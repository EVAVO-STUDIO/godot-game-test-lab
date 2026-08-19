from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from godot_game_test_lab.automated_testing_probe import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
