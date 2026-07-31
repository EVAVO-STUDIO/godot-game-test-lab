from __future__ import annotations

import json
import os
import re
import subprocess
import tomllib
import unicodedata
import xml.etree.ElementTree as element_tree
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from .core import find_project_root

_TEXT_NAMES = {".gdignore", "project.godot", "export_presets.cfg"}
_ALLOWED_EMPTY_NAMES = {".gdignore", ".gitkeep", ".keep"}
_TEXT_SUFFIXES = {
    ".cfg",
    ".compute",
    ".cs",
    ".csproj",
    ".csv",
    ".escn",
    ".gd",
    ".gdextension",
    ".gdshader",
    ".gdshaderinc",
    ".gltf",
    ".godot",
    ".ini",
    ".json",
    ".md",
    ".po",
    ".pot",
    ".shader",
    ".sln",
    ".svg",
    ".toml",
    ".tres",
    ".tscn",
    ".tsv",
    ".txt",
    ".uid",
    ".xml",
    ".yaml",
    ".yml",
}
_RESOURCE_SUFFIXES = {".escn", ".res", ".scn", ".tres", ".tscn"}
_TEXT_RESOURCE_SUFFIXES = {".escn", ".tres", ".tscn"}
_IGNORED_DIRECTORIES = {
    ".git",
    ".godot",
    ".idea",
    ".mono",
    ".pytest_cache",
    ".qa",
    ".ruff_cache",
    ".vs",
    ".vscode",
    "artifacts",
    "bin",
    "obj",
    "reports",
    "test-results",
}
_WINDOWS_RESERVED_NAMES = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
_SECTION_RE = re.compile(
    r"^\s*\[(?P<kind>[A-Za-z_][A-Za-z0-9_]*)(?P<attributes>[^\]]*)\]\s*(?:;.*)?$"
)
_ATTRIBUTE_RE = re.compile(
    r"(?P<key>[A-Za-z_][A-Za-z0-9_/]*)\s*=\s*"
    r'(?P<value>"(?:\\.|[^"\\])*"|[^\s\]]+)'
)
_EXT_REFERENCE_RE = re.compile(r'ExtResource\(\s*(?:"([^"]+)"|([^\s\)]+))\s*\)')
_SUB_REFERENCE_RE = re.compile(r'SubResource\(\s*(?:"([^"]+)"|([^\s\)]+))\s*\)')
_PROJECT_SETTING_RE = re.compile(
    r'^(?P<key>[A-Za-z0-9_./-]+)\s*=\s*"(?P<value>(?:\\.|[^"\\])*)"\s*$',
    re.MULTILINE,
)
_CONFLICT_START_RE = re.compile(r"^<{7}(?:\s|$)", re.MULTILINE)
_CONFLICT_MIDDLE_RE = re.compile(r"^={7}(?:\s|$)", re.MULTILINE)
_CONFLICT_END_RE = re.compile(r"^>{7}(?:\s|$)", re.MULTILINE)
_GIT_LFS_PREFIX = b"version https://git-lfs.github.com/spec/v1\n"
_UID_RE = re.compile(r"^uid://[a-z0-9]+$")
_TOOL_SCRIPT_RE = re.compile(r"^\s*@tool\s*(?:#.*)?$", re.MULTILINE)
_QUOTED_STRING_RE = re.compile(r'"(?:\\.|[^"\\])*"')
_EXECUTION_BLOCKING_CODES = frozenset(
    {
        "filesystem.directory_unreadable",
        "filesystem.entry_unreadable",
        "filesystem.file_read_failed",
        "filesystem.file_stat_failed",
        "filesystem.special_file_skipped",
        "filesystem.symlink_escape",
        "project.file_unreadable",
        "project.main_scene_escape",
        "resource.external_path_escape",
    }
)


@dataclass(frozen=True, slots=True)
class AuditLimits:
    max_files: int = 250_000
    max_total_bytes: int = 32 * 1024 * 1024 * 1024
    max_text_file_bytes: int = 32 * 1024 * 1024
    max_findings: int = 5_000

    def __post_init__(self) -> None:
        for field_name, value in asdict(self).items():
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")


@dataclass(slots=True)
class IntegrityFinding:
    severity: str
    code: str
    category: str
    message: str
    suggested_action: str
    path: str | None = None
    line: int | None = None
    evidence: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class IntegrityReport:
    schema_version: str
    generated_at: str
    status: str
    project_root: str
    project_file: str
    scanned_files: int
    scanned_bytes: int
    scene_files: int
    resource_files: int
    script_files: int
    errors: int
    warnings: int
    findings_truncated: bool
    findings: list[IntegrityFinding]
    limits: AuditLimits

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


