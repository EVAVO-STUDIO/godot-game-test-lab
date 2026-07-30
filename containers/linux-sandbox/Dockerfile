FROM ubuntu:noble-20260610

ARG GODOT_VERSION=4.6.2
ARG GODOT_FLAVOR=standard

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/godot-lab/src \
    GODOT_BIN=/usr/local/bin/godot \
    DOTNET_BIN=/usr/bin/dotnet \
    HOME=/home/godotlab

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        dotnet-sdk-8.0 \
        ffmpeg \
        fonts-dejavu-core \
        libasound2t64 \
        libdbus-1-3 \
        libfontconfig1 \
        libfreetype6 \
        libgl1 \
        libglu1-mesa \
        libpulse0 \
        libudev1 \
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

RUN set -euo pipefail; \
    case "${GODOT_FLAVOR}" in \
        standard) \
            editor_archive="Godot_v${GODOT_VERSION}-stable_linux.x86_64.zip"; \
            template_archive="Godot_v${GODOT_VERSION}-stable_export_templates.tpz"; \
            ;; \
        mono) \
            editor_archive="Godot_v${GODOT_VERSION}-stable_mono_linux_x86_64.zip"; \
            template_archive="Godot_v${GODOT_VERSION}-stable_mono_export_templates.tpz"; \
            ;; \
        *) \
            echo "Unsupported GODOT_FLAVOR: ${GODOT_FLAVOR}" >&2; \
            exit 1; \
            ;; \
    esac; \
    base_url="https://github.com/godotengine/godot-builds/releases/download/${GODOT_VERSION}-stable"; \
    mkdir -p /opt/godot/editor /opt/godot/export_templates/${GODOT_VERSION}.stable /tmp/godot-download /tmp/godot-templates; \
    curl --fail --location --retry 3 --output /tmp/godot-download/SHA512-SUMS.txt "${base_url}/SHA512-SUMS.txt"; \
    curl --fail --location --retry 3 --output "/tmp/godot-download/${editor_archive}" "${base_url}/${editor_archive}"; \
    curl --fail --location --retry 3 --output "/tmp/godot-download/${template_archive}" "${base_url}/${template_archive}"; \
    grep -F "  ${editor_archive}" /tmp/godot-download/SHA512-SUMS.txt > /tmp/godot-download/selected-SHA512-SUMS.txt; \
    grep -F "  ${template_archive}" /tmp/godot-download/SHA512-SUMS.txt >> /tmp/godot-download/selected-SHA512-SUMS.txt; \
    (cd /tmp/godot-download && sha512sum --check selected-SHA512-SUMS.txt); \
    unzip -q "/tmp/godot-download/${editor_archive}" -d /opt/godot/editor; \
    unzip -q "/tmp/godot-download/${template_archive}" -d /tmp/godot-templates; \
    template_root="$(find /tmp/godot-templates -type d -name templates -print -quit)"; \
    if [[ -z "${template_root}" ]]; then \
        echo "Godot export template root was not found." >&2; \
        exit 1; \
    fi; \
    cp -a "${template_root}/." "/opt/godot/export_templates/${GODOT_VERSION}.stable/"; \
    editor_path="$(find /opt/godot/editor -type f -name 'Godot_v*-stable*linux*x86_64' -print -quit)"; \
    if [[ -z "${editor_path}" ]]; then \
        echo "Godot Linux editor binary was not found." >&2; \
        exit 1; \
    fi; \
    chmod +x "${editor_path}"; \
    printf '%s\n' "${editor_path}" > /opt/godot/editor-path; \
    printf '#!/usr/bin/env bash\nexec "%s" "$@"\n' "${editor_path}" > /usr/local/bin/godot; \
    chmod +x /usr/local/bin/godot; \
    rm -rf /tmp/godot-download /tmp/godot-templates

RUN useradd --create-home --home-dir /home/godotlab --uid 10001 --shell /bin/bash godotlab \
    && mkdir -p /workspace/source /workspace/work /artifacts /opt/godot-lab \
    && chown -R 10001:10001 /workspace /artifacts /home/godotlab

COPY . /opt/godot-lab
RUN chmod +x /opt/godot-lab/scripts/linux-sandbox-entrypoint.sh

USER 10001:10001
WORKDIR /workspace

ENTRYPOINT ["/usr/bin/tini", "--", "/opt/godot-lab/scripts/linux-sandbox-entrypoint.sh"]
