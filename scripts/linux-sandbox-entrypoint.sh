#!/usr/bin/env bash
set -euo pipefail
umask 077

source_root="${EVAVO_SOURCE_ROOT:-/workspace/source}"
working_root="${EVAVO_WORKING_ROOT:-/workspace/work/project}"
artifacts_root="${EVAVO_ARTIFACTS_ROOT:-/artifacts}"
project_subpath="${EVAVO_PROJECT_SUBPATH:-.}"
godot_bin="${GODOT_BIN:-/usr/local/bin/godot}"
dotnet_bin="${DOTNET_BIN:-/usr/bin/dotnet}"
minimum_version="${EVAVO_MINIMUM_GODOT_VERSION:-4.6.2}"
timeout_seconds="${EVAVO_TIMEOUT_SECONDS:-600}"
boot_frames="${EVAVO_BOOT_FRAMES:-30}"
visual_scene="${EVAVO_VISUAL_SCENE:-}"
visual_frames="${EVAVO_VISUAL_FRAMES:-180}"
visual_fps="${EVAVO_VISUAL_FPS:-30}"
visual_width="${EVAVO_VISUAL_WIDTH:-1280}"
visual_height="${EVAVO_VISUAL_HEIGHT:-720}"
rendering_method="${EVAVO_RENDERING_METHOD:-gl_compatibility}"
visual_arguments_json="${EVAVO_VISUAL_ARGUMENTS_JSON:-[]}"
export_preset="${EVAVO_EXPORT_PRESET:-}"

if [[ ! -d "${source_root}" ]]; then
    echo "Linux sandbox source mount is missing: ${source_root}" >&2
    exit 2
fi

mount_options="$(findmnt -T "${source_root}" -no OPTIONS 2>/dev/null || true)"
if [[ ",${mount_options}," != *,ro,* ]]; then
    echo "Linux sandbox source mount must be read-only." >&2
    exit 2
fi

mkdir -p "${HOME}/.local/share/godot/export_templates" "${artifacts_root}"
cp -a /opt/godot/export_templates/. "${HOME}/.local/share/godot/export_templates/"

arguments=(
    "${source_root}"
    --working-root "${working_root}"
    --artifacts "${artifacts_root}"
    --project-subpath "${project_subpath}"
    --godot "${godot_bin}"
    --minimum-godot-version "${minimum_version}"
    --timeout "${timeout_seconds}"
    --boot-frames "${boot_frames}"
    --visual-scene "${visual_scene}"
    --visual-frames "${visual_frames}"
    --visual-fps "${visual_fps}"
    --visual-width "${visual_width}"
    --visual-height "${visual_height}"
    --rendering-method "${rendering_method}"
    --visual-arguments-json "${visual_arguments_json}"
)

if [[ -x "${dotnet_bin}" ]]; then
    arguments+=(--dotnet "${dotnet_bin}")
fi
if [[ -n "${export_preset}" ]]; then
    arguments+=(--export-preset "${export_preset}")
fi

exec python3 /opt/godot-lab/scripts/run_profiled_linux_sandbox.py "${arguments[@]}"
