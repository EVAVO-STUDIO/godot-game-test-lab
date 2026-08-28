#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
RUNTIME_ROOT="${1:-${SCRIPT_DIR}/../../godot-web-runtime}"
PYTHON_EXECUTABLE="${PYTHON_EXECUTABLE:-python3}"

if [[ ! -d "${RUNTIME_ROOT}" ]]; then
  printf 'Godot Web Runtime root is unavailable: %s\n' "${RUNTIME_ROOT}" >&2
  exit 2
fi

exec "${PYTHON_EXECUTABLE}" \
  "${SCRIPT_DIR}/check_web_export_descriptor_fixture.py" \
  --runtime-root "$(cd -- "${RUNTIME_ROOT}" && pwd -P)" \
  --json
