#!/usr/bin/env bash
set -euo pipefail

LAB_ROOT="${LAB_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)}"
GODOT_VERSION="${GODOT_VERSION:-4.6.3}"
FLAVOR="${FLAVOR:-all}"
IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-evavo/godot-lab-sandbox}"
RECEIPT_PATH="${RECEIPT_PATH:-}"
NO_CACHE="${NO_CACHE:-0}"
PULL_BASE_IMAGE="${PULL_BASE_IMAGE:-0}"

fail() {
  printf '[godot-lab] %s\n' "$*" >&2
  exit 2
}

[[ "$(uname -s)" == Linux ]] || fail "Use Build-GodotLabSandboxes.ps1 on Windows."
[[ "$GODOT_VERSION" =~ ^4\.[0-9]+\.[0-9]+$ ]] || \
  fail "GODOT_VERSION must be an explicit stable Godot 4.x.y version."
[[ "$FLAVOR" == standard || "$FLAVOR" == mono || "$FLAVOR" == all ]] || \
  fail "FLAVOR must be standard, mono, or all."
command -v docker >/dev/null 2>&1 || fail "Docker Engine is required."
docker version --format '{{.Server.Version}}' >/dev/null
[[ -f "$LAB_ROOT/containers/linux-sandbox/Dockerfile" ]] || \
  fail "Linux sandbox Dockerfile is missing."

if [[ "$FLAVOR" == all ]]; then
  flavors=(standard mono)
else
  flavors=("$FLAVOR")
fi

records=()
for selected in "${flavors[@]}"; do
  tag="${IMAGE_REPOSITORY}:${GODOT_VERSION}-${selected}"
  args=(
    build
    --file "$LAB_ROOT/containers/linux-sandbox/Dockerfile"
    --build-arg "GODOT_VERSION=$GODOT_VERSION"
    --build-arg "GODOT_FLAVOR=$selected"
    --label dev.evavo.godot-lab.version=0.7.0
    --label "dev.evavo.godot.version=$GODOT_VERSION"
    --label "dev.evavo.godot.flavor=$selected"
    --tag "$tag"
  )
  [[ "$NO_CACHE" == 1 ]] && args+=(--no-cache)
  [[ "$PULL_BASE_IMAGE" == 1 ]] && args+=(--pull)
  args+=("$LAB_ROOT")
  printf '[godot-lab] Building %s\n' "$tag"
  docker "${args[@]}"
  image_id="$(docker image inspect "$tag" --format '{{.Id}}')"
  [[ -n "$image_id" ]] || fail "Docker did not return an image identity for $tag"
  records+=("$tag|$image_id|$selected")
done

python3 - "$LAB_ROOT" "$GODOT_VERSION" "$RECEIPT_PATH" "${records[@]}" <<'PY'
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

lab, version, destination, *records = sys.argv[1:]
value = {
    "schemaVersion": "1.0",
    "status": "ready",
    "labRoot": lab,
    "createdAt": datetime.now(UTC).isoformat(),
    "images": [
        {
            "tag": tag,
            "imageId": image_id,
            "godotVersion": version,
            "flavor": flavor,
        }
        for tag, image_id, flavor in (record.split("|", 2) for record in records)
    ],
}
rendered = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
if destination:
    path = Path(destination).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")
print(rendered, end="")
PY
