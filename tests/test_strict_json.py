from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from godot_game_test_lab.strict_json import StrictJsonError, load_strict_json_object


def write_bytes(path: Path, value: bytes) -> Path:
    path.write_bytes(value)
    return path


def test_strict_json_returns_the_hash_of_the_parsed_bytes(tmp_path: Path) -> None:
    source = b'{"schemaVersion":"1.0","targets":[]}\n'
    path = write_bytes(tmp_path / "manifest.json", source)

    value, sha256 = load_strict_json_object(path, maximum_bytes=1024)

    assert value == {"schemaVersion": "1.0", "targets": []}
    assert sha256 == hashlib.sha256(source).hexdigest()


@pytest.mark.parametrize(
    "source, expected",
    [
        (b'{"id":"first","id":"second"}', "duplicate JSON property"),
        (
            b'{"target":{"sha":"first","sha":"second"}}',
            "duplicate JSON property",
        ),
        (b"\xef\xbb\xbf{}", "UTF-8 BOM"),
        (b'{"value":NaN}', "non-standard JSON constant"),
        (b'{"value":-0}', "negative zero"),
        (b'{"value":-0.0}', "negative zero"),
        (b'{"value":"\\ud800"}', "invalid Unicode"),
        (b"[]", "root must be an object"),
    ],
)
def test_strict_json_rejects_ambiguous_inputs(
    tmp_path: Path,
    source: bytes,
    expected: str,
) -> None:
    path = write_bytes(tmp_path / "invalid.json", source)

    with pytest.raises(StrictJsonError, match=expected):
        load_strict_json_object(path, maximum_bytes=1024)


def test_strict_json_rejects_invalid_utf8_and_oversized_input(
    tmp_path: Path,
) -> None:
    invalid = write_bytes(tmp_path / "invalid-utf8.json", b'{"x":"\xff"}')
    oversized = write_bytes(tmp_path / "oversized.json", b'{"padding":"1234"}')

    with pytest.raises(StrictJsonError, match="valid UTF-8"):
        load_strict_json_object(invalid, maximum_bytes=1024)
    with pytest.raises(StrictJsonError, match="byte length"):
        load_strict_json_object(oversized, maximum_bytes=8)


def test_strict_json_rejects_symbolic_links(tmp_path: Path) -> None:
    source = write_bytes(tmp_path / "source.json", b"{}")
    linked = tmp_path / "linked.json"
    try:
        linked.symlink_to(source)
    except OSError:
        pytest.skip("symbolic links are unavailable on this runner")

    with pytest.raises(StrictJsonError, match="non-symbolic-link"):
        load_strict_json_object(linked, maximum_bytes=1024)


def test_strict_json_rejects_descriptor_identity_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = write_bytes(tmp_path / "manifest.json", b'{"value":1}')
    original_fstat = os.fstat
    calls = 0

    def drifting_fstat(descriptor: int) -> os.stat_result:
        nonlocal calls
        calls += 1
        observed = original_fstat(descriptor)
        if calls == 2:
            values = list(observed)
            values[6] += 1
            return os.stat_result(values)
        return observed

    monkeypatch.setattr(os, "fstat", drifting_fstat)

    with pytest.raises(StrictJsonError, match="changed while it was read"):
        load_strict_json_object(path, maximum_bytes=1024)


def test_strict_json_reads_through_one_open_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = write_bytes(tmp_path / "manifest.json", b'{"value":1}')
    original_open = os.open
    original_read = os.read
    opened: list[int] = []
    reads: list[int] = []

    def observed_open(target: os.PathLike[str], flags: int) -> int:
        descriptor = original_open(target, flags)
        opened.append(descriptor)
        return descriptor

    def observed_read(descriptor: int, count: int) -> bytes:
        reads.append(descriptor)
        return original_read(descriptor, count)

    monkeypatch.setattr(os, "open", observed_open)
    monkeypatch.setattr(os, "read", observed_read)

    value, _ = load_strict_json_object(path, maximum_bytes=1024)

    assert value == {"value": 1}
    assert len(opened) == 1
    assert reads
    assert set(reads) == set(opened)
