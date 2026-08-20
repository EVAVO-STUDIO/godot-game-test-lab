from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import io
import json
import os
import re
import stat
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_BUNDLE_VERSION = "localization-godot-stable-id-application-bundle-v1"
_REPORT_VERSION = "evavo_godot_stable_id_bundle_admission_report_v1"
_SHA40 = re.compile(r"^[a-f0-9]{40}$")
_SHA64 = re.compile(r"^[a-f0-9]{64}$")
_REPOSITORY = re.compile(r"^EVAVO-STUDIO/[A-Za-z0-9._-]{1,100}$")
_STABLE_ID = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
_TEXT_ASSIGNMENT = re.compile(r'^\s*text\s*=\s*("(?:\\.|[^"\\])*")\s*$')
_MAX_FILES = 64
_MAX_MESSAGES = 10_000
_MAX_FILE_BYTES = 16 * 1024 * 1024
_MAX_TOTAL_BYTES = 64 * 1024 * 1024

_TOP_LEVEL_FIELDS = {
    "version",
    "generatedAt",
    "repository",
    "exactHead",
    "planSha256",
    "catalogSha256",
    "decisionSha256",
    "sourceLocale",
    "status",
    "files",
    "sourceCatalog",
    "totalRetainedBytes",
    "requiredApplicationSequence",
    "authority",
    "sha256",
}
_FILE_FIELDS = {
    "path",
    "operation",
    "beforeBytes",
    "beforeSha256",
    "beforeGitBlobSha1",
    "afterBytes",
    "afterSha256",
    "afterGitBlobSha1",
    "editCount",
    "stableIds",
    "afterContentBase64",
}
_SOURCE_CATALOG_FIELDS = {
    "path",
    "operation",
    "encoding",
    "bom",
    "sourceLocale",
    "godotLocale",
    "messageCount",
    "bytes",
    "sha256",
    "gitBlobSha1",
    "contentBase64",
    "messages",
}
_SOURCE_MESSAGE_FIELDS = {
    "stableId",
    "text",
    "sourcePath",
    "nodePath",
    "property",
    "sourceTextSha256",
}
_BUNDLE_AUTHORITY_FIELDS = {
    "appliesChanges",
    "createsFiles",
    "sourceMutationAuthority",
    "runtimeRegistrationAuthority",
    "commitAuthority",
    "pushAuthority",
    "releaseAuthority",
    "publicationAuthority",
}
_REPORT_AUTHORITY_FIELDS = {
    "targetRepositoryMutationAuthority",
    "sourceMutationAuthority",
    "runtimeRegistrationAuthority",
    "commitAuthority",
    "pushAuthority",
    "releaseAuthority",
    "publicationAuthority",
}


class StableIdBundleAdmissionError(RuntimeError):
    """Raised when a stable-ID application bundle cannot be admitted."""


def _fail(message: str) -> None:
    raise StableIdBundleAdmissionError(message)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git_blob_sha(value: bytes) -> str:
    digest = hashlib.sha1(usedforsecurity=False)
    digest.update(f"blob {len(value)}\0".encode("ascii"))
    digest.update(value)
    return digest.hexdigest()


