#!/usr/bin/env python3
"""Repository wrapper for the installed resilient Godot import command."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))
    from godot_game_test_lab.resilient_import import main as resilient_main

    return resilient_main()


if __name__ == "__main__":
    raise SystemExit(main())
