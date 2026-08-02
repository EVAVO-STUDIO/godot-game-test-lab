#!/usr/bin/env bash
set -euo pipefail

LAB_ROOT="${LAB_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)}"
TARGET_REPOSITORY_PATH="${TARGET_REPOSITORY_PATH:-}"
PROJECT_SUBPATH="${PROJECT_SUBPATH:-.}"
PROFILE_PATH="${PROFILE_PATH:-}"
EVIDENCE_ROOT="${EVIDENCE_ROOT:-${XDG_DATA_HOME:-$HOME/.local/share}/EVAVO/GodotLabEvidence}"
ARTIFACT_PATH="${ARTIFACT_PATH:-}"
GODOT_VERSION="${GODOT_VERSION:-4.6.3}"
IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-evavo/godot-lab-sandbox}"
EXPECTED_LAB_SHA="${EXPECTED_LAB_SHA:-}"
EXPECTED_TARGET_SHA="${EXPECTED_TARGET_SHA:-}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-600}"
BOOT_FRAMES="${BOOT_FRAMES:-30}"
CPU_COUNT="${CPU_COUNT:-4}"
MEMORY="${MEMORY:-10g}"
BUILD_IMAGE="${BUILD_IMAGE:-0}"
NO_CACHE="${NO_CACHE:-0}"

fail() {
  printf '[godot-lab] %s\n' "$*" >&2
  exit 2
}

is_within() {
  local candidate="$1/" parent="$2/"
  [[ "$candidate" == "$parent"* ]]
}

git_optional() {
  local root="$1"
  shift
  git -C "$root" "$@" 2>/dev/null || true
}

