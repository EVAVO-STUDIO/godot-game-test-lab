from __future__ import annotations

import json
import re

import pytest

from godot_game_test_lab.movie_source_identity import (
    CAPTURE_MOVIE_SOURCE_PATHS,
    TEMPORAL_MOVIE_SOURCE_PATHS,
    capture_movie_source_identity,
    movie_source_identities,
    temporal_movie_source_identity,
)
from godot_game_test_lab.movie_source_identity_cli import main, source_identity_result

_SHA256 = re.compile(r"^[a-f0-9]{64}$")


def test_source_identities_are_deterministic_and_distinct() -> None:
    first = movie_source_identities()
    second = movie_source_identities()
    assert first == second
    assert set(first) == {
        "godot-game-test-lab.video-evidence",
        "godot-game-test-lab.movie-temporal",
    }
    assert first["godot-game-test-lab.video-evidence"] == capture_movie_source_identity()
    assert first["godot-game-test-lab.movie-temporal"] == temporal_movie_source_identity()
    assert all(_SHA256.fullmatch(value) for value in first.values())
    assert first["godot-game-test-lab.video-evidence"] != first[
        "godot-game-test-lab.movie-temporal"
    ]


def test_source_identity_paths_cover_each_provider_trust_boundary() -> None:
    for path in (
        "src/godot_game_test_lab/movie_evidence.py",
        "src/godot_game_test_lab/movie_evidence_cli.py",
        "src/godot_game_test_lab/movie_source_identity.py",
        "src/godot_game_test_lab/visual_path_security.py",
    ):
        assert path in CAPTURE_MOVIE_SOURCE_PATHS
    for path in (
        "src/godot_game_test_lab/movie_evidence.py",
        "src/godot_game_test_lab/movie_temporal.py",
        "src/godot_game_test_lab/movie_temporal_cli.py",
        "src/godot_game_test_lab/movie_source_identity.py",
        "src/godot_game_test_lab/visual_path_security.py",
    ):
        assert path in TEMPORAL_MOVIE_SOURCE_PATHS


def test_source_identity_paths_are_unique_and_canonical() -> None:
    for paths in (CAPTURE_MOVIE_SOURCE_PATHS, TEMPORAL_MOVIE_SOURCE_PATHS):
        assert len(paths) == len(set(paths))
        assert all("\\" not in path for path in paths)
        assert all(not path.startswith("/") for path in paths)
        assert all(
            part not in {"", ".", ".."}
            for path in paths
            for part in path.split("/")
        )


def test_all_identity_result_is_source_only_not_runtime_or_worker_proof() -> None:
    result = source_identity_result("all")
    assert result["schema"] == "evavo.godot-movie-source-identities.v1"
    assert result["status"] == "source-present"
    assert result["ready"] is True
    assert result["workerAdmitted"] is False
    assert result["identities"] == movie_source_identities()
    assert "do not prove" in str(result["truthBoundary"])


@pytest.mark.parametrize(
    ("selector", "adapter_id"),
    [
        ("capture", "godot-game-test-lab.video-evidence"),
        ("temporal", "godot-game-test-lab.movie-temporal"),
    ],
)
def test_filtered_identity_result_returns_only_the_requested_provider(
    selector: str,
    adapter_id: str,
) -> None:
    result = source_identity_result(selector)
    identities = result["identities"]
    assert isinstance(identities, dict)
    assert identities == {adapter_id: movie_source_identities()[adapter_id]}


def test_cli_prints_machine_readable_identity_result(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--adapter", "capture"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["ready"] is True
    assert list(output["identities"]) == ["godot-game-test-lab.video-evidence"]
    assert _SHA256.fullmatch(
        output["identities"]["godot-game-test-lab.video-evidence"]
    )
