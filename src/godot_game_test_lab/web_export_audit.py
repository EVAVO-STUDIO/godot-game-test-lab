from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit

_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_EXECUTABLE = re.compile(r"^[A-Za-z0-9._-]+$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_REQUIRED_SUFFIXES = (".js", ".wasm", ".pck")


@dataclass(frozen=True)
class WebExportAuditLimits:
    max_files: int = 512
    max_total_bytes: int = 2 * 1024 * 1024 * 1024
    max_file_bytes: int = 1024 * 1024 * 1024
    max_descriptor_bytes: int = 2 * 1024 * 1024

    def validate(self) -> None:
        for name, value in (
            ("max_files", self.max_files),
            ("max_total_bytes", self.max_total_bytes),
            ("max_file_bytes", self.max_file_bytes),
            ("max_descriptor_bytes", self.max_descriptor_bytes),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True)
class WebExportFinding:
    code: str
    severity: str
    message: str
    path: str | None = None

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
        }
        if self.path is not None:
            value["path"] = self.path
        return value


@dataclass(frozen=True)
class WebExportAuditReport:
    export_root: str
    descriptor_path: str
    status: str
    files_scanned: int
    total_bytes: int
    profile: str | None
    executable: str | None
    assets_verified: int
    findings: tuple[WebExportFinding, ...]

    @property
    def errors(self) -> int:
        return sum(item.severity == "error" for item in self.findings)

    @property
    def warnings(self) -> int:
        return sum(item.severity == "warning" for item in self.findings)

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": "1.0",
            "status": self.status,
            "exportRoot": self.export_root,
            "descriptorPath": self.descriptor_path,
            "filesScanned": self.files_scanned,
            "totalBytes": self.total_bytes,
            "profile": self.profile,
            "executable": self.executable,
            "assetsVerified": self.assets_verified,
            "errors": self.errors,
            "warnings": self.warnings,
            "findings": [item.to_dict() for item in self.findings],
            "truthBoundary": (
                "This audit proves bounded local descriptor, asset identity and isolation-policy "
                "consistency. It does not prove browser execution, HTTPS delivery, GPU behavior, "
                "service-worker activation or visual quality."
            ),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


@dataclass(frozen=True)
class _ScannedFile:
    path: Path
    relative: str
    size: int


def _finding(
    findings: list[WebExportFinding],
    code: str,
    severity: str,
    message: str,
    path: str | Path | None = None,
) -> None:
    findings.append(
        WebExportFinding(
            code=code,
            severity=severity,
            message=message,
            path=str(path) if path is not None else None,
        )
    )


def _report(
    root: Path,
    descriptor: Path,
    findings: list[WebExportFinding],
    *,
    files_scanned: int = 0,
    total_bytes: int = 0,
    profile: str | None = None,
    executable: str | None = None,
    assets_verified: int = 0,
) -> WebExportAuditReport:
    return WebExportAuditReport(
        export_root=str(root),
        descriptor_path=str(descriptor),
        status="failed" if any(item.severity == "error" for item in findings) else "passed",
        files_scanned=files_scanned,
        total_bytes=total_bytes,
        profile=profile,
        executable=executable,
        assets_verified=assets_verified,
        findings=tuple(findings),
    )


def audit_web_export(
    export_root: Path,
    *,
    descriptor_path: Path | None = None,
    headers_path: Path | None = None,
    limits: WebExportAuditLimits | None = None,
) -> WebExportAuditReport:
    policy = limits or WebExportAuditLimits()
    policy.validate()
    findings: list[WebExportFinding] = []
    requested_root = export_root.expanduser().absolute()
    descriptor = (descriptor_path or requested_root / "export.json").expanduser().absolute()

    if requested_root.is_symlink():
        _finding(
            findings,
            "web.root_symlink",
            "error",
            "Export root cannot be a symlink.",
            requested_root,
        )
        return _report(requested_root, descriptor, findings)
    if not requested_root.is_dir():
        _finding(
            findings,
            "web.root_missing",
            "error",
            "Godot web export root is not a directory.",
            requested_root,
        )
        return _report(requested_root, descriptor, findings)

    root = requested_root.resolve(strict=True)
    scanned, total_bytes = _scan_root(root, policy, findings)
    descriptor_value = _load_descriptor(descriptor, policy, findings)
    if descriptor_value is None:
        return _report(
            root,
            descriptor,
            findings,
            files_scanned=len(scanned),
            total_bytes=total_bytes,
        )

    profile, executable = _validate_identity(descriptor_value, findings)
    assets_verified = _verify_assets(
        descriptor_value,
        {item.relative: item for item in scanned},
        executable,
        policy,
        findings,
    )
    _verify_isolation(profile, descriptor_value, headers_path, findings)
    _verify_signature(descriptor_value.get("signature"), descriptor, findings)
    return _report(
        root,
        descriptor,
        findings,
        files_scanned=len(scanned),
        total_bytes=total_bytes,
        profile=profile,
        executable=executable,
        assets_verified=assets_verified,
    )


