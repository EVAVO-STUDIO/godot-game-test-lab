from __future__ import annotations

import hashlib
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
