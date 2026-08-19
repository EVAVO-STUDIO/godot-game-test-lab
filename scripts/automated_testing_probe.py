from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

main = import_module("godot_game_test_lab.automated_testing_probe").main


if __name__ == "__main__":
    raise SystemExit(main())