def _fingerprint(value: dict[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "sha256"}
    return _sha256_bytes(_canonical_json(payload).encode("utf-8"))


def _with_fingerprint(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result.pop("sha256", None)
    result["sha256"] = _fingerprint(result)
    return result


def _exact_fields(label: str, value: object, expected: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{label} must be an object.")
    observed = set(value)
    if observed != expected:
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        detail = []
        if missing:
            detail.append(f"missing={','.join(missing)}")
        if extra:
            detail.append(f"extra={','.join(extra)}")
        _fail(f"{label} fields changed ({'; '.join(detail)}).")
    return value


def _bounded_string(value: object, label: str, maximum: int, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        _fail(f"{label} must be a string.")
    if (not allow_empty and not value) or len(value) > maximum:
        _fail(f"{label} length is invalid.")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise StableIdBundleAdmissionError(f"{label} is not valid Unicode.") from error
    return value


def _bounded_int(value: object, label: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        _fail(f"{label} must be an integer between {minimum} and {maximum}.")
    return value


def _sha(value: object, label: str, expression: re.Pattern[str]) -> str:
    selected = _bounded_string(value, label, 64)
    if not expression.fullmatch(selected):
        _fail(f"{label} is invalid.")
    return selected


def _validate_datetime(value: object, label: str) -> str:
    selected = _bounded_string(value, label, 80)
    try:
        parsed = datetime.fromisoformat(selected.replace("Z", "+00:00"))
    except ValueError as error:
        raise StableIdBundleAdmissionError(f"{label} must be an ISO date-time.") from error
    if parsed.tzinfo is None:
        _fail(f"{label} must include a timezone.")
    return selected


def _false_authority(label: str, value: object, expected: set[str]) -> dict[str, bool]:
    authority = _exact_fields(label, value, expected)
    for field in expected:
        if authority[field] is not False:
            _fail(f"{label}.{field} must remain false.")
    return {field: False for field in sorted(expected)}


def _decode_base64(value: object, label: str, maximum_bytes: int) -> bytes:
    source = _bounded_string(value, label, maximum_bytes * 2)
    try:
        payload = base64.b64decode(source.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error) as error:
        raise StableIdBundleAdmissionError(f"{label} is not canonical base64.") from error
    if not 1 <= len(payload) <= maximum_bytes:
        _fail(f"{label} decoded byte length is invalid.")
    if base64.b64encode(payload).decode("ascii") != source:
        _fail(f"{label} is not canonical base64.")
    return payload


def _decode_utf8(value: bytes, label: str) -> str:
    if value.startswith(b"\xef\xbb\xbf"):
        _fail(f"{label} contains a prohibited UTF-8 BOM.")
    try:
        return value.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise StableIdBundleAdmissionError(f"{label} is not valid UTF-8.") from error


def _normalise_relative_path(
    value: object,
    label: str,
    *,
    extension: str | None = None,
) -> tuple[str, tuple[str, ...]]:
    selected = _bounded_string(value, label, 500).replace("\\", "/").removeprefix("./")
    if selected.startswith("/") or re.match(r"^[A-Za-z]:/", selected):
        _fail(f"{label} must be project-relative.")
    parts = tuple(selected.split("/"))
    if any(not part or part in {".", ".."} for part in parts):
        _fail(f"{label} contains an unsafe segment.")
    if any(part.casefold() == ".git" for part in parts):
        _fail(f"{label} may not enter .git.")
    if extension and not selected.casefold().endswith(extension.casefold()):
        _fail(f"{label} must end in {extension}.")
    return selected, parts


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _safe_existing_file(root: Path, value: object, *, extension: str) -> tuple[str, Path]:
    selected, parts = _normalise_relative_path(value, "Bundle replacement path", extension=extension)
    current = root
    for part in parts:
        current = current / part
        if current.exists() and current.is_symlink():
            _fail(f"Bundle replacement path may not traverse a symbolic link: {selected}.")
    try:
        resolved = current.resolve(strict=True)
        info = resolved.stat()
    except OSError as error:
        raise StableIdBundleAdmissionError(
            f"Bundle replacement path is unavailable: {selected}."
        ) from error
    if not _is_within(resolved, root) or not stat.S_ISREG(info.st_mode):
        _fail(f"Bundle replacement path must be a regular file inside the target: {selected}.")
    if not 1 <= info.st_size <= _MAX_FILE_BYTES:
        _fail(f"Bundle replacement file size is outside policy: {selected}.")
    return selected, resolved


def _safe_creation_path(root: Path, value: object) -> tuple[str, Path]:
    selected, parts = _normalise_relative_path(
        value,
        "Bundle source-catalog path",
        extension=".csv",
    )
    current = root
    for index, part in enumerate(parts):
        current = current / part
        if not current.exists():
            continue
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode):
            _fail(f"Bundle source-catalog path may not traverse a symbolic link: {selected}.")
        if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            _fail(f"Bundle source-catalog parent is not a directory: {selected}.")
        if index == len(parts) - 1:
            _fail(f"Bundle source-catalog path already exists: {selected}.")
    resolved = (root / Path(*parts)).resolve(strict=False)
    if not _is_within(resolved, root):
        _fail(f"Bundle source-catalog path escapes the target: {selected}.")
    return selected, resolved


def _run_git(
    root: Path,
    arguments: list[str],
    *,
    binary: bool = False,
    timeout_seconds: int = 30,
) -> bytes | str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=False,
        capture_output=True,
        text=not binary,
        timeout=timeout_seconds,
        shell=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "replace") if binary else result.stderr
        stdout = result.stdout.decode("utf-8", "replace") if binary else result.stdout
        detail = (stderr or stdout or "unknown Git error").strip()
        _fail(f"git {' '.join(arguments)} failed: {detail}")
    return result.stdout


def _normalise_origin(value: str) -> str:
    selected = value.strip()
    patterns = (
        re.compile(r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$", re.I),
        re.compile(r"^git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$", re.I),
        re.compile(r"^ssh://git@github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$", re.I),
    )
    for pattern in patterns:
        match = pattern.fullmatch(selected)
        if match:
            return f"{match.group('owner')}/{match.group('repo')}"
    _fail("Target Git origin is not a supported github.com repository URL.")


def _capture_git_state(root: Path) -> dict[str, str]:
    top = str(_run_git(root, ["rev-parse", "--show-toplevel"])).strip()
    git_root = Path(top).resolve(strict=True)
    if git_root != root:
        _fail("project_root must be the target Git repository root.")
    return {
        "root": str(git_root),
        "head": str(_run_git(root, ["rev-parse", "HEAD"])).strip(),
        "origin": _normalise_origin(str(_run_git(root, ["remote", "get-url", "origin"]))),
        "status": str(
            _run_git(root, ["status", "--porcelain=v1", "--untracked-files=all"])
        ),
    }


def _validate_stable_ids(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= _MAX_MESSAGES:
        _fail(f"{label} must be a non-empty bounded array.")
    selected: list[str] = []
    for index, item in enumerate(value):
        stable_id = _bounded_string(item, f"{label}[{index}]", 256)
        if not _STABLE_ID.fullmatch(stable_id):
            _fail(f"{label}[{index}] is not a valid stable ID.")
        selected.append(stable_id)
    if len(set(selected)) != len(selected):
        _fail(f"{label} contains duplicate stable IDs.")
    return selected


def _assigned_text_values(source: str, label: str) -> list[str]:
    values: list[str] = []
    for line_number, raw in enumerate(source.splitlines(), 1):
        match = _TEXT_ASSIGNMENT.fullmatch(raw)
        if not match:
            continue
        try:
            value = json.loads(match.group(1))
        except json.JSONDecodeError as error:
            raise StableIdBundleAdmissionError(
                f"{label} has an invalid text assignment at line {line_number}."
            ) from error
        if not isinstance(value, str):
            _fail(f"{label} has a non-string text assignment at line {line_number}.")
        values.append(value)
    return values


def _validate_replacement(
    root: Path,
    exact_head: str,
    value: object,
) -> tuple[dict[str, Any], set[str], int]:
    record = _exact_fields("Bundle replacement", value, _FILE_FIELDS)
    selected, resolved = _safe_existing_file(root, record["path"], extension=".tscn")
    if record["operation"] != "replace":
        _fail(f"Bundle replacement operation must be replace: {selected}.")
    before_bytes = _bounded_int(record["beforeBytes"], f"{selected}.beforeBytes", 1, _MAX_FILE_BYTES)
    after_bytes = _bounded_int(record["afterBytes"], f"{selected}.afterBytes", 1, _MAX_FILE_BYTES)
    before_sha = _sha(record["beforeSha256"], f"{selected}.beforeSha256", _SHA64)
    before_blob = _sha(record["beforeGitBlobSha1"], f"{selected}.beforeGitBlobSha1", _SHA40)
    after_sha = _sha(record["afterSha256"], f"{selected}.afterSha256", _SHA64)
    after_blob = _sha(record["afterGitBlobSha1"], f"{selected}.afterGitBlobSha1", _SHA40)
    edit_count = _bounded_int(record["editCount"], f"{selected}.editCount", 1, _MAX_MESSAGES)
    stable_ids = _validate_stable_ids(record["stableIds"], f"{selected}.stableIds")
    if edit_count != len(stable_ids):
        _fail(f"{selected}.editCount must equal the stable-ID count.")

    current = resolved.read_bytes()
    if (
        len(current) != before_bytes
        or _sha256_bytes(current) != before_sha
        or _git_blob_sha(current) != before_blob
    ):
        _fail(f"Current target bytes do not match the bundle before identity: {selected}.")
    tracked = _run_git(root, ["ls-files", "--error-unmatch", "--", selected])
    if not str(tracked).strip():
        _fail(f"Bundle replacement is not tracked by Git: {selected}.")
    committed = _run_git(root, ["show", f"{exact_head}:{selected}"], binary=True)
    if not isinstance(committed, bytes) or committed != current:
        _fail(f"Current target bytes do not match exactHead: {selected}.")

    proposed = _decode_base64(
        record["afterContentBase64"],
        f"{selected}.afterContentBase64",
        _MAX_FILE_BYTES,
    )
    if (
        len(proposed) != after_bytes
        or _sha256_bytes(proposed) != after_sha
        or _git_blob_sha(proposed) != after_blob
    ):
        _fail(f"Proposed target bytes do not match the bundle after identity: {selected}.")
    proposed_text = _decode_utf8(proposed, f"Proposed {selected}")
    assigned = _assigned_text_values(proposed_text, f"Proposed {selected}")
    for stable_id in stable_ids:
        if assigned.count(stable_id) != 1:
            _fail(
                f"Proposed {selected} must assign stable ID {stable_id} exactly once."
            )

    return (
        {
            "path": selected,
            "beforeSha256": before_sha,
            "beforeGitBlobSha1": before_blob,
            "afterSha256": after_sha,
            "afterGitBlobSha1": after_blob,
            "stableIds": stable_ids,
        },
        set(stable_ids),
        after_bytes,
    )


def _validate_source_catalog(
    root: Path,
    source_locale: str,
    value: object,
) -> tuple[dict[str, Any], set[str], int, dict[str, str]]:
    record = _exact_fields("Bundle source catalog", value, _SOURCE_CATALOG_FIELDS)
    selected, _ = _safe_creation_path(root, record["path"])
    if record["operation"] != "create":
        _fail("Bundle source-catalog operation must be create.")
    if record["encoding"] != "UTF-8" or record["bom"] is not False:
        _fail("Bundle source catalog must be UTF-8 without BOM.")
    if record["sourceLocale"] != source_locale:
        _fail("Bundle source-catalog locale does not match the bundle source locale.")
    godot_locale = _bounded_string(record["godotLocale"], "sourceCatalog.godotLocale", 128)
    message_count = _bounded_int(
        record["messageCount"], "sourceCatalog.messageCount", 1, _MAX_MESSAGES
    )
    byte_count = _bounded_int(record["bytes"], "sourceCatalog.bytes", 1, _MAX_TOTAL_BYTES)
    expected_sha = _sha(record["sha256"], "sourceCatalog.sha256", _SHA64)
    expected_blob = _sha(record["gitBlobSha1"], "sourceCatalog.gitBlobSha1", _SHA40)

    raw_messages = record["messages"]
    if not isinstance(raw_messages, list) or len(raw_messages) != message_count:
        _fail("Bundle source-catalog messages do not match messageCount.")
    messages: list[dict[str, str]] = []
    ids: list[str] = []
    provenance: dict[str, str] = {}
    for index, item in enumerate(raw_messages):
        message = _exact_fields(
            f"sourceCatalog.messages[{index}]", item, _SOURCE_MESSAGE_FIELDS
        )
        stable_id = _bounded_string(
            message["stableId"], f"sourceCatalog.messages[{index}].stableId", 256
        )
        if not _STABLE_ID.fullmatch(stable_id):
            _fail(f"sourceCatalog.messages[{index}].stableId is invalid.")
        text = _bounded_string(
            message["text"], f"sourceCatalog.messages[{index}].text", 1_000_000
        )
        source_path, _ = _normalise_relative_path(
            message["sourcePath"],
            f"sourceCatalog.messages[{index}].sourcePath",
            extension=".tscn",
        )
        node_path = _bounded_string(
            message["nodePath"], f"sourceCatalog.messages[{index}].nodePath", 500
        )
        if message["property"] != "text":
            _fail(f"sourceCatalog.messages[{index}].property must be text.")
        text_sha = _sha(
            message["sourceTextSha256"],
            f"sourceCatalog.messages[{index}].sourceTextSha256",
            _SHA64,
        )
        if _sha256_bytes(text.encode("utf-8")) != text_sha:
            _fail(f"Source-text fingerprint is invalid for stable ID {stable_id}.")
        messages.append(
            {
                "stableId": stable_id,
                "text": text,
                "sourcePath": source_path,
                "nodePath": node_path,
                "sourceTextSha256": text_sha,
            }
        )
        ids.append(stable_id)
        provenance[stable_id] = source_path
    if len(set(ids)) != len(ids):
        _fail("Bundle source catalog contains duplicate stable IDs.")
    if ids != sorted(ids):
        _fail("Bundle source-catalog messages must be sorted by stable ID.")

    payload = _decode_base64(
        record["contentBase64"], "sourceCatalog.contentBase64", _MAX_TOTAL_BYTES
    )
    if (
        len(payload) != byte_count
        or _sha256_bytes(payload) != expected_sha
        or _git_blob_sha(payload) != expected_blob
    ):
        _fail("Bundle source-catalog bytes do not match their declared identity.")
    text = _decode_utf8(payload, "Bundle source catalog")
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error as error:
        raise StableIdBundleAdmissionError("Bundle source catalog is invalid CSV.") from error
    if not rows or rows[0] != ["keys", godot_locale]:
        _fail("Bundle source-catalog CSV header is invalid.")
    if len(rows) != message_count + 1:
        _fail("Bundle source-catalog CSV row count does not match messageCount.")
    expected_rows = [[message["stableId"], message["text"]] for message in messages]
    if rows[1:] != expected_rows:
        _fail("Bundle source-catalog CSV does not exactly match message provenance.")

    return (
        {
            "path": selected,
            "sha256": expected_sha,
            "gitBlobSha1": expected_blob,
            "sourceLocale": source_locale,
            "godotLocale": godot_locale,
            "messageCount": message_count,
            "stableIds": ids,
        },
        set(ids),
        byte_count,
        provenance,
    )


def validate_stable_id_application_bundle(bundle: dict[str, Any]) -> None:
    value = _exact_fields("Stable-ID application bundle", bundle, _TOP_LEVEL_FIELDS)
    observed_fingerprint = _sha(value["sha256"], "bundle.sha256", _SHA64)
    if _fingerprint(value) != observed_fingerprint:
        _fail("Stable-ID application-bundle fingerprint is invalid or stale.")
    if value["version"] != _BUNDLE_VERSION:
        _fail(f"Unsupported stable-ID application-bundle version: {value['version']!r}.")
    _validate_datetime(value["generatedAt"], "bundle.generatedAt")
    repository = _bounded_string(value["repository"], "bundle.repository", 128)
    if not _REPOSITORY.fullmatch(repository):
        _fail("Bundle repository identity is invalid.")
    _sha(value["exactHead"], "bundle.exactHead", _SHA40)
    for field in ("planSha256", "catalogSha256", "decisionSha256"):
        _sha(value[field], f"bundle.{field}", _SHA64)
    _bounded_string(value["sourceLocale"], "bundle.sourceLocale", 128)
    if value["status"] != "bundled-not-applied":
        _fail("Stable-ID application bundle must remain bundled-not-applied.")
    if not isinstance(value["files"], list) or not 1 <= len(value["files"]) <= _MAX_FILES:
        _fail("Bundle replacement files are missing or exceed the bounded limit.")
    _bounded_int(value["totalRetainedBytes"], "bundle.totalRetainedBytes", 1, _MAX_TOTAL_BYTES)
    sequence = value["requiredApplicationSequence"]
    if not isinstance(sequence, list) or not sequence or len(sequence) > 100:
        _fail("Bundle requiredApplicationSequence is invalid.")
    if any(not isinstance(item, str) or not item or len(item) > 500 for item in sequence):
        _fail("Bundle requiredApplicationSequence contains an invalid item.")
    if len(set(sequence)) != len(sequence):
        _fail("Bundle requiredApplicationSequence contains duplicates.")
    _false_authority("Bundle authority", value["authority"], _BUNDLE_AUTHORITY_FIELDS)


def admit_stable_id_application_bundle(
    project_root: Path,
    bundle: dict[str, Any],
) -> dict[str, Any]:
    validate_stable_id_application_bundle(bundle)
    try:
        root = Path(os.path.abspath(os.fspath(project_root.expanduser()))).resolve(strict=True)
    except OSError as error:
        raise StableIdBundleAdmissionError("Target project root is unavailable.") from error
    if not root.is_dir() or root.is_symlink():
        _fail("Target project root must be a real directory.")

    before = _capture_git_state(root)
    repository = str(bundle["repository"])
    exact_head = str(bundle["exactHead"])
    if before["head"] != exact_head:
        _fail(
            f"Target Git HEAD {before['head']} does not match bundle exactHead {exact_head}."
        )
    if before["origin"] != repository:
        _fail("Target Git origin does not match the bundle repository.")
    if before["status"]:
        _fail("Target Git repository must be clean before bundle admission.")

    replacement_reports: list[dict[str, Any]] = []
    replacement_ids: set[str] = set()
    replacement_source_by_id: dict[str, str] = {}
    replacement_paths: set[str] = set()
    retained_bytes = 0
    files = bundle["files"]
    if not isinstance(files, list):
        _fail("Bundle files are invalid.")
    observed_order = [str(item.get("path", "")) if isinstance(item, dict) else "" for item in files]
    if observed_order != sorted(observed_order):
        _fail("Bundle replacement files must be sorted by path.")
    for item in files:
        report, stable_ids, byte_count = _validate_replacement(root, exact_head, item)
        if report["path"] in replacement_paths:
            _fail(f"Bundle replacement path is duplicated: {report['path']}.")
        if replacement_ids.intersection(stable_ids):
            _fail("Stable IDs may not appear in more than one replacement file.")
        replacement_paths.add(str(report["path"]))
        replacement_ids.update(stable_ids)
        for stable_id in stable_ids:
            replacement_source_by_id[stable_id] = str(report["path"])
        replacement_reports.append(report)
        retained_bytes += byte_count

    source_report, source_ids, source_bytes, source_by_id = _validate_source_catalog(
        root, str(bundle["sourceLocale"]), bundle["sourceCatalog"]
    )
    if source_report["path"] in replacement_paths:
        _fail("Bundle source-catalog path collides with a replacement path.")
    if source_ids != replacement_ids:
        _fail("Bundle source-catalog stable IDs do not exactly match replacement IDs.")
    if source_by_id != replacement_source_by_id:
        _fail("Bundle source-message paths do not match their replacement files.")
    retained_bytes += source_bytes
    if retained_bytes != bundle["totalRetainedBytes"]:
        _fail("Bundle totalRetainedBytes does not match admitted content.")

    after = _capture_git_state(root)
    if after != before:
        _fail("Stable-ID bundle admission changed the target Git state.")
    for report in replacement_reports:
        current = (root / Path(*str(report["path"]).split("/"))).read_bytes()
        if _sha256_bytes(current) != report["beforeSha256"]:
            _fail("Stable-ID bundle admission changed target source bytes.")
    source_path = root / Path(*str(source_report["path"]).split("/"))
    if source_path.exists() or source_path.is_symlink():
        _fail("Stable-ID bundle admission created the source-catalog path.")

    report = {
        "version": _REPORT_VERSION,
        "generatedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": "passed",
        "repository": repository,
        "exactHead": exact_head,
        "bundleSha256": bundle["sha256"],
        "planSha256": bundle["planSha256"],
        "catalogSha256": bundle["catalogSha256"],
        "decisionSha256": bundle["decisionSha256"],
        "replacementFiles": replacement_reports,
        "sourceCatalog": source_report,
        "checks": {
            "bundleFingerprintVerified": True,
            "exactTargetHeadVerified": True,
            "targetOriginVerified": True,
            "targetInitiallyClean": True,
            "currentSourceBytesVerified": True,
            "proposedSourceBytesVerified": True,
            "sourceCatalogBytesVerified": True,
            "stableIdCoverageExact": True,
            "targetGitStateUnchanged": True,
            "targetSourceBytesUnchanged": True,
            "sourceCatalogNotCreated": True,
        },
        "authority": {field: False for field in sorted(_REPORT_AUTHORITY_FIELDS)},
    }
    return _with_fingerprint(report)