def _scan_root(
    root: Path,
    limits: WebExportAuditLimits,
    findings: list[WebExportFinding],
) -> tuple[list[_ScannedFile], int]:
    scanned: list[_ScannedFile] = []
    total = 0
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as error:
            _finding(findings, "web.directory_unreadable", "error", str(error), directory)
            continue
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
            if entry.is_symlink():
                _finding(
                    findings,
                    "web.symlink_rejected",
                    "error",
                    "Symlinks are not admitted inside a web export.",
                    relative,
                )
                continue
            if entry.is_dir(follow_symlinks=False):
                pending.append(path)
                continue
            if not entry.is_file(follow_symlinks=False):
                _finding(
                    findings,
                    "web.special_file_rejected",
                    "error",
                    "Only regular files and directories are admitted.",
                    relative,
                )
                continue
            try:
                size = entry.stat(follow_symlinks=False).st_size
            except OSError as error:
                _finding(findings, "web.file_unreadable", "error", str(error), relative)
                continue
            scanned.append(_ScannedFile(path, relative, size))
            total += size
            if size > limits.max_file_bytes:
                _finding(
                    findings,
                    "web.file_limit_exceeded",
                    "error",
                    f"File exceeds the {limits.max_file_bytes}-byte limit.",
                    relative,
                )
            if len(scanned) > limits.max_files:
                _finding(
                    findings,
                    "web.file_count_exceeded",
                    "error",
                    f"Bundle exceeds the {limits.max_files}-file limit.",
                )
                return scanned, total
            if total > limits.max_total_bytes:
                _finding(
                    findings,
                    "web.total_size_exceeded",
                    "error",
                    f"Bundle exceeds the {limits.max_total_bytes}-byte limit.",
                )
                return scanned, total
    return scanned, total


def _load_descriptor(
    path: Path,
    limits: WebExportAuditLimits,
    findings: list[WebExportFinding],
) -> dict[str, Any] | None:
    if path.is_symlink() or not path.is_file():
        _finding(
            findings,
            "web.descriptor_missing",
            "error",
            "A regular non-linked export descriptor is required.",
            path,
        )
        return None
    try:
        if path.stat().st_size > limits.max_descriptor_bytes:
            _finding(
                findings,
                "web.descriptor_too_large",
                "error",
                "Export descriptor exceeds the JSON size limit.",
                path,
            )
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        _finding(findings, "web.descriptor_invalid_json", "error", str(error), path)
        return None
    if not isinstance(value, dict):
        _finding(
            findings,
            "web.descriptor_not_object",
            "error",
            "Export descriptor must contain a JSON object.",
            path,
        )
        return None
    return value


def _validate_identity(
    descriptor: dict[str, Any],
    findings: list[WebExportFinding],
) -> tuple[str | None, str | None]:
    if descriptor.get("schemaVersion") != 2:
        _finding(
            findings,
            "web.descriptor_schema",
            "error",
            "Godot web export descriptors must use schemaVersion 2.",
        )
    game_id = descriptor.get("id")
    if not isinstance(game_id, str) or _ID.fullmatch(game_id) is None:
        _finding(findings, "web.descriptor_id", "error", "Descriptor id must be kebab-case.")

    executable = descriptor.get("executable")
    if not isinstance(executable, str) or _EXECUTABLE.fullmatch(executable) is None:
        _finding(
            findings,
            "web.descriptor_executable",
            "error",
            "Descriptor executable must be a safe basename.",
        )
        executable = None

    profile = descriptor.get("webRuntimeProfile")
    if profile not in {"single-threaded", "threaded"}:
        _finding(
            findings,
            "web.descriptor_profile",
            "error",
            "webRuntimeProfile must be single-threaded or threaded.",
        )
        profile = None
    if descriptor.get("renderer") != "compatibility":
        _finding(
            findings,
            "web.descriptor_renderer",
            "error",
            "Godot 4 web exports must declare the Compatibility renderer.",
        )

    if executable is not None:
        stem = executable.removesuffix(".js")
        _require_exact_reference(
            descriptor.get("loaderUrl"),
            f"{stem}.js",
            "web.loader_executable_mismatch",
            "loaderUrl must identify the generated executable JavaScript file.",
            findings,
        )
        _require_exact_reference(
            descriptor.get("mainPack"),
            f"{stem}.pck",
            "web.main_pack_executable_mismatch",
            "mainPack must identify the generated executable PCK file.",
            findings,
        )
    return profile, executable


