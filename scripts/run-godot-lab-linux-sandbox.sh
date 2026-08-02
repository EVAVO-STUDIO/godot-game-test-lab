#!/usr/bin/env bash
set -euo pipefail

LAB_ROOT="${LAB_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PYTHON="${PYTHON:-$LAB_ROOT/.venv/bin/python}"

if [[ ! -x "$PYTHON" ]]; then
  PYTHON="${PYTHON_FALLBACK:-python3.11}"
fi

exec "$PYTHON" -m godot_game_test_lab.local_sandbox "$@"
