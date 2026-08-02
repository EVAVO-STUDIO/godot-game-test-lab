#!/usr/bin/env bash
set -euo pipefail

LAB_ROOT="${LAB_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PYTHON="${PYTHON:-python3.11}"
ENGINE_VERSION="${ENGINE_VERSION:-4.6.3}"
ENGINE_ROOT="${EVAVO_GODOT_HOME:-${XDG_CACHE_HOME:-$HOME/.cache}/evavo/godot-game-test-lab/engines}"
TARGET_ROOT="${TARGET_ROOT:-$HOME/GitRepos}"
EVIDENCE_ROOT="${EVAVO_GODOT_LAB_EVIDENCE_ROOT:-${XDG_DATA_HOME:-$HOME/.local/share}/EVAVO/GodotLabEvidence}"
OFFLINE_SOURCE_DIR="${OFFLINE_SOURCE_DIR:-}"
PREPARE_ESTATE="${PREPARE_ESTATE:-0}"
PREPARE_SANDBOX_IMAGES="${PREPARE_SANDBOX_IMAGES:-0}"
DOCKER="${DOCKER:-docker}"
SKIP_AGENT_BRIDGE="${SKIP_AGENT_BRIDGE:-0}"
SKIP_EXPORT_TEMPLATES="${SKIP_EXPORT_TEMPLATES:-0}"
FORCE_ENGINE_INSTALL="${FORCE_ENGINE_INSTALL:-0}"

[[ -f "$LAB_ROOT/pyproject.toml" ]] || { echo "Invalid LAB_ROOT: $LAB_ROOT" >&2; exit 2; }
[[ -d "$TARGET_ROOT" ]] || { echo "Target root does not exist: $TARGET_ROOT" >&2; exit 2; }
mkdir -p "$ENGINE_ROOT" "$EVIDENCE_ROOT"
LAB_ROOT="$(cd "$LAB_ROOT" && pwd -P)"
TARGET_ROOT="$(cd "$TARGET_ROOT" && pwd -P)"
ENGINE_ROOT="$(cd "$ENGINE_ROOT" && pwd -P)"
EVIDENCE_ROOT="$(cd "$EVIDENCE_ROOT" && pwd -P)"
case "$ENGINE_ROOT/" in "$LAB_ROOT/"*|"$TARGET_ROOT/"*) echo "Engine root must be external." >&2; exit 2;; esac
case "$EVIDENCE_ROOT/" in "$LAB_ROOT/"*|"$TARGET_ROOT/"*) echo "Evidence root must be external." >&2; exit 2;; esac

"$PYTHON" -c 'import sys; assert sys.version_info[:2] == (3, 11), sys.version'
VENV="$LAB_ROOT/.venv"
[[ -x "$VENV/bin/python" ]] || "$PYTHON" -m venv "$VENV"
VENV_PYTHON="$VENV/bin/python"
EXTRAS='.[dev,agent]'
[[ "$SKIP_AGENT_BRIDGE" == 1 ]] && EXTRAS='.[dev]'
(
  cd "$LAB_ROOT"
  "$VENV_PYTHON" -m pip install --disable-pip-version-check --editable "$EXTRAS"
)

BOOTSTRAP_REPORT="$EVIDENCE_ROOT/managed-engine-bootstrap.json"
ENGINE_ARGS=(
  -m godot_game_test_lab.cli engine bootstrap
  --version "$ENGINE_VERSION"
  --flavors standard,mono
  --root "$ENGINE_ROOT"
  --output "$BOOTSTRAP_REPORT"
)
[[ "$SKIP_EXPORT_TEMPLATES" == 1 ]] && ENGINE_ARGS+=(--no-templates)
[[ "$FORCE_ENGINE_INSTALL" == 1 ]] && ENGINE_ARGS+=(--force)
if [[ -n "$OFFLINE_SOURCE_DIR" ]]; then
  OFFLINE_SOURCE_DIR="$(cd "$OFFLINE_SOURCE_DIR" && pwd -P)"
  ENGINE_ARGS+=(--source-dir "$OFFLINE_SOURCE_DIR" --offline)
fi
PYTHONPATH="$LAB_ROOT/src" "$VENV_PYTHON" "${ENGINE_ARGS[@]}"

readarray -t ENGINE_VALUES < <(
  "$VENV_PYTHON" - "$BOOTSTRAP_REPORT" <<'PY'
import json, sys
value=json.load(open(sys.argv[1], encoding="utf-8"))
standard=next(x for x in value["installations"] if x["flavor"]=="standard")
mono=next(x for x in value["installations"] if x["flavor"]=="mono")
print(standard["executable"])
print(mono["executable"])
PY
)
GODOT_BIN="${ENGINE_VALUES[0]}"
GODOT_MONO_BIN="${ENGINE_VALUES[1]}"
export EVAVO_GODOT_LAB_ROOT="$LAB_ROOT"
export EVAVO_GODOT_HOME="$ENGINE_ROOT"
export EVAVO_GODOT_LAB_ALLOWED_ROOTS="$TARGET_ROOT"
export EVAVO_GODOT_LAB_EVIDENCE_ROOT="$EVIDENCE_ROOT"
export GODOT_BIN GODOT_MONO_BIN

ENV_FILE="$EVIDENCE_ROOT/godot-lab-env.sh"
{
  printf 'export EVAVO_GODOT_LAB_ROOT=%q\n' "$LAB_ROOT"
  printf 'export EVAVO_GODOT_HOME=%q\n' "$ENGINE_ROOT"
  printf 'export EVAVO_GODOT_LAB_ALLOWED_ROOTS=%q\n' "$TARGET_ROOT"
  printf 'export EVAVO_GODOT_LAB_EVIDENCE_ROOT=%q\n' "$EVIDENCE_ROOT"
  printf 'export GODOT_BIN=%q\n' "$GODOT_BIN"
  printf 'export GODOT_MONO_BIN=%q\n' "$GODOT_MONO_BIN"
  printf 'export PATH=%q:$PATH\n' "$VENV/bin"
} > "$ENV_FILE"
chmod 600 "$ENV_FILE"

