# syntax=docker/dockerfile:1.7
FROM ubuntu:noble-20260610@sha256:4fbb8e6a8395de5a7550b33509421a2bafbc0aab6c06ba2cef9ebffbc7092d90

ARG GODOT_VERSION=4.6.3
ARG GODOT_FLAVOR=standard

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/godot-lab/src \
    GODOT_BIN=/usr/local/bin/godot \
    DOTNET_BIN=/usr/bin/dotnet \
    DOTNET_ROOT=/usr/share/dotnet \
    DOTNET_MULTILEVEL_LOOKUP=0 \
    DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1 \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_NOLOGO=1 \
    DOTNET_CLI_HOME=/home/godotlab/.dotnet \
    NUGET_PACKAGES=/home/godotlab/.nuget/packages \
    NUGET_XMLDOC_MODE=skip \
    LIBGL_ALWAYS_SOFTWARE=1 \
    HOME=/home/godotlab

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        dotnet-sdk-8.0 \
        ffmpeg \
        fonts-dejavu-core \
        git \
        libasound2t64 \
        libdbus-1-3 \
        libfontconfig1 \
        libfreetype6 \
        libgl1 \
        libglu1-mesa \
        libpulse0 \
        libudev1 \
        libvulkan1 \
        libwayland-client0 \
        libwayland-cursor0 \
        libwayland-egl1 \
        libx11-6 \
        libxcursor1 \
        libxi6 \
        libxinerama1 \
        libxrandr2 \
        mesa-utils \
        mesa-vulkan-drivers \
        procps \
        python3 \
        rsync \
        tini \
        unzip \
        util-linux \
        xauth \
        xvfb \
    && rm -rf /var/lib/apt/lists/*

RUN <<'BASH'
set -euo pipefail
[[ "${GODOT_VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] \
    || { echo "Invalid GODOT_VERSION: ${GODOT_VERSION}" >&2; exit 1; }
case "${GODOT_FLAVOR}" in
    standard)
        editor_archive="Godot_v${GODOT_VERSION}-stable_linux.x86_64.zip"
        template_archive="Godot_v${GODOT_VERSION}-stable_export_templates.tpz"
        ;;
    mono)
        editor_archive="Godot_v${GODOT_VERSION}-stable_mono_linux_x86_64.zip"
        template_archive="Godot_v${GODOT_VERSION}-stable_mono_export_templates.tpz"
        ;;
    *)
        echo "Unsupported GODOT_FLAVOR: ${GODOT_FLAVOR}" >&2
        exit 1
        ;;
esac
base_url="https://github.com/godotengine/godot-builds/releases/download/${GODOT_VERSION}-stable"
mkdir -p /opt/godot/editor /opt/godot/export_templates/${GODOT_VERSION}.stable \
    /tmp/godot-download
for asset in SHA512-SUMS.txt "${editor_archive}" "${template_archive}"; do
    curl --proto '=https' --proto-redir '=https' --tlsv1.2 \
        --fail --location --retry 3 --retry-all-errors \
        --connect-timeout 30 --max-time 1800 \
        --output "/tmp/godot-download/${asset}" \
        "${base_url}/${asset}"
done
EDITOR_ARCHIVE="${editor_archive}" TEMPLATE_ARCHIVE="${template_archive}" \
    GODOT_VERSION="${GODOT_VERSION}" python3 <<'PY_SAFE'
from __future__ import annotations

import hashlib
import os
import shutil
import stat
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath

root = Path("/tmp/godot-download")
manifest = (root / "SHA512-SUMS.txt").read_text(encoding="utf-8")
assets = (os.environ["EDITOR_ARCHIVE"], os.environ["TEMPLATE_ARCHIVE"])


def expected_digest(filename: str) -> str:
    matches: list[str] = []
    for line in manifest.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) != 2:
            continue
        digest, name = parts
        name = name.removeprefix("*")
        if name == filename and len(digest) == 128:
            matches.append(digest.casefold())
    if len(matches) != 1:
        raise SystemExit(f"checksum manifest must contain exactly one {filename!r} entry")
    return matches[0]


def sha512(path: Path) -> str:
    digest = hashlib.sha512()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_extract(archive_path: Path, destination: Path) -> None:
    maximum_members = 100_000
    maximum_member = 3 * 1024**3
    maximum_total = 8 * 1024**3
    seen: set[str] = set()
    total = 0
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if len(members) > maximum_members:
            raise SystemExit(f"archive member limit exceeded: {archive_path.name}")
        for member in members:
            pure = PurePosixPath(member.filename.replace("\\", "/"))
            mode = member.external_attr >> 16
            if (
                not member.filename
                or "\x00" in member.filename
                or pure.is_absolute()
                or any(part in {"", ".", ".."} for part in pure.parts)
                or member.flag_bits & 0x1
                or stat.S_ISLNK(mode)
                or (mode and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)))
                or member.file_size < 0
                or member.file_size > maximum_member
            ):
                raise SystemExit(f"unsafe archive member: {member.filename}")
            identity = unicodedata.normalize("NFC", pure.as_posix()).casefold()
            if identity in seen:
                raise SystemExit(f"case or Unicode colliding member: {member.filename}")
            seen.add(identity)
            total += member.file_size
            if total > maximum_total:
                raise SystemExit(f"archive expanded-byte limit exceeded: {archive_path.name}")
        for member in members:
            pure = PurePosixPath(member.filename.replace("\\", "/"))
            target = destination.joinpath(*pure.parts)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            mode = member.external_attr >> 16
            if mode & stat.S_IXUSR:
                target.chmod(target.stat().st_mode | 0o755)


for filename in assets:
    path = root / filename
    if sha512(path) != expected_digest(filename):
        raise SystemExit(f"SHA-512 mismatch for {filename}")

safe_extract(root / assets[0], Path("/tmp/godot-editor"))
safe_extract(root / assets[1], Path("/tmp/godot-templates"))
PY_SAFE
cp -a /tmp/godot-editor/. /opt/godot/editor/
mapfile -t template_roots < <(
    find /tmp/godot-templates -type d -name templates -print | sort
)
if (( ${#template_roots[@]} != 1 )); then
    echo "Expected exactly one Godot export template root; found ${#template_roots[@]}." >&2
    exit 1
fi
template_root="${template_roots[0]}"
cp -a "${template_root}/." "/opt/godot/export_templates/${GODOT_VERSION}.stable/"
mapfile -t editor_paths < <(
    find /opt/godot/editor -type f \
        -name 'Godot_v*-stable*linux*x86_64' -print | sort
)
if (( ${#editor_paths[@]} != 1 )); then
    echo "Expected exactly one Godot Linux editor binary; found ${#editor_paths[@]}." >&2
    exit 1
fi
editor_path="${editor_paths[0]}"
chmod +x "${editor_path}"
"${editor_path}" --version | grep -F "${GODOT_VERSION}"
printf '%s\n' "${editor_path}" > /opt/godot/editor-path
printf '#!/usr/bin/env bash\nexec "%s" "$@"\n' "${editor_path}" \
    > /usr/local/bin/godot
chmod +x /usr/local/bin/godot
rm -rf /tmp/godot-download /tmp/godot-editor /tmp/godot-templates
BASH

RUN useradd --create-home --home-dir /home/godotlab --uid 10001 \
        --shell /bin/bash godotlab \
    && mkdir -p \
        /workspace/source \
        /workspace/work \
        /artifacts \
        /opt/godot-lab \
        /home/godotlab/.dotnet \
        /home/godotlab/.nuget/packages \
        /home/godotlab/.local/share/godot/export_templates \
    && chown -R 10001:10001 /workspace /artifacts /home/godotlab

COPY . /opt/godot-lab
RUN chmod +x /opt/godot-lab/scripts/linux-sandbox-entrypoint.sh \
    && godot --headless --version | grep -F "${GODOT_VERSION}" \
    && godot --headless --help | grep -F -- "--import" \
    && dotnet --version | grep -E '^8\.' \
    && ffmpeg -version >/dev/null \
    && ffprobe -version >/dev/null

USER 10001:10001
WORKDIR /workspace

ENTRYPOINT ["/usr/bin/tini", "--", "/opt/godot-lab/scripts/linux-sandbox-entrypoint.sh"]