def _require_exact_reference(
    value: object,
    expected: str,
    code: str,
    message: str,
    findings: list[WebExportFinding],
) -> None:
    if not isinstance(value, str):
        return
    relative = _safe_reference(value)
    if relative is not None and relative != expected:
        _finding(findings, code, "error", message, relative)


def _normalise_sizes(
    value: object,
    findings: list[WebExportFinding],
) -> dict[str, int] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        _finding(findings, "web.file_size_table", "error", "fileSizes must be an object.")
        return None
    result: dict[str, int] = {}
    for raw_reference, raw_size in sorted(value.items(), key=lambda item: str(item[0])):
        if not isinstance(raw_reference, str):
            _finding(
                findings,
                "web.file_size_reference",
                "error",
                "fileSizes keys must be strings.",
            )
            continue
        relative = _safe_reference(raw_reference)
        if relative is None:
            _finding(
                findings,
                "web.file_size_reference",
                "error",
                "fileSizes contains an unsafe or non-local reference.",
                raw_reference,
            )
            continue
        if not isinstance(raw_size, int) or isinstance(raw_size, bool) or raw_size < 0:
            _finding(
                findings,
                "web.file_size_value",
                "error",
                "fileSizes values must be non-negative integers.",
                relative,
            )
            continue
        if relative in result:
            _finding(
                findings,
                "web.file_size_duplicate",
                "error",
                "Multiple fileSizes entries normalize to the same path.",
                relative,
            )
            continue
        result[relative] = raw_size
    return result


def _verify_assets(
    descriptor: dict[str, Any],
    scanned: dict[str, _ScannedFile],
    executable: str | None,
    limits: WebExportAuditLimits,
    findings: list[WebExportFinding],
) -> int:
    integrity = descriptor.get("assetIntegrity")
    if not isinstance(integrity, dict) or len(integrity) < 3:
        _finding(
            findings,
            "web.integrity_table",
            "error",
            "assetIntegrity must bind the generated JS, WASM and PCK files.",
        )
        return 0
    sizes = _normalise_sizes(descriptor.get("fileSizes"), findings)
    for field in ("loaderUrl", "mainPack"):
        value = descriptor.get(field)
        if not isinstance(value, str) or _safe_reference(value) is None:
            _finding(
                findings,
                f"web.{field}_reference",
                "error",
                f"{field} must be a safe local relative asset reference.",
            )

    normalized: dict[str, str] = {}
    verified = 0
    for raw_reference, raw_digest in sorted(integrity.items(), key=lambda item: str(item[0])):
        if not isinstance(raw_reference, str):
            _finding(
                findings,
                "web.integrity_reference",
                "error",
                "assetIntegrity keys must be strings.",
            )
            continue
        relative = _safe_reference(raw_reference)
        if relative is None:
            _finding(
                findings,
                "web.integrity_reference",
                "error",
                "assetIntegrity contains an unsafe or non-local reference.",
                raw_reference,
            )
            continue
        if not isinstance(raw_digest, str) or _SHA256.fullmatch(raw_digest) is None:
            _finding(
                findings,
                "web.integrity_digest",
                "error",
                "assetIntegrity values must be lowercase SHA-256 digests.",
                relative,
            )
            continue
        if relative in normalized:
            _finding(
                findings,
                "web.integrity_duplicate",
                "error",
                "Multiple assetIntegrity entries normalize to the same path.",
                relative,
            )
            continue
        normalized[relative] = raw_digest
        item = scanned.get(relative)
        if item is None:
            _finding(
                findings,
                "web.asset_missing",
                "error",
                "An integrity-bound export asset is missing.",
                relative,
            )
            continue
        if item.size > limits.max_file_bytes:
            continue
        try:
            observed = _sha256_regular(item.path, item.size)
        except OSError as error:
            _finding(findings, "web.asset_unreadable", "error", str(error), relative)
            continue

        hash_matches = observed == raw_digest
        if not hash_matches:
            _finding(
                findings,
                "web.asset_hash_mismatch",
                "error",
                "Asset SHA-256 does not match the descriptor.",
                relative,
            )

        size_matches = True
        if sizes is not None:
            expected_size = sizes.get(relative)
            if expected_size is None:
                _finding(
                    findings,
                    "web.asset_size_missing",
                    "error",
                    "fileSizes lacks an integrity-bound asset.",
                    relative,
                )
                size_matches = False
            elif expected_size != item.size:
                _finding(
                    findings,
                    "web.asset_size_mismatch",
                    "error",
                    "Asset size does not match the descriptor.",
                    relative,
                )
                size_matches = False
        if hash_matches and size_matches:
            verified += 1

    if executable is not None:
        stem = executable.removesuffix(".js")
        for relative in (f"{stem}{suffix}" for suffix in _REQUIRED_SUFFIXES):
            if relative not in normalized:
                _finding(
                    findings,
                    "web.required_asset_unbound",
                    "error",
                    "Generated JS, WASM and PCK assets must all be integrity-bound.",
                    relative,
                )
    for field in ("loaderUrl", "mainPack"):
        value = descriptor.get(field)
        relative = _safe_reference(value) if isinstance(value, str) else None
        if relative is not None and relative not in normalized:
            _finding(
                findings,
                "web.descriptor_asset_unbound",
                "error",
                f"{field} is not present in assetIntegrity.",
                relative,
            )
    return verified


