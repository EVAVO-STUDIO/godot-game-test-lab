#!/usr/bin/env python3
"""Repository wrapper for the installed resilient Godot import command."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from godot_game_test_lab.resilient_import import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