if [[ "$PREPARE_ESTATE" == 1 ]]; then
  ESTATE_REPORT="$EVIDENCE_ROOT/managed-engine-estate.json"
  PREPARE_ARGS=(
    -m godot_game_test_lab.cli engine prepare "$TARGET_ROOT"
    --root "$ENGINE_ROOT" --output "$ESTATE_REPORT"
  )
  [[ "$SKIP_EXPORT_TEMPLATES" == 1 ]] && PREPARE_ARGS+=(--no-templates)
  if [[ -n "$OFFLINE_SOURCE_DIR" ]]; then
    PREPARE_ARGS+=(--source-dir "$OFFLINE_SOURCE_DIR" --offline)
  fi
  "$VENV_PYTHON" "${PREPARE_ARGS[@]}" || {
    echo "One or more estate projects were not prepared; inspect $ESTATE_REPORT" >&2
  }
fi

"$VENV_PYTHON" -m godot_game_test_lab.cli doctor
MCP_CONFIG=""
if [[ "$SKIP_AGENT_BRIDGE" != 1 ]]; then
  "$VENV_PYTHON" -m godot_game_test_lab.mcp_server \
    --lab-root "$LAB_ROOT" \
    --allowed-root "$TARGET_ROOT" \
    --evidence-root "$EVIDENCE_ROOT" \
    --engine-root "$ENGINE_ROOT" \
    --allow-noninteractive \
    --self-test
  MCP_CONFIG="$EVIDENCE_ROOT/godot-lab-mcp.json"
  "$VENV_PYTHON" - "$MCP_CONFIG" "$LAB_ROOT" "$TARGET_ROOT" \
    "$EVIDENCE_ROOT" "$ENGINE_ROOT" "$VENV_PYTHON" <<'PY_MCP'
import json
import sys
from pathlib import Path

output, lab, target, evidence, engines, python = map(str, sys.argv[1:])
value = {
    "mcpServers": {
        "evavo-godot-game-test-lab": {
            "command": python,
            "args": [
                "-m",
                "godot_game_test_lab.mcp_server",
                "--transport",
                "stdio",
                "--lab-root",
                lab,
                "--allowed-root",
                target,
                "--evidence-root",
                evidence,
                "--engine-root",
                engines,
                "--allow-noninteractive",
            ],
        }
    }
}
Path(output).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
PY_MCP
  chmod 600 "$MCP_CONFIG"
fi

SANDBOX_IMAGES_JSON='[]'
if [[ "$PREPARE_SANDBOX_IMAGES" == 1 ]]; then
  command -v "$DOCKER" >/dev/null 2>&1 || {
    echo "Docker Engine is required when PREPARE_SANDBOX_IMAGES=1." >&2
    exit 2
  }
  "$VENV_PYTHON" -m godot_game_test_lab.cli sandbox status \
    --docker "$DOCKER" \
    --output "$EVIDENCE_ROOT/linux-sandbox-status.json"
  sandbox_reports=()
  for flavor in standard mono; do
    report="$EVIDENCE_ROOT/linux-sandbox-${flavor}.json"
    "$VENV_PYTHON" -m godot_game_test_lab.cli sandbox image \
      --lab-root "$LAB_ROOT" \
      --version "$ENGINE_VERSION" \
      --flavor "$flavor" \
      --docker "$DOCKER" \
      --output "$report"
    sandbox_reports+=("$report")
  done
  SANDBOX_IMAGES_JSON="$($VENV_PYTHON - "${sandbox_reports[@]}" <<'PY_SANDBOX'
import json
import sys

print(json.dumps([json.load(open(path, encoding="utf-8")) for path in sys.argv[1:]]))
PY_SANDBOX
)"
fi

command -v ffmpeg >/dev/null 2>&1 || echo "Warning: ffmpeg is required for media evidence." >&2
command -v ffprobe >/dev/null 2>&1 || echo "Warning: ffprobe is required for media evidence." >&2
command -v dotnet >/dev/null 2>&1 || echo "Warning: .NET SDK 8 is required for C# games." >&2

"$VENV_PYTHON" - "$EVIDENCE_ROOT/godot-lab-installation.json" <<PY
import json, sys
json.dump({
  "schemaVersion":"1.0", "status":"ready", "labRoot":${LAB_ROOT@Q},
  "python":${VENV_PYTHON@Q}, "engineVersion":${ENGINE_VERSION@Q},
  "engineRoot":${ENGINE_ROOT@Q}, "standardGodot":${GODOT_BIN@Q},
  "monoGodot":${GODOT_MONO_BIN@Q}, "evidenceRoot":${EVIDENCE_ROOT@Q},
  "targetRoot":${TARGET_ROOT@Q}, "environmentFile":${ENV_FILE@Q},
  "mcpConfig":${MCP_CONFIG@Q} or None,
  "estatePrepared":${PREPARE_ESTATE@Q} == "1",
  "sandboxImagesPrepared":${PREPARE_SANDBOX_IMAGES@Q} == "1",
  "sandboxImages":json.loads(${SANDBOX_IMAGES_JSON@Q})
}, open(sys.argv[1], "w", encoding="utf-8"), indent=2)
open(sys.argv[1], "a", encoding="utf-8").write("\n")
PY
printf '[godot-lab] Installation complete. Run: source %q\n' "$ENV_FILE"