def _verify_isolation(
    profile: str | None,
    descriptor: dict[str, Any],
    headers_path: Path | None,
    findings: list[WebExportFinding],
) -> None:
    ensure = descriptor.get("ensureCrossOriginIsolationHeaders", False)
    if not isinstance(ensure, bool):
        _finding(
            findings,
            "web.isolation_flag",
            "error",
            "ensureCrossOriginIsolationHeaders must be a boolean.",
        )
        ensure = False
    headers = _load_headers(headers_path, findings) if headers_path is not None else {}
    coop = headers.get("cross-origin-opener-policy", "").lower() == "same-origin"
    coep = headers.get("cross-origin-embedder-policy", "").lower() == "require-corp"
    if profile == "threaded":
        if not ensure and not (coop and coep):
            _finding(
                findings,
                "web.threaded_isolation_unproven",
                "error",
                "Threaded exports require the Godot PWA isolation option or COOP/COEP evidence.",
            )
        if headers_path is not None and not coop:
            _finding(
                findings,
                "web.coop_header",
                "error",
                "Threaded evidence requires Cross-Origin-Opener-Policy: same-origin.",
                headers_path,
            )
        if headers_path is not None and not coep:
            _finding(
                findings,
                "web.coep_header",
                "error",
                "Threaded evidence requires Cross-Origin-Embedder-Policy: require-corp.",
                headers_path,
            )
        _finding(
            findings,
            "web.secure_context_unproven",
            "warning",
            "Static inspection cannot prove that a threaded export is served over HTTPS.",
        )
    elif profile == "single-threaded" and ensure:
        _finding(
            findings,
            "web.single_thread_isolation_extra",
            "warning",
            "Single-threaded exports do not normally need cross-origin isolation.",
        )


def _load_headers(path: Path, findings: list[WebExportFinding]) -> dict[str, str]:
    candidate = path.expanduser().absolute()
    if candidate.is_symlink() or not candidate.is_file():
        _finding(
            findings,
            "web.headers_missing",
            "error",
            "Hosting-header evidence must be a regular non-linked file.",
            candidate,
        )
        return {}
    try:
        if candidate.stat().st_size > 1024 * 1024:
            _finding(
                findings,
                "web.headers_too_large",
                "error",
                "Hosting-header evidence exceeds 1 MiB.",
                candidate,
            )
            return {}
        text = candidate.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        _finding(findings, "web.headers_unreadable", "error", str(error), candidate)
        return {}
    if candidate.suffix.lower() == ".json":
        try:
            value = json.loads(text)
        except json.JSONDecodeError as error:
            _finding(findings, "web.headers_invalid_json", "error", str(error), candidate)
            return {}
        if isinstance(value, dict) and isinstance(value.get("headers"), dict):
            value = value["headers"]
        if not isinstance(value, dict):
            _finding(
                findings,
                "web.headers_not_object",
                "error",
                "JSON hosting-header evidence must contain an object.",
                candidate,
            )
            return {}
        return {
            key.strip().lower(): item.strip()
            for key, item in value.items()
            if isinstance(key, str) and isinstance(item, str)
        }
    headers: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        if re.fullmatch(r"[a-z0-9-]+", key):
            headers[key] = value.strip()
    return headers


