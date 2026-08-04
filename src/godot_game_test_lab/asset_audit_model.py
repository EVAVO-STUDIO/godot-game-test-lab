from __future__ import annotations

import re
from dataclasses import dataclass

AUDIT_SCHEMA_VERSION = "1.0"
AUDIT_ANALYSIS_VERSION = "1.0"
MAX_AUDIT_BYTES = 64 * 1024 * 1024
MAX_FILES = 100_000
HEX_64 = re.compile(r"^[0-9a-f]{64}$")

CATEGORIES = frozenset(
    {
        "image",
        "animation",
        "font",
        "engine-resource",
        "source-art",
        "metadata",
        "other",
    }
)
ROLES = frozenset(
    {
        "dialogue-portrait",
        "standing-character",
        "crew-portrait",
        "ui-icon",
        "weather-overlay",
        "port-map",
        "ship-profile",
        "document-plate",
        "location-background",
        "animation-frame",
        "editable-source",
        "metadata",
        "unknown",
    }
)
POLICIES = frozenset(
    {
        "preserve-authored-opaque",
        "preserve-authored-black-stage",
        "require-meaningful-alpha",
        "review-required",
    }
)
ALPHA_USAGES = frozenset(
    {"none", "opaque-channel", "meaningful", "fully-transparent", "unknown"}
)
COMPRESSION_POLICIES = frozenset({"lossless", "visually-lossless", "source-only"})
CLEANUP_ACTIONS = frozenset(
    {"review-exact-duplicate", "review-unreferenced-runtime"}
)
LOOP_MODES = frozenset({"linear", "ping-pong", "none"})
ENGINES = frozenset({"godot", "unity", "web", "unknown"})

EXTENSION_CATEGORY = {
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
    ".avif": "image",
    ".gif": "image",
    ".bmp": "image",
    ".tga": "image",
    ".tif": "image",
    ".tiff": "image",
    ".svg": "image",
    ".exr": "image",
    ".hdr": "image",
    ".apng": "animation",
    ".mp4": "animation",
    ".webm": "animation",
    ".mov": "animation",
    ".mkv": "animation",
    ".ttf": "font",
    ".otf": "font",
    ".woff": "font",
    ".woff2": "font",
    ".tres": "engine-resource",
    ".res": "engine-resource",
    ".tscn": "engine-resource",
    ".scn": "engine-resource",
    ".import": "engine-resource",
    ".godot": "engine-resource",
    ".psd": "source-art",
    ".ase": "source-art",
    ".aseprite": "source-art",
    ".kra": "source-art",
    ".xcf": "source-art",
    ".ai": "source-art",
    ".afdesign": "source-art",
    ".blend": "source-art",
    ".json": "metadata",
    ".yaml": "metadata",
    ".yml": "metadata",
    ".toml": "metadata",
    ".xml": "metadata",
    ".atlas": "metadata",
}
ART_EXTENSIONS = frozenset(EXTENSION_CATEGORY)
IGNORED_DIRECTORIES = frozenset(
    {
        ".git",
        ".godot",
        ".next",
        "node_modules",
        "dist",
        "build",
        "coverage",
        ".cache",
        ".turbo",
    }
)
ROLE_POLICY = {
    "dialogue-portrait": "preserve-authored-black-stage",
    "standing-character": "require-meaningful-alpha",
    "crew-portrait": "require-meaningful-alpha",
    "ui-icon": "require-meaningful-alpha",
    "weather-overlay": "require-meaningful-alpha",
    "port-map": "preserve-authored-opaque",
    "ship-profile": "require-meaningful-alpha",
    "document-plate": "preserve-authored-opaque",
    "location-background": "preserve-authored-opaque",
    "animation-frame": "require-meaningful-alpha",
    "editable-source": "review-required",
    "metadata": "review-required",
    "unknown": "review-required",
}


@dataclass(frozen=True)
class AuditImage:
    format: str
    width: int | float | None
    height: int | float | None
    bit_depth: int | None
    colour_model: str | None
    has_alpha_channel: bool
    alpha_usage: str
    probe_complete: bool
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class AuditRow:
    path: str
    extension: str
    size_bytes: int
    category: str
    sha256: str
    role: str
    transparency_policy: str
    image: AuditImage | None
    referenced_by: tuple[str, ...]
    reference_count: int
    animation_family_id: str | None
    animation_frame_index: int | None
    findings: tuple[str, ...]


@dataclass(frozen=True)
class DuplicateGroup:
    sha256: str
    canonical_path: str
    paths: tuple[str, ...]
    total_bytes: int


@dataclass(frozen=True)
class AnimationFrame:
    path: str
    frame_index: int


@dataclass(frozen=True)
class AnimationFamily:
    id: str
    role: str
    frames: tuple[AnimationFrame, ...]
    missing_frame_indices: tuple[int, ...]
    consistent_dimensions: bool | str
    recommended_frames_per_second: float
    loop_mode: str
    timing_notes: tuple[str, ...]


@dataclass(frozen=True)
class MissingReference:
    requested_path: str
    referenced_by: tuple[str, ...]


@dataclass(frozen=True)
class CleanupCandidate:
    path: str
    action: str
    reason: str
    requires_human_approval: bool


@dataclass(frozen=True)
class AuditSummary:
    audited_files: int
    exact_duplicate_groups: int
    animation_families: int
    missing_references: int
    blocking_findings: int
    review_findings: int
    role_counts: dict[str, int]
    transparency_policy_counts: dict[str, int]


@dataclass(frozen=True)
class AuditDocument:
    schema_version: str
    analysis_version: str
    root: str
    project_name: str
    engine: str
    files_scanned: int
    art_files: tuple[AuditRow, ...]
    extension_counts: dict[str, int]
    category_counts: dict[str, int]
    signals: tuple[str, ...]
    gaps: tuple[str, ...]
    truncated: bool
    duplicate_groups: tuple[DuplicateGroup, ...]
    animation_families: tuple[AnimationFamily, ...]
    missing_asset_references: tuple[MissingReference, ...]
    cleanup_candidates: tuple[CleanupCandidate, ...]
    audit_summary: AuditSummary
    audit_rules: tuple[str, ...]
    engine_version_hint: str | None
    viewport: tuple[int, int] | None