def _suggested_action(code: str) -> str:
    exact = {
        "git.conflict_markers": (
            "Resolve the merge conflict from version control, then rerun the audit "
            "and Godot import."
        ),
        "git.unmerged_index": (
            "Resolve or abort the incomplete Git merge before testing this checkout."
        ),
        "git_lfs.pointer_not_materialized": (
            "Materialize Git LFS content for the exact target commit, then verify its checksum."
        ),
        "project.main_scene_missing": (
            "Set application/run/main_scene to a valid scene in project.godot."
        ),
        "project.main_scene_missing_file": (
            "Restore the declared main scene or update project.godot to the intended scene."
        ),
        "project.main_scene_uid_unresolved": (
            "Restore the scene carrying this UID or resave the project with the matching "
            "Godot editor."
        ),
        "project.editor_plugin_missing": (
            "Restore the enabled editor plugin or remove it from the enabled plugin list."
        ),
        "resource.external_path_missing": (
            "Restore the referenced asset or update the ExtResource path in the owning resource."
        ),
        "resource.ext_resource_reference_unresolved": (
            "Restore the matching ext_resource declaration or repair the stale reference."
        ),
        "resource.sub_resource_reference_unresolved": (
            "Restore the matching sub_resource declaration or repair the stale reference."
        ),
        "asset.signature_invalid": (
            "Restore the asset from source control or regenerate it with the correct file format."
        ),
        "text.invalid_utf8": (
            "Restore the source or convert it to valid UTF-8 without changing semantic content."
        ),
    }
    if code in exact:
        return exact[code]
    prefix = code.split(".", maxsplit=1)[0]
    by_prefix = {
        "asset": "Restore or regenerate the asset, then rerun Godot import.",
        "execution": (
            "Review this import-time execution surface; use recovery-mode evidence to isolate it."
        ),
        "export": "Repair export_presets.cfg or the declared export configuration.",
        "filesystem": (
            "Restore a readable regular-file project tree without symlink or special-file "
            "ambiguity."
        ),
        "git": "Repair the checkout state and bind the next run to the intended commit.",
        "json": "Repair the structured file without introducing non-standard JSON values.",
        "limits": (
            "Review project scope and generated content before deliberately raising bounded "
            "audit limits."
        ),
        "path": "Rename the path to a portable, collision-free form and update references.",
        "project": "Repair project.godot or the referenced project-level resource.",
        "resource": (
            "Recover or repair the resource from version control, then validate it with "
            "Godot --import."
        ),
        "scene": (
            "Recover or repair the scene structure, then open and resave it in the matching "
            "Godot editor."
        ),
        "text": "Restore or normalize the text source, then rerun static and engine validation.",
        "toml": "Repair the TOML syntax and rerun the audit.",
        "xml": "Repair the XML structure and rerun the audit.",
    }
    return by_prefix.get(
        prefix,
        "Review the retained evidence and repair the source of this finding.",
    )


