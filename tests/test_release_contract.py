from __future__ import annotations

import json
import tomllib
from pathlib import Path

from godot_game_test_lab import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_release_version_is_consistent_across_authorities() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    reliability = json.loads(
        (ROOT / "evavo.reliability.json").read_text(encoding="utf-8")
    )
    schema = json.loads(
        (ROOT / "schemas" / "repository-owned-reliability-profile.schema.json").read_text(
            encoding="utf-8"
        )
    )

    expected = "0.7.0"
    assert __version__ == expected
    assert pyproject["project"]["version"] == expected
    assert reliability["toolVersion"] == expected
    assert schema["properties"]["toolVersion"]["const"] == expected