[[ "$(uname -s)" == Linux ]] || fail "Use Invoke-GodotLabSandbox.ps1 on Windows."
[[ -n "$TARGET_REPOSITORY_PATH" ]] || fail "Set TARGET_REPOSITORY_PATH."
[[ "$GODOT_VERSION" =~ ^4\.[0-9]+\.[0-9]+$ ]] || fail "Invalid GODOT_VERSION."
[[ "$TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] && (( TIMEOUT_SECONDS >= 30 && TIMEOUT_SECONDS <= 3600 )) || \
  fail "TIMEOUT_SECONDS must be between 30 and 3600."
[[ "$BOOT_FRAMES" =~ ^[0-9]+$ ]] && (( BOOT_FRAMES <= 3600 )) || \
  fail "BOOT_FRAMES must be between 0 and 3600."
command -v docker >/dev/null 2>&1 || fail "Docker Engine is required."
docker version --format '{{.Server.Version}}' >/dev/null

LAB_ROOT="$(cd "$LAB_ROOT" && pwd -P)"
TARGET_REPOSITORY_PATH="$(cd "$TARGET_REPOSITORY_PATH" && pwd -P)"
mkdir -p "$EVIDENCE_ROOT"
EVIDENCE_ROOT="$(cd "$EVIDENCE_ROOT" && pwd -P)"
if is_within "$EVIDENCE_ROOT" "$LAB_ROOT" || is_within "$LAB_ROOT" "$EVIDENCE_ROOT" || \
   is_within "$EVIDENCE_ROOT" "$TARGET_REPOSITORY_PATH" || \
   is_within "$TARGET_REPOSITORY_PATH" "$EVIDENCE_ROOT"; then
  fail "EVIDENCE_ROOT must remain separate from both source repositories."
fi
if [[ -z "$ARTIFACT_PATH" ]]; then
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  ARTIFACT_PATH="$EVIDENCE_ROOT/sandbox/$(basename "$TARGET_REPOSITORY_PATH")/$stamp"
fi
mkdir -p "$ARTIFACT_PATH"
ARTIFACT_PATH="$(cd "$ARTIFACT_PATH" && pwd -P)"
is_within "$ARTIFACT_PATH" "$EVIDENCE_ROOT" || fail "ARTIFACT_PATH must remain under EVIDENCE_ROOT."
[[ -z "$(find "$ARTIFACT_PATH" -mindepth 1 -maxdepth 1 -print -quit)" ]] || \
  fail "ARTIFACT_PATH must be new or empty."

before_sha="$(git_optional "$TARGET_REPOSITORY_PATH" rev-parse HEAD)"
before_status="$(git_optional "$TARGET_REPOSITORY_PATH" status --porcelain=v1 --untracked-files=all)"
lab_sha="$(git_optional "$LAB_ROOT" rev-parse HEAD)"
[[ -z "$EXPECTED_TARGET_SHA" || "$before_sha" == "$EXPECTED_TARGET_SHA" ]] || \
  fail "Target HEAD does not match EXPECTED_TARGET_SHA."
[[ -z "$EXPECTED_LAB_SHA" || "$lab_sha" == "$EXPECTED_LAB_SHA" ]] || \
  fail "Lab HEAD does not match EXPECTED_LAB_SHA."

python="$LAB_ROOT/.venv/bin/python"
[[ -x "$python" ]] || python="${PYTHON:-python3.11}"
command -v "$python" >/dev/null 2>&1 || [[ -x "$python" ]] || \
  fail "Python 3.11 is required; run scripts/install-godot-lab.sh first."
normalised_profile="$ARTIFACT_PATH/profile.normalized.json"
if [[ -n "$PROFILE_PATH" ]]; then
  if [[ "$PROFILE_PATH" != /* ]]; then
    PROFILE_PATH="$TARGET_REPOSITORY_PATH/$PROFILE_PATH"
  fi
  PROFILE_PATH="$(cd "$(dirname "$PROFILE_PATH")" && pwd -P)/$(basename "$PROFILE_PATH")"
  [[ -f "$PROFILE_PATH" ]] || fail "Profile does not exist: $PROFILE_PATH"
  is_within "$PROFILE_PATH" "$TARGET_REPOSITORY_PATH" || \
    fail "PROFILE_PATH must remain inside the target repository."
  "$python" "$LAB_ROOT/scripts/read_linux_sandbox_profile.py" \
    --profile "$PROFILE_PATH" --output "$normalised_profile" >/dev/null
else
  python3 - "$normalised_profile" "$PROJECT_SUBPATH" <<'PY'
import json, sys
from pathlib import PurePosixPath
path, subpath = sys.argv[1:]
subpath = subpath.replace("\\", "/").strip()
pure = PurePosixPath(subpath)
if not subpath or pure.is_absolute() or any(part in {"", ".."} for part in pure.parts):
    raise SystemExit("PROJECT_SUBPATH must be a bounded relative path")
value = {
    "schemaVersion": "2.0",
    "projectSubpath": pure.as_posix(),
    "minimumGodotVersion": "4.6.2",
    "engineFlavor": "auto",
    "visual": {
        "required": True,
        "scene": "",
        "frames": 180,
        "fps": 30,
        "width": 1280,
        "height": 720,
        "renderingMethod": "gl_compatibility",
        "userArguments": [],
    },
    "export": {"required": False, "preset": ""},
    "journeys": [],
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(value, handle, indent=2)
    handle.write("\n")
PY
fi

readarray -t profile_values < <(
  python3 - "$normalised_profile" <<'PY'
import json, sys
value=json.load(open(sys.argv[1], encoding="utf-8"))
visual=value["visual"]
print(value["projectSubpath"])
print(value["minimumGodotVersion"])
print(value["engineFlavor"])
print(visual["scene"])
print(visual["frames"])
print(visual["fps"])
print(visual["width"])
print(visual["height"])
print(visual["renderingMethod"])
print(json.dumps(visual.get("userArguments", []), separators=(",", ":")))
print(value["export"].get("preset", ""))
PY
)
profile_subpath="${profile_values[0]}"
minimum_version="${profile_values[1]}"
flavor="${profile_values[2]}"
project_root="$TARGET_REPOSITORY_PATH"
[[ "$profile_subpath" == . ]] || project_root="$TARGET_REPOSITORY_PATH/$profile_subpath"
[[ -f "$project_root/project.godot" ]] || fail "Selected project does not contain project.godot."
has_csharp=0
find "$project_root" -type f -name '*.csproj' -print -quit | grep -q . && has_csharp=1
if [[ "$flavor" == auto ]]; then
  if [[ "$has_csharp" == 1 ]]; then flavor=mono; else flavor=standard; fi
fi
[[ "$has_csharp" == 0 || "$flavor" == mono ]] || fail "C# targets require the mono image."
if ! python3 - "$GODOT_VERSION" "$minimum_version" <<'PY'
import sys
actual=tuple(map(int,sys.argv[1].split('.')))
minimum=tuple(map(int,sys.argv[2].split('.')))
raise SystemExit(0 if actual >= minimum else 2)
PY
then
  fail "GODOT_VERSION is below the profile minimum."
fi

image="${IMAGE_REPOSITORY}:${GODOT_VERSION}-${flavor}"
if [[ "$BUILD_IMAGE" == 1 ]] || ! docker image inspect "$image" >/dev/null 2>&1; then
  LAB_ROOT="$LAB_ROOT" GODOT_VERSION="$GODOT_VERSION" FLAVOR="$flavor" \
    IMAGE_REPOSITORY="$IMAGE_REPOSITORY" NO_CACHE="$NO_CACHE" \
    "$LAB_ROOT/scripts/build-godot-lab-sandboxes.sh" >/dev/null
fi
docker image inspect "$image" >/dev/null

work="$(mktemp -d "${TMPDIR:-/tmp}/godot-lab-sandbox.XXXXXX")"
container="evavo-godot-$(printf '%s' "$RANDOM$RANDOM" | sha256sum | cut -c1-12)"
cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  rm -rf "$work"
  after_sha="$(git_optional "$TARGET_REPOSITORY_PATH" rev-parse HEAD)"
  after_status="$(git_optional "$TARGET_REPOSITORY_PATH" status --porcelain=v1 --untracked-files=all)"
  [[ -z "$before_sha" || "$after_sha" == "$before_sha" ]] || \
    fail "The sandbox changed the target repository HEAD."
  [[ "$after_status" == "$before_status" ]] || \
    fail "The sandbox changed the target repository working tree."
}
trap cleanup EXIT INT TERM
chmod 0777 "$work" "$ARTIFACT_PATH"

python3 - "$ARTIFACT_PATH/local-sandbox-dispatch.json" "$TARGET_REPOSITORY_PATH" \
  "$before_sha" "$LAB_ROOT" "$lab_sha" "$profile_subpath" "$normalised_profile" \
  "$image" "$flavor" "$GODOT_VERSION" <<'PY'
import json, sys
from datetime import UTC, datetime
(
    output,target,target_sha,lab,lab_sha,project,profile,image,flavor,version
)=sys.argv[1:]
value={
    "schemaVersion":"1.0","status":"dispatched","targetRoot":target,
    "targetSha":target_sha or None,"labRoot":lab,"labSha":lab_sha or None,
    "projectSubpath":project,"profile":profile,"image":image,"flavor":flavor,
    "godotVersion":version,"network":"none","sourceReadOnly":True,
    "rootFilesystemReadOnly":True,"createdAt":datetime.now(UTC).isoformat(),
}
with open(output,"w",encoding="utf-8") as handle:
    json.dump(value,handle,indent=2)
    handle.write("\n")
PY

timeout --signal=TERM --kill-after=15s "$((TIMEOUT_SECONDS + 300))"s \
  docker run --rm \
    --name "$container" \
    --stop-timeout 10 \
    --network none \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --pids-limit 1024 \
    --cpus "$CPU_COUNT" \
    --memory "$MEMORY" \
    --memory-swap "$MEMORY" \
    --ulimit nofile=4096:4096 \
    --shm-size 1g \
    --tmpfs /tmp:rw,nosuid,nodev,noexec,size=1g,mode=1777 \
    --tmpfs /home/godotlab:rw,nosuid,nodev,size=2g,mode=0700,uid=10001,gid=10001 \
    --mount "type=bind,source=$TARGET_REPOSITORY_PATH,target=/workspace/source,readonly" \
    --mount "type=bind,source=$normalised_profile,target=/workspace/profile.normalized.json,readonly" \
    --mount "type=bind,source=$work,target=/workspace/work" \
    --mount "type=bind,source=$ARTIFACT_PATH,target=/artifacts" \
    --env "EVAVO_TARGET_REPOSITORY=local/$(basename "$TARGET_REPOSITORY_PATH")" \
    --env "EVAVO_TARGET_SHA=$before_sha" \
    --env "EVAVO_LAB_SHA=$lab_sha" \
    --env EVAVO_PROFILE_PATH=/workspace/profile.normalized.json \
    --env "EVAVO_PROJECT_SUBPATH=$profile_subpath" \
    --env "EVAVO_MINIMUM_GODOT_VERSION=$minimum_version" \
    --env "EVAVO_TIMEOUT_SECONDS=$TIMEOUT_SECONDS" \
    --env "EVAVO_BOOT_FRAMES=$BOOT_FRAMES" \
    --env "EVAVO_VISUAL_SCENE=${profile_values[3]}" \
    --env "EVAVO_VISUAL_FRAMES=${profile_values[4]}" \
    --env "EVAVO_VISUAL_FPS=${profile_values[5]}" \
    --env "EVAVO_VISUAL_WIDTH=${profile_values[6]}" \
    --env "EVAVO_VISUAL_HEIGHT=${profile_values[7]}" \
    --env "EVAVO_RENDERING_METHOD=${profile_values[8]}" \
    --env "EVAVO_VISUAL_ARGUMENTS_JSON=${profile_values[9]}" \
    --env "EVAVO_EXPORT_PRESET=${profile_values[10]}" \
    "$image"

printf '[godot-lab] Sandbox evidence: %s\n' "$ARTIFACT_PATH"