class _Findings:
    def __init__(self, maximum: int) -> None:
        self.maximum = maximum
        self.items: list[IntegrityFinding] = []
        self.truncated = False

    def add(
        self,
        severity: str,
        code: str,
        message: str,
        *,
        path: str | None = None,
        line: int | None = None,
        evidence: dict[str, object] | None = None,
    ) -> None:
        if len(self.items) >= self.maximum:
            self.truncated = True
            return
        self.items.append(
            IntegrityFinding(
                severity=severity,
                code=code,
                category=code.split(".", maxsplit=1)[0],
                message=message,
                suggested_action=_suggested_action(code),
                path=path,
                line=line,
                evidence=evidence or {},
            )
        )

    def error(
        self,
        code: str,
        message: str,
        *,
        path: str | None = None,
        line: int | None = None,
        evidence: dict[str, object] | None = None,
    ) -> None:
        self.add("error", code, message, path=path, line=line, evidence=evidence)

    def warning(
        self,
        code: str,
        message: str,
        *,
        path: str | None = None,
        line: int | None = None,
        evidence: dict[str, object] | None = None,
    ) -> None:
        self.add("warning", code, message, path=path, line=line, evidence=evidence)


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _unquote(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return value[1:-1]
        return decoded if isinstance(decoded, str) else None
    return value


def _decode_escaped_string(value: str) -> str:
    try:
        decoded = json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return value
    return decoded if isinstance(decoded, str) else value


def _quoted_strings(source: str) -> list[str]:
    values: list[str] = []
    for match in _QUOTED_STRING_RE.finditer(source):
        decoded = _unquote(match.group(0))
        if decoded is not None:
            values.append(decoded)
    return values


def execution_blocking_findings(report: IntegrityReport) -> list[IntegrityFinding]:
    return [
        finding
        for finding in report.findings
        if finding.code in _EXECUTION_BLOCKING_CODES or finding.code.startswith("limits.")
    ]


def _attributes(source: str) -> dict[str, str]:
    return {
        match.group("key"): match.group("value")
        for match in _ATTRIBUTE_RE.finditer(source)
    }


def _reference_ids(pattern: re.Pattern[str], source: str) -> list[str]:
    output: list[str] = []
    for match in pattern.finditer(source):
        value = match.group(1) or match.group(2)
        if value:
            output.append(value)
    return output


def _is_text_path(path: Path) -> bool:
    return path.name in _TEXT_NAMES or path.suffix.lower() in _TEXT_SUFFIXES


def _is_windows_invalid_component(component: str) -> bool:
    return (
        component.endswith((" ", "."))
        or any(character in component for character in '<>:"|?*')
        or any(ord(character) < 32 for character in component)
    )


def _validate_portable_path(relative: str, findings: _Findings) -> None:
    pure = PurePosixPath(relative)
    for component in pure.parts:
        base = component.split(".", maxsplit=1)[0].casefold()
        if base in _WINDOWS_RESERVED_NAMES:
            findings.error(
                "path.windows_reserved_name",
                "Path component is reserved on Windows.",
                path=relative,
                evidence={"component": component},
            )
        if _is_windows_invalid_component(component):
            findings.error(
                "path.windows_invalid_component",
                "Path component is not portable to Windows.",
                path=relative,
                evidence={"component": component},
            )
    if len(relative) > 240:
        findings.warning(
            "path.windows_length_risk",
            "Relative path exceeds 240 characters and may fail in Windows tooling.",
            path=relative,
            evidence={"characters": len(relative)},
        )


def _walk_project(
    root: Path,
    limits: AuditLimits,
    findings: _Findings,
) -> tuple[list[Path], int]:
    files: list[Path] = []
    total_bytes = 0
    stack = [root]
    identities: dict[str, str] = {}

    while stack:
        current = stack.pop()
        try:
            entries = sorted(os.scandir(current), key=lambda entry: entry.name.casefold())
        except OSError as error:
            relative = "." if current == root else _relative(root, current)
            findings.error(
                "filesystem.directory_unreadable",
                "Directory could not be inspected.",
                path=relative,
                evidence={"errorType": type(error).__name__},
            )
            continue

        for entry in entries:
            path = Path(entry.path)
            relative = _relative(root, path)
            normalized = unicodedata.normalize("NFC", relative).casefold()
            previous = identities.setdefault(normalized, relative)
            if previous != relative:
                findings.error(
                    "path.portability_collision",
                    "Two paths collide after Unicode normalization and case folding.",
                    path=relative,
                    evidence={"otherPath": previous},
                )
            _validate_portable_path(relative, findings)

            try:
                if entry.is_symlink():
                    try:
                        raw_target = path.readlink()
                        resolved_target = path.resolve(strict=False)
                    except OSError as error:
                        findings.error(
                            "filesystem.entry_unreadable",
                            "Symbolic-link metadata could not be inspected.",
                            path=relative,
                            evidence={"errorType": type(error).__name__},
                        )
                        continue
                    try:
                        target_relative = resolved_target.relative_to(root).as_posix()
                    except ValueError:
                        findings.error(
                            "filesystem.symlink_escape",
                            "Symbolic link resolves outside the project root.",
                            path=relative,
                            evidence={"target": str(raw_target)},
                        )
                        continue
                    if not resolved_target.exists():
                        findings.error(
                            "filesystem.symlink_broken",
                            "Symbolic link target does not exist.",
                            path=relative,
                            evidence={"target": target_relative},
                        )
                        continue
                    findings.warning(
                        "filesystem.symlink_present",
                        "Internal symbolic link was retained as a portability warning "
                        "and not followed.",
                        path=relative,
                        evidence={"target": target_relative},
                    )
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if entry.name not in _IGNORED_DIRECTORIES:
                        stack.append(path)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    findings.warning(
                        "filesystem.special_file_skipped",
                        "Non-regular filesystem entry was skipped.",
                        path=relative,
                    )
                    continue
                size = entry.stat(follow_symlinks=False).st_size
            except OSError as error:
                findings.error(
                    "filesystem.entry_unreadable",
                    "Filesystem entry could not be inspected.",
                    path=relative,
                    evidence={"errorType": type(error).__name__},
                )
                continue

            files.append(path)
            total_bytes += size
            if len(files) > limits.max_files:
                findings.error(
                    "limits.file_count_exceeded",
                    "Project contains more files than the bounded audit permits.",
                    evidence={"maximum": limits.max_files},
                )
                return files, total_bytes
            if total_bytes > limits.max_total_bytes:
                findings.error(
                    "limits.total_bytes_exceeded",
                    "Project exceeds the bounded audit byte limit.",
                    evidence={"maximum": limits.max_total_bytes},
                )
                return files, total_bytes

    return sorted(files), total_bytes


def _read_text(
    root: Path,
    path: Path,
    limits: AuditLimits,
    findings: _Findings,
) -> str | None:
    relative = _relative(root, path)
    try:
        size = path.stat().st_size
    except OSError as error:
        findings.error(
            "filesystem.file_stat_failed",
            "File metadata could not be read.",
            path=relative,
            evidence={"errorType": type(error).__name__},
        )
        return None

    if size == 0:
        if path.name not in _ALLOWED_EMPTY_NAMES:
            findings.error("text.empty_file", "Text source file is empty.", path=relative)
        return ""
    if size > limits.max_text_file_bytes:
        findings.error(
            "limits.text_file_bytes_exceeded",
            "Text source file exceeds the bounded per-file byte limit.",
            path=relative,
            evidence={"bytes": size, "maximum": limits.max_text_file_bytes},
        )
        return None

    try:
        payload = path.read_bytes()
    except OSError as error:
        findings.error(
            "filesystem.file_read_failed",
            "File content could not be read.",
            path=relative,
            evidence={"errorType": type(error).__name__},
        )
        return None
    if b"\x00" in payload:
        findings.error("text.nul_byte", "Text source contains a NUL byte.", path=relative)
        return None
    normalized_prefix = payload[: len(_GIT_LFS_PREFIX) + 8].replace(b"\r\n", b"\n")
    if normalized_prefix.startswith(_GIT_LFS_PREFIX):
        findings.error(
            "git_lfs.pointer_not_materialized",
            "Git LFS pointer is present instead of the required file content.",
            path=relative,
        )
        return None
    if payload.startswith(b"\xef\xbb\xbf"):
        findings.warning(
            "text.utf8_bom",
            "UTF-8 byte-order mark is present; canonical Godot source should not require it.",
            path=relative,
        )
        payload = payload[3:]
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        findings.error(
            "text.invalid_utf8",
            "Text source is not valid UTF-8.",
            path=relative,
            evidence={"byteOffset": error.start},
        )
        return None

    if (
        _CONFLICT_START_RE.search(text)
        and _CONFLICT_MIDDLE_RE.search(text)
        and _CONFLICT_END_RE.search(text)
    ):
        line = text[: _CONFLICT_START_RE.search(text).start()].count("\n") + 1
        findings.error(
            "git.conflict_markers",
            "Unresolved merge conflict markers remain in source.",
            path=relative,
            line=line,
        )
    return text


def _validate_binary_asset(root: Path, path: Path, findings: _Findings) -> None:
    relative = _relative(root, path)
    try:
        size = path.stat().st_size
        with path.open("rb") as stream:
            head = stream.read(64)
            if size > 64:
                stream.seek(max(0, size - 64))
            tail = stream.read(64)
    except OSError as error:
        findings.error(
            "filesystem.file_read_failed",
            "Binary asset could not be read.",
            path=relative,
            evidence={"errorType": type(error).__name__},
        )
        return

    if head.startswith(_GIT_LFS_PREFIX) or head.replace(b"\r\n", b"\n").startswith(
        _GIT_LFS_PREFIX
    ):
        findings.error(
            "git_lfs.pointer_not_materialized",
            "Git LFS pointer is present instead of the required asset content.",
            path=relative,
        )
        return
    if size == 0:
        if path.name not in _ALLOWED_EMPTY_NAMES:
            findings.error("asset.empty_file", "Binary asset is empty.", path=relative)
        return

    suffix = path.suffix.casefold()
    valid = True
    if suffix == ".png":
        valid = head.startswith(b"\x89PNG\r\n\x1a\n") and tail.endswith(
            b"IEND\xaeB`\x82"
        )
    elif suffix in {".jpg", ".jpeg"}:
        valid = head.startswith(b"\xff\xd8\xff") and tail.endswith(b"\xff\xd9")
    elif suffix == ".gif":
        valid = head.startswith((b"GIF87a", b"GIF89a"))
    elif suffix == ".bmp":
        valid = head.startswith(b"BM")
    elif suffix in {".ico", ".cur"}:
        expected = b"\x00\x00\x01\x00" if suffix == ".ico" else b"\x00\x00\x02\x00"
        valid = head.startswith(expected)
    elif suffix == ".wav":
        valid = head.startswith(b"RIFF") and head[8:12] == b"WAVE"
    elif suffix == ".webp":
        valid = head.startswith(b"RIFF") and head[8:12] == b"WEBP"
    elif suffix in {".ogg", ".opus"}:
        valid = head.startswith(b"OggS")
    elif suffix == ".flac":
        valid = head.startswith(b"fLaC")
    elif suffix == ".glb":
        valid = head.startswith(b"glTF")
        if valid and len(head) >= 12:
            declared_length = int.from_bytes(head[8:12], "little")
            if declared_length != size:
                findings.error(
                    "asset.declared_length_mismatch",
                    "Binary asset header length does not match the file size.",
                    path=relative,
                    evidence={"declaredBytes": declared_length, "actualBytes": size},
                )
    elif suffix in {".zip", ".tpz"}:
        valid = head.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))
    elif suffix == ".pck":
        valid = head.startswith(b"GDPC")
    elif suffix in {".ttf", ".otf"}:
        valid = head.startswith((b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1"))
    elif suffix == ".woff":
        valid = head.startswith(b"wOFF")
    elif suffix == ".woff2":
        valid = head.startswith(b"wOF2")

    if not valid:
        findings.error(
            "asset.signature_invalid",
            "Binary asset does not have the expected file signature or terminator.",
            path=relative,
            evidence={"suffix": suffix, "bytes": size},
        )


def _resolve_resource_path(
    root: Path,
    owner: Path,
    source: str,
) -> tuple[Path | None, bool]:
    if source.startswith("uid://"):
        return None, False
    if source.startswith("res://"):
        candidate = root / source.removeprefix("res://")
    else:
        candidate = owner.parent / source
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None, True
    return resolved, False


def _first_meaningful_line(lines: list[str]) -> tuple[int, str] | None:
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped and not stripped.startswith(";"):
            return index, line
    return None


def _resource_header(
    root: Path,
    path: Path,
    lines: list[str],
    expected: str,
    findings: _Findings,
) -> tuple[dict[str, str], int] | None:
    relative = _relative(root, path)
    first = _first_meaningful_line(lines)
    if first is None:
        findings.error("resource.empty", "Godot text resource has no content.", path=relative)
        return None
    line_number, source = first
    match = _SECTION_RE.match(source)
    if match is None or match.group("kind") != expected:
        findings.error(
            "resource.invalid_header",
            f"Expected [{expected} ...] as the first meaningful line.",
            path=relative,
            line=line_number,
        )
        return None
    attributes = _attributes(match.group("attributes"))
    format_value = _unquote(attributes.get("format"))
    if format_value != "3":
        findings.error(
            "resource.unsupported_format",
            "Godot 4 text scenes and resources must declare format=3.",
            path=relative,
            line=line_number,
            evidence={"format": format_value},
        )
    if "load_steps" in attributes:
        findings.warning(
            "resource.deprecated_load_steps",
            "load_steps is deprecated in Godot 4.6 and can be removed when the file is resaved.",
            path=relative,
            line=line_number,
        )
    return attributes, line_number


def _parse_text_resource(
    root: Path,
    path: Path,
    text: str,
    findings: _Findings,
    top_level_uids: dict[str, str],
) -> None:
    relative = _relative(root, path)
    suffix = path.suffix.lower()
    expected = "gd_scene" if suffix in {".escn", ".tscn"} else "gd_resource"
    lines = text.splitlines()
    header = _resource_header(root, path, lines, expected, findings)
    if header is None:
        return
    header_attributes, _ = header
    top_uid = _unquote(header_attributes.get("uid"))
    if top_uid:
        if not _UID_RE.fullmatch(top_uid):
            findings.error(
                "resource.uid_invalid",
                "Top-level Godot resource UID is malformed.",
                path=relative,
                evidence={"uid": top_uid},
            )
        else:
            previous = top_level_uids.setdefault(top_uid, relative)
            if previous != relative:
                findings.error(
                    "resource.duplicate_uid",
                    "Top-level Godot resource UID is used by more than one source file.",
                    path=relative,
                    evidence={"uid": top_uid, "otherPath": previous},
                )

    ext_ids: dict[str, int] = {}
    sub_ids: dict[str, int] = {}
    ext_references: list[tuple[str, int]] = []
    sub_references: list[tuple[str, int]] = []
    nodes: list[tuple[dict[str, str], int]] = []
    connections: list[tuple[dict[str, str], int]] = []
    resource_sections = 0
    last_order = -1
    section_order = {
        "ext_resource": 0,
        "sub_resource": 1,
        "resource": 2,
        "node": 2,
        "connection": 3,
        "editable": 3,
    }

    for line_number, source in enumerate(lines, start=1):
        stripped = source.strip()
        if not stripped or stripped.startswith(";"):
            continue
        ext_references.extend(
            (reference, line_number) for reference in _reference_ids(_EXT_REFERENCE_RE, source)
        )
        sub_references.extend(
            (reference, line_number) for reference in _reference_ids(_SUB_REFERENCE_RE, source)
        )
        if not stripped.startswith("["):
            continue
        match = _SECTION_RE.match(source)
        if match is None:
            if stripped.startswith(
                ("[gd_", "[ext_resource", "[sub_resource", "[node", "[connection")
            ):
                findings.error(
                    "resource.malformed_section",
                    "Godot resource section header is malformed.",
                    path=relative,
                    line=line_number,
                )
            continue
        kind = match.group("kind")
        if kind in {"gd_scene", "gd_resource"}:
            continue
        order = section_order.get(kind)
        if order is not None:
            if order < last_order:
                findings.warning(
                    "resource.section_order",
                    "Godot text resource sections are not in canonical order.",
                    path=relative,
                    line=line_number,
                    evidence={"section": kind},
                )
            last_order = max(last_order, order)
        attributes = _attributes(match.group("attributes"))
        if kind == "ext_resource":
            identifier = _unquote(attributes.get("id"))
            resource_path = _unquote(attributes.get("path"))
            resource_type = _unquote(attributes.get("type"))
            resource_uid = _unquote(attributes.get("uid"))
            if not resource_type:
                findings.warning(
                    "resource.ext_resource_type_missing",
                    "External resource declaration has no type.",
                    path=relative,
                    line=line_number,
                )
            if resource_uid and not _UID_RE.fullmatch(resource_uid):
                findings.error(
                    "resource.ext_resource_uid_invalid",
                    "External resource UID is malformed.",
                    path=relative,
                    line=line_number,
                    evidence={"uid": resource_uid},
                )
            if not identifier:
                findings.error(
                    "resource.ext_resource_id_missing",
                    "External resource declaration has no id.",
                    path=relative,
                    line=line_number,
                )
            elif identifier in ext_ids:
                findings.error(
                    "resource.ext_resource_id_duplicate",
                    "External resource id is declared more than once.",
                    path=relative,
                    line=line_number,
                    evidence={"id": identifier, "firstLine": ext_ids[identifier]},
                )
            else:
                ext_ids[identifier] = line_number
            if not resource_path:
                findings.error(
                    "resource.ext_resource_path_missing",
                    "External resource declaration has no path.",
                    path=relative,
                    line=line_number,
                )
            else:
                resolved, escaped = _resolve_resource_path(root, path, resource_path)
                if escaped:
                    findings.error(
                        "resource.external_path_escape",
                        "External resource path escapes the project root.",
                        path=relative,
                        line=line_number,
                        evidence={"resourcePath": resource_path},
                    )
                elif resolved is not None and not resolved.is_file():
                    findings.error(
                        "resource.external_path_missing",
                        "External resource path does not exist.",
                        path=relative,
                        line=line_number,
                        evidence={"resourcePath": resource_path},
                    )
        elif kind == "sub_resource":
            identifier = _unquote(attributes.get("id"))
            resource_type = _unquote(attributes.get("type"))
            if not resource_type:
                findings.error(
                    "resource.sub_resource_type_missing",
                    "Internal resource declaration has no type.",
                    path=relative,
                    line=line_number,
                )
            if not identifier:
                findings.error(
                    "resource.sub_resource_id_missing",
                    "Internal resource declaration has no id.",
                    path=relative,
                    line=line_number,
                )
            elif identifier in sub_ids:
                findings.error(
                    "resource.sub_resource_id_duplicate",
                    "Internal resource id is declared more than once.",
                    path=relative,
                    line=line_number,
                    evidence={"id": identifier, "firstLine": sub_ids[identifier]},
                )
            else:
                sub_ids[identifier] = line_number
        elif kind == "node":
            nodes.append((attributes, line_number))
        elif kind == "connection":
            connections.append((attributes, line_number))
        elif kind == "resource":
            resource_sections += 1

    for identifier, line_number in ext_references:
        if identifier not in ext_ids:
            findings.error(
                "resource.ext_resource_reference_unresolved",
                "ExtResource reference has no matching declaration.",
                path=relative,
                line=line_number,
                evidence={"id": identifier},
            )
    for identifier, line_number in sub_references:
        if identifier not in sub_ids:
            findings.error(
                "resource.sub_resource_reference_unresolved",
                "SubResource reference has no matching declaration.",
                path=relative,
                line=line_number,
                evidence={"id": identifier},
            )

    if suffix in {".escn", ".tscn"}:
        _validate_scene_nodes(relative, nodes, findings)
        _validate_scene_connections(relative, connections, findings)
    elif resource_sections != 1:
        findings.error(
            "resource.root_section_count",
            "TRES file must contain exactly one [resource] section.",
            path=relative,
            evidence={"count": resource_sections},
        )


def _validate_scene_nodes(
    relative: str,
    nodes: list[tuple[dict[str, str], int]],
    findings: _Findings,
) -> None:
    if not nodes:
        findings.error("scene.no_nodes", "Scene contains no node sections.", path=relative)
        return
    roots = [
        (attributes, line)
        for attributes, line in nodes
        if _unquote(attributes.get("parent")) in {None, ""}
    ]
    if len(roots) != 1:
        findings.error(
            "scene.root_count",
            "Scene must contain exactly one root node without a parent attribute.",
            path=relative,
            evidence={"count": len(roots)},
        )
    elif roots[0] != nodes[0]:
        findings.error(
            "scene.root_not_first",
            "The first node section must be the scene root.",
            path=relative,
            line=roots[0][1],
        )
    elif not any(
        key in roots[0][0] for key in ("type", "instance", "instance_placeholder")
    ):
        findings.error(
            "scene.root_type_or_instance_missing",
            "Scene root must declare a type, instance, or instance_placeholder.",
            path=relative,
            line=roots[0][1],
        )

    inherited_root = bool(
        roots and any(key in roots[0][0] for key in ("instance", "instance_placeholder"))
    )
    known_paths: set[str] = set()
    unique_ids: dict[str, int] = {}
    for index, (attributes, line_number) in enumerate(nodes):
        name = _unquote(attributes.get("name"))
        parent = _unquote(attributes.get("parent"))
        unique_id = _unquote(attributes.get("unique_id"))
        if unique_id:
            if unique_id in unique_ids:
                findings.error(
                    "scene.node_unique_id_duplicate",
                    "Scene node unique_id is declared more than once.",
                    path=relative,
                    line=line_number,
                    evidence={"uniqueId": unique_id, "firstLine": unique_ids[unique_id]},
                )
            else:
                unique_ids[unique_id] = line_number
        if not name:
            findings.error(
                "scene.node_name_missing",
                "Node declaration has no name.",
                path=relative,
                line=line_number,
            )
            continue
        if index == 0 and parent in {None, ""}:
            continue
        if parent in {None, ""}:
            continue
        node_path = name if parent == "." else f"{parent}/{name}"
        if node_path in known_paths:
            findings.error(
                "scene.node_path_duplicate",
                "Scene contains duplicate node paths.",
                path=relative,
                line=line_number,
                evidence={"nodePath": node_path},
            )
        known_paths.add(node_path)
        if parent not in {"."} and parent not in known_paths and not inherited_root:
            findings.warning(
                "scene.parent_not_declared_earlier",
                "Node parent is not declared earlier in this scene; verify inheritance "
                "and merge state.",
                path=relative,
                line=line_number,
                evidence={"parent": parent},
            )


def _validate_scene_connections(
    relative: str,
    connections: list[tuple[dict[str, str], int]],
    findings: _Findings,
) -> None:
    required = ("signal", "from", "to", "method")
    for attributes, line_number in connections:
        missing = [key for key in required if not _unquote(attributes.get(key))]
        if missing:
            findings.error(
                "scene.connection_fields_missing",
                "Scene connection is missing required attributes.",
                path=relative,
                line=line_number,
                evidence={"missing": missing},
            )


def _parse_project_settings(
    root: Path,
    text: str,
    findings: _Findings,
    top_level_uids: dict[str, str],
) -> None:
    relative = "project.godot"
    seen_sections: dict[str, int] = {}
    seen_settings: dict[tuple[str, str], int] = {}
    active_section = ""
    config_version: int | None = None
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith((";", "#")):
            continue
        if stripped.startswith("["):
            section_match = re.fullmatch(r"\[([^]\r\n]+)\]\s*(?:;.*)?", stripped)
            if section_match is None:
                findings.error(
                    "project.section_malformed",
                    "project.godot contains a malformed section header.",
                    path=relative,
                    line=line_number,
                )
                continue
            active_section = section_match.group(1)
            if active_section in seen_sections:
                findings.error(
                    "project.section_duplicate",
                    "project.godot declares the same section more than once.",
                    path=relative,
                    line=line_number,
                    evidence={
                        "section": active_section,
                        "firstLine": seen_sections[active_section],
                    },
                )
            else:
                seen_sections[active_section] = line_number
            continue
        if "=" not in line:
            continue
        key = line.split("=", maxsplit=1)[0].strip()
        identity = (active_section, key)
        if key and identity in seen_settings:
            findings.error(
                "project.setting_duplicate",
                "project.godot declares the same setting more than once in a section.",
                path=relative,
                line=line_number,
                evidence={
                    "section": active_section,
                    "setting": key,
                    "firstLine": seen_settings[identity],
                },
            )
        elif key:
            seen_settings[identity] = line_number
        if active_section == "" and key == "config_version":
            raw_version = line.split("=", maxsplit=1)[1].strip()
            try:
                config_version = int(raw_version)
            except ValueError:
                findings.error(
                    "project.config_version_invalid",
                    "project.godot config_version is not an integer.",
                    path=relative,
                    line=line_number,
                )

    if config_version is None:
        findings.warning(
            "project.config_version_missing",
            "project.godot does not declare config_version.",
            path=relative,
        )
    elif config_version != 5:
        findings.error(
            "project.config_version_unsupported",
            "Godot 4 projects must use project config_version=5.",
            path=relative,
            evidence={"configVersion": config_version},
        )

    settings = {
        match.group("key"): _decode_escaped_string(match.group("value"))
        for match in _PROJECT_SETTING_RE.finditer(text)
    }
    main_scene = settings.get("run/main_scene")
    if not main_scene:
        findings.error(
            "project.main_scene_missing",
            "project.godot does not declare run/main_scene.",
            path=relative,
        )
    elif main_scene.startswith("uid://"):
        mapped = top_level_uids.get(main_scene)
        if mapped is None or Path(mapped).suffix.casefold() not in {".escn", ".scn", ".tscn"}:
            findings.error(
                "project.main_scene_uid_unresolved",
                "run/main_scene references a UID not declared by a scanned scene.",
                path=relative,
                evidence={"uid": main_scene, "resolvedPath": mapped},
            )
    else:
        resolved, escaped = _resolve_resource_path(root, root / "project.godot", main_scene)
        if escaped:
            findings.error(
                "project.main_scene_escape",
                "run/main_scene escapes the project root.",
                path=relative,
                evidence={"scene": main_scene},
            )
        elif resolved is None or not resolved.is_file():
            findings.error(
                "project.main_scene_missing_file",
                "run/main_scene does not resolve to an existing file.",
                path=relative,
                evidence={"scene": main_scene},
            )

    in_autoload = False
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_autoload = stripped == "[autoload]"
            continue
        if not in_autoload or "=" not in line:
            continue
        _, raw_value = line.split("=", maxsplit=1)
        value = _unquote(raw_value.strip())
        if not value:
            continue
        value = value.removeprefix("*")
        if value.startswith("uid://"):
            if value not in top_level_uids:
                findings.error(
                    "project.autoload_uid_unresolved",
                    "Autoload UID does not resolve to a scanned resource.",
                    path=relative,
                    line=line_number,
                    evidence={"autoload": value},
                )
            continue
        if not value.startswith("res://"):
            findings.warning(
                "project.autoload_path_unusual",
                "Autoload uses a non-resource path and requires engine validation.",
                path=relative,
                line=line_number,
                evidence={"autoload": value},
            )
            continue
        resolved, escaped = _resolve_resource_path(root, root / "project.godot", value)
        if escaped or resolved is None or not resolved.is_file():
            findings.error(
                "project.autoload_missing",
                "Autoload path does not resolve to an existing file.",
                path=relative,
                line=line_number,
                evidence={"autoload": value},
            )

    enabled_match = re.search(
        r"^\[editor_plugins\]\s*$"
        r"(?P<section>.*?)(?=^\[[^]\r\n]+\]\s*$|\Z)",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    if enabled_match:
        enabled_match = re.search(
            r"^enabled\s*=\s*PackedStringArray\((?P<values>.*)\)\s*$",
            enabled_match.group("section"),
            flags=re.MULTILINE,
        )
    if enabled_match:
        line_number = next(
            (
                index
                for index, line in enumerate(text.splitlines(), start=1)
                if line.strip().startswith("enabled=PackedStringArray(")
            ),
            1,
        )
        for plugin_path in _quoted_strings(enabled_match.group("values")):
            findings.warning(
                "execution.editor_plugin_enabled",
                "Enabled editor plugin is an executable import-time surface.",
                path=relative,
                line=line_number,
                evidence={"plugin": plugin_path},
            )
            resolved, escaped = _resolve_resource_path(
                root,
                root / "project.godot",
                plugin_path,
            )
            if escaped or resolved is None or not resolved.is_file():
                findings.error(
                    "project.editor_plugin_missing",
                    "Enabled editor plugin configuration does not exist.",
                    path=relative,
                    line=line_number,
                    evidence={"plugin": plugin_path},
                )


def _parse_export_presets(text: str, findings: _Findings) -> None:
    relative = "export_presets.cfg"
    records: dict[int, dict[str, object]] = {}
    active: int | None = None
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        base_match = re.fullmatch(r"\[preset\.(\d+)\]", stripped)
        if base_match:
            index = int(base_match.group(1))
            if index in records:
                findings.error(
                    "export.preset_section_duplicate",
                    "Export preset section is declared more than once.",
                    path=relative,
                    line=line_number,
                    evidence={"index": index},
                )
                active = None
            else:
                records[index] = {"line": line_number, "name": None, "platform": None}
                active = index
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            active = None
            continue
        if active is None or "=" not in line:
            continue
        key, raw_value = line.split("=", maxsplit=1)
        key = key.strip()
        if key in {"name", "platform"}:
            records[active][key] = _unquote(raw_value.strip())

    names: dict[str, int] = {}
    for index, record in sorted(records.items()):
        line_number = int(record["line"])
        name = record["name"]
        platform = record["platform"]
        if not isinstance(name, str) or not name:
            findings.error(
                "export.preset_name_missing",
                "Export preset is missing a name.",
                path=relative,
                line=line_number,
                evidence={"index": index},
            )
        elif name in names:
            findings.error(
                "export.preset_name_duplicate",
                "Export preset names must be unique.",
                path=relative,
                line=line_number,
                evidence={"name": name, "firstIndex": names[name]},
            )
        else:
            names[name] = index
        if not isinstance(platform, str) or not platform:
            findings.error(
                "export.preset_platform_missing",
                "Export preset is missing a platform.",
                path=relative,
                line=line_number,
                evidence={"index": index},
            )


def _validate_structured_text(root: Path, path: Path, text: str, findings: _Findings) -> None:
    relative = _relative(root, path)
    suffix = path.suffix.lower()
    if suffix in {".gltf", ".json"}:

        def reject_constant(value: str) -> None:
            raise ValueError(value)

        try:
            json.loads(text, parse_constant=reject_constant)
        except json.JSONDecodeError as error:
            findings.error(
                "json.invalid",
                "JSON file could not be parsed.",
                path=relative,
                line=error.lineno,
                evidence={"column": error.colno},
            )
        except ValueError as error:
            findings.error(
                "json.non_finite_number",
                "JSON contains a non-standard non-finite number.",
                path=relative,
                evidence={"value": str(error)},
            )
    elif suffix == ".toml":
        try:
            tomllib.loads(text)
        except tomllib.TOMLDecodeError as error:
            findings.error(
                "toml.invalid",
                "TOML file could not be parsed.",
                path=relative,
                evidence={"error": str(error)},
            )
    elif suffix in {".csproj", ".svg", ".xml"}:
        try:
            element_tree.fromstring(text)
        except element_tree.ParseError as error:
            findings.error(
                "xml.invalid",
                "XML file could not be parsed.",
                path=relative,
                line=error.position[0],
                evidence={"column": error.position[1]},
            )
    elif suffix == ".uid":
        value = text.strip()
        if not _UID_RE.fullmatch(value):
            findings.error(
                "resource.uid_sidecar_invalid",
                "Godot UID sidecar must contain exactly one uid:// identifier.",
                path=relative,
            )


def _git_tracked_paths(root: Path, findings: _Findings) -> set[str]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--", "."],
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return set()
    if completed.returncode != 0:
        return set()
    tracked = {
        value.decode("utf-8", errors="surrogateescape").replace("\\", "/")
        for value in completed.stdout.split(b"\x00")
        if value
    }
    for path in sorted(tracked):
        lowered = path.casefold()
        if lowered.endswith(".godot/export_credentials.cfg") or lowered.endswith(
            "export_credentials.cfg"
        ):
            findings.error(
                "git.export_credentials_tracked",
                "Confidential Godot export credentials are tracked by Git.",
                path=path,
            )
    try:
        unmerged = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-u", "-z", "--", "."],
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return tracked
    if unmerged.returncode == 0 and unmerged.stdout:
        findings.error(
            "git.unmerged_index",
            "Git index contains unresolved merge entries for this project.",
        )
    return tracked


def audit_project(
    candidate: Path,
    *,
    limits: AuditLimits | None = None,
) -> IntegrityReport:
    effective_limits = limits or AuditLimits()
    root = find_project_root(candidate)
    project_file = root / "project.godot"
    findings = _Findings(effective_limits.max_findings)
    files, total_bytes = _walk_project(root, effective_limits, findings)
    _git_tracked_paths(root, findings)

    texts: dict[Path, str] = {}
    top_level_uids: dict[str, str] = {}
    scene_files = 0
    resource_files = 0
    script_files = 0

    for path in files:
        suffix = path.suffix.lower()
        if suffix in _RESOURCE_SUFFIXES:
            resource_files += 1
        if suffix in {".escn", ".scn", ".tscn"}:
            scene_files += 1
        if suffix in {".cs", ".gd"}:
            script_files += 1
        if _is_text_path(path):
            text = _read_text(root, path, effective_limits, findings)
            if text is not None:
                texts[path] = text
                if suffix == ".gd" and _TOOL_SCRIPT_RE.search(text):
                    findings.warning(
                        "execution.tool_script_present",
                        "GDScript @tool code can execute during editor import.",
                        path=_relative(root, path),
                    )
                elif suffix == ".gdextension":
                    findings.warning(
                        "execution.gdextension_present",
                        "GDExtension configuration can load native code during editor import.",
                        path=_relative(root, path),
                    )
        else:
            _validate_binary_asset(root, path, findings)

    for path, text in texts.items():
        suffix = path.suffix.lower()
        if suffix in _TEXT_RESOURCE_SUFFIXES:
            _parse_text_resource(root, path, text, findings, top_level_uids)
        _validate_structured_text(root, path, text, findings)

    project_text = texts.get(project_file)
    if project_text is None:
        findings.error(
            "project.file_unreadable",
            "project.godot could not be read as bounded UTF-8 text.",
            path="project.godot",
        )
    else:
        _parse_project_settings(root, project_text, findings, top_level_uids)

    export_path = root / "export_presets.cfg"
    if export_path in texts:
        _parse_export_presets(texts[export_path], findings)

    errors = sum(item.severity == "error" for item in findings.items)
    warnings = sum(item.severity == "warning" for item in findings.items)
    if findings.truncated:
        errors += 1
    status = "passed" if errors == 0 else "failed"
    return IntegrityReport(
        schema_version="1.0",
        generated_at=datetime.now(UTC).isoformat(),
        status=status,
        project_root=str(root),
        project_file=str(project_file),
        scanned_files=len(files),
        scanned_bytes=total_bytes,
        scene_files=scene_files,
        resource_files=resource_files,
        script_files=script_files,
        errors=errors,
        warnings=warnings,
        findings_truncated=findings.truncated,
        findings=findings.items,
        limits=effective_limits,
    )