def _verify_signature(
    value: object,
    descriptor_path: Path,
    findings: list[WebExportFinding],
) -> None:
    if value is None:
        _finding(
            findings,
            "web.signature_missing",
            "warning",
            "Descriptor is unsigned; retain it in development or candidate-only lanes.",
            descriptor_path,
        )
    elif not _valid_signature(value):
        _finding(
            findings,
            "web.signature_invalid",
            "error",
            "Descriptor signature envelope is malformed.",
            descriptor_path,
        )
    else:
        _finding(
            findings,
            "web.signature_unverified",
            "warning",
            "Signature is present but no trusted public key was supplied.",
            descriptor_path,
        )


def _safe_reference(value: str) -> str | None:
    if not value or "\x00" in value or "\\" in value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        return None
    decoded = unquote(parsed.path)
    if decoded.startswith("/") or "//" in decoded:
        return None
    while decoded.startswith("./"):
        decoded = decoded[2:]
    if not decoded:
        return None
    path = PurePosixPath(decoded)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path.as_posix()


def _sha256_regular(path: Path, expected_size: int) -> str:
    before = path.lstat()
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise OSError("Asset changed from a regular file before hashing.")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        if not stat.S_ISREG(opened.st_mode) or opened.st_size != expected_size:
            raise OSError("Asset identity or size changed before hashing.")
        while block := handle.read(1024 * 1024):
            digest.update(block)
        completed = os.fstat(handle.fileno())
    after = path.lstat()
    identities = {
        (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
        for item in (before, opened, completed, after)
    }
    if not stat.S_ISREG(after.st_mode) or len(identities) != 1:
        raise OSError("Asset changed while its SHA-256 identity was being calculated.")
    return digest.hexdigest()


def _valid_signature(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {"algorithm", "keyId", "value"}:
        return False
    return (
        value.get("algorithm") == "ECDSA_P256_SHA256"
        and isinstance(value.get("keyId"), str)
        and _ID.fullmatch(value["keyId"]) is not None
        and isinstance(value.get("value"), str)
        and re.fullmatch(r"[A-Za-z0-9_-]+", value["value"]) is not None
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="godot-lab-web-export-audit",
        description=(
            "Audit one generated Godot 4 web export descriptor, exact asset bytes and "
            "threaded hosting-isolation evidence without launching a browser."
        ),
    )
    parser.add_argument("export_root", type=Path)
    parser.add_argument("--descriptor", type=Path)
    parser.add_argument("--headers", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--warnings-as-errors", action="store_true")
    parser.add_argument("--max-files", type=int, default=512)
    parser.add_argument("--max-total-mib", type=int, default=2048)
    parser.add_argument("--max-file-mib", type=int, default=1024)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        report = audit_web_export(
            args.export_root,
            descriptor_path=args.descriptor,
            headers_path=args.headers,
            limits=WebExportAuditLimits(
                max_files=args.max_files,
                max_total_bytes=args.max_total_mib * 1024 * 1024,
                max_file_bytes=args.max_file_mib * 1024 * 1024,
            ),
        )
    except (OSError, ValueError) as error:
        print(
            json.dumps(
                {"schemaVersion": "1.0", "status": "blocked", "error": str(error)},
                indent=2,
                ensure_ascii=False,
            )
        )
        return 2
    payload = report.to_dict()
    passed = report.status == "passed" and not (
        args.warnings_as_errors and report.warnings > 0
    )
    payload["warningsAsErrors"] = args.warnings_as_errors
    payload["policyStatus"] = "passed" if passed else "failed"
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if args.output is not None:
        destination = args.output.expanduser().absolute()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
