from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .core import CommandResult, find_project_root, run_command
from .pipeline import (
    PipelineReport,
    command_succeeded,
    validate_project_pipeline,
    write_report_bundle,
)

_REQUEST_VERSION = "localization-godot-plural-testlab-request-v1"
_REPORT_VERSION = "evavo_godot_plural_localization_test_lab_report_v1"
_MARKER = "EVAVO_GODOT_PLURAL_RESULT_V1:"
_SHA40 = re.compile(r"^[a-f0-9]{40}$")
_SHA64 = re.compile(r"^[a-f0-9]{64}$")
_REPOSITORY = re.compile(r"^EVAVO-STUDIO/[A-Za-z0-9._-]{1,100}$")
_MAX_REQUEST_BYTES = 2 * 1024 * 1024
_MAX_PROBES = 10_000


@dataclass(slots=True)
class GitState:
    root: str
    head: str
    origin: str
    status_porcelain: str


@dataclass(slots=True)
class PluralProbeResult:
    message_id: str
    locale: str
    godot_locale: str
    singular_key: str
    plural_key: str
    context: str
    n: int
    expected_form_key: str
    expected_text: str
    actual_text: str
    matched: bool


@dataclass(slots=True)
class PluralLocalizationReport:
    version: str
    generated_at: str
    status: str
    request_sha256: str
    project_root: str
    repository: str
    exact_head: str
    csv_path: str
    csv_sha256: str
    csv_bytes: int
    git_before: GitState
    git_after: GitState | None
    native_validation: dict[str, Any]
    runtime_probes: list[PluralProbeResult] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    commands: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    authority: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


def _generated_at() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


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


def _request_fingerprint(request: dict[str, Any]) -> str:
    payload = {key: value for key, value in request.items() if key != "sha256"}
    return _sha256_bytes(_canonical_json(payload).encode("utf-8"))


def load_plural_testlab_request(path: Path) -> dict[str, Any]:
    selected = path.expanduser().resolve(strict=True)
    if not selected.is_file() or selected.is_symlink():
        raise ValueError("Plural localization Test Lab request must be a real regular file.")
    if selected.stat().st_size <= 0 or selected.stat().st_size > _MAX_REQUEST_BYTES:
        raise ValueError("Plural localization Test Lab request exceeds the bounded file-size policy.")
    raw = selected.read_text(encoding="utf-8")
    request = json.loads(raw)
    if not isinstance(request, dict):
        raise ValueError("Plural localization Test Lab request must be a JSON object.")
    validate_plural_testlab_request(request)
    return request


def validate_plural_testlab_request(request: dict[str, Any]) -> None:
    if request.get("version") != _REQUEST_VERSION:
        raise ValueError(f"Unsupported plural localization request version: {request.get('version')!r}.")
    repository = str(request.get("repository", ""))
    exact_head = str(request.get("exactHead", ""))
    csv_sha = str(request.get("csvSha256", ""))
    request_sha = str(request.get("sha256", ""))
    if not _REPOSITORY.fullmatch(repository):
        raise ValueError("Plural localization request repository identity is invalid.")
    if not _SHA40.fullmatch(exact_head):
        raise ValueError("Plural localization request exactHead must be a lowercase 40-character Git SHA.")
    if not _SHA64.fullmatch(csv_sha):
        raise ValueError("Plural localization request csvSha256 is invalid.")
    if not _SHA64.fullmatch(request_sha):
        raise ValueError("Plural localization request sha256 is invalid.")
    if _request_fingerprint(request) != request_sha:
        raise ValueError("Plural localization request fingerprint is invalid or stale.")
    csv_bytes = request.get("csvBytes")
    if not isinstance(csv_bytes, int) or isinstance(csv_bytes, bool) or csv_bytes <= 0:
        raise ValueError("Plural localization request csvBytes must be a positive integer.")
    probes = request.get("runtimeProbes")
    if not isinstance(probes, list) or not probes or len(probes) > _MAX_PROBES:
        raise ValueError("Plural localization request runtimeProbes are missing or exceed the bounded limit.")
    for index, probe in enumerate(probes):
        if not isinstance(probe, dict):
            raise ValueError(f"runtimeProbes[{index}] must be an object.")
        for key in (
            "messageId",
            "locale",
            "godotLocale",
            "singularKey",
            "pluralKey",
            "context",
            "expectedFormKey",
            "expectedText",
        ):
            if not isinstance(probe.get(key), str):
                raise ValueError(f"runtimeProbes[{index}].{key} must be a string.")
        n = probe.get("n")
        if not isinstance(n, int) or isinstance(n, bool) or n < 0 or n > 2_147_483_647:
            raise ValueError(f"runtimeProbes[{index}].n must be a non-negative 32-bit integer.")
    authority = request.get("authority")
    if not isinstance(authority, dict):
        raise ValueError("Plural localization request authority block is missing.")
    expected_authority = {
        "requestExecutesGodot": False,
        "requestWritesTarget": False,
        "requestPublishesTarget": False,
        "nativeGodotImportVerified": False,
        "runtimePluralLookupVerified": False,
        "testLabExecutionRequired": True,
    }
    for key, expected in expected_authority.items():
        if authority.get(key) is not expected:
            raise ValueError(f"Plural localization request authority.{key} is invalid.")
    downstream = request.get("downstream")
    if not isinstance(downstream, dict):
        raise ValueError("Plural localization request downstream block is missing.")
    if downstream.get("authorityRepository") != "EVAVO-STUDIO/godot-game-test-lab":
        raise ValueError("Plural localization request downstream authority repository is invalid.")
    if downstream.get("requiredCapability") != "testlab.project.validate-runtime":
        raise ValueError("Plural localization request downstream capability is invalid.")


def _command_payload(result: CommandResult) -> dict[str, Any]:
    return asdict(result)


def _run_git(args: list[str], cwd: Path, timeout_seconds: int = 30) -> CommandResult:
    result = run_command(["git", *args], cwd, timeout_seconds)
    if not command_succeeded(result):
        detail = result.stderr or result.stdout or "unknown git error"
        raise ValueError(f"Git command failed: git {' '.join(args)}: {detail}")
    return result


def _normalize_origin(value: str) -> str:
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
    raise ValueError("Target Git origin is not a supported github.com repository URL.")


def capture_git_state(project_root: Path) -> tuple[GitState, list[CommandResult]]:
    commands: list[CommandResult] = []
    top = _run_git(["rev-parse", "--show-toplevel"], project_root)
    commands.append(top)
    git_root = Path(top.stdout.strip()).expanduser().resolve(strict=True)
    head_result = _run_git(["rev-parse", "HEAD"], git_root)
    commands.append(head_result)
    origin_result = _run_git(["remote", "get-url", "origin"], git_root)
    commands.append(origin_result)
    status_result = _run_git(
        ["status", "--porcelain=v1", "--untracked-files=all"], git_root
    )
    commands.append(status_result)
    return (
        GitState(
            root=str(git_root),
            head=head_result.stdout.strip(),
            origin=_normalize_origin(origin_result.stdout),
            status_porcelain=status_result.stdout,
        ),
        commands,
    )


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _safe_csv_path(project_root: Path, relative_value: str) -> Path:
    selected = relative_value.strip().replace("\\", "/").removeprefix("./")
    if not selected or selected.startswith("/") or re.match(r"^[A-Za-z]:/", selected):
        raise ValueError("Plural localization CSV path must be project-relative.")
    parts = selected.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        raise ValueError("Plural localization CSV path contains an unsafe path segment.")
    if not selected.casefold().endswith(".csv"):
        raise ValueError("Plural localization CSV path must end in .csv.")
    current = project_root
    for part in parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise ValueError("Plural localization CSV path may not traverse a symbolic link.")
    resolved = (project_root / Path(*parts)).resolve(strict=True)
    if not _is_within(resolved, project_root):
        raise ValueError("Plural localization CSV path escapes the selected Godot project.")
    if not resolved.is_file() or resolved.is_symlink():
        raise ValueError("Plural localization CSV path must resolve to a real regular file.")
    return resolved


def _verify_csv(csv_path: Path, request: dict[str, Any]) -> tuple[str, int]:
    data = csv_path.read_bytes()
    digest = _sha256_bytes(data)
    size = len(data)
    if digest != request["csvSha256"]:
        raise ValueError("Plural localization CSV SHA-256 does not match the request.")
    if size != request["csvBytes"]:
        raise ValueError("Plural localization CSV byte count does not match the request.")
    if data.startswith(b"\xef\xbb\xbf"):
        raise ValueError("Plural localization CSV must be UTF-8 without BOM.")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("Plural localization CSV is not valid UTF-8.") from error
    return digest, size


def _select_godot_executable(report: PipelineReport) -> Path:
    for tool in report.tools:
        if tool.id in {"godot", "godot-mono"} and tool.compatible and tool.executable:
            selected = Path(tool.executable).expanduser().resolve(strict=True)
            if selected.is_file():
                return selected
    raise ValueError("Native validation did not retain a compatible Godot executable.")


def _probe_script(request: dict[str, Any]) -> str:
    payload = json.dumps(
        {"runtimeProbes": request["runtimeProbes"]},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    quoted_payload = json.dumps(payload, ensure_ascii=False)
    return f'''extends SceneTree

const MARKER := "{_MARKER}"
const PAYLOAD_JSON := {quoted_payload}

func _initialize() -> void:
    var payload = JSON.parse_string(PAYLOAD_JSON)
    if typeof(payload) != TYPE_DICTIONARY:
        print(MARKER + JSON.stringify({{"version":"evavo-godot-plural-probe-v1","status":"invalid-payload","results":[]}}))
        quit(7)
        return
    var results: Array = []
    var all_matched := true
    for raw_probe in payload.get("runtimeProbes", []):
        var probe: Dictionary = raw_probe
        TranslationServer.set_locale(String(probe.get("godotLocale", "")))
        var actual := String(TranslationServer.translate_plural(
            StringName(String(probe.get("singularKey", ""))),
            StringName(String(probe.get("pluralKey", ""))),
            int(probe.get("n", 0)),
            StringName(String(probe.get("context", "")))
        ))
        var expected := String(probe.get("expectedText", ""))
        var matched := actual == expected
        all_matched = all_matched and matched
        results.append({{
            "messageId": String(probe.get("messageId", "")),
            "locale": String(probe.get("locale", "")),
            "godotLocale": String(probe.get("godotLocale", "")),
            "singularKey": String(probe.get("singularKey", "")),
            "pluralKey": String(probe.get("pluralKey", "")),
            "context": String(probe.get("context", "")),
            "n": int(probe.get("n", 0)),
            "expectedFormKey": String(probe.get("expectedFormKey", "")),
            "expectedText": expected,
            "actualText": actual,
            "matched": matched
        }})
    print(MARKER + JSON.stringify({{"version":"evavo-godot-plural-probe-v1","status":"passed" if all_matched else "failed","results":results}}))
    quit(0 if all_matched else 3)
'''


def _parse_probe_payload(result: CommandResult) -> dict[str, Any]:
    marker_lines = [
        line[len(_MARKER) :]
        for line in result.stdout.splitlines()
        if line.startswith(_MARKER)
    ]
    if len(marker_lines) != 1:
        raise ValueError("Godot plural probe did not emit exactly one machine result marker.")
    payload = json.loads(marker_lines[0])
    if not isinstance(payload, dict) or payload.get("version") != "evavo-godot-plural-probe-v1":
        raise ValueError("Godot plural probe emitted an invalid result contract.")
    results = payload.get("results")
    if not isinstance(results, list):
        raise ValueError("Godot plural probe result list is invalid.")
    return payload


def _normalize_probe_results(
    request: dict[str, Any], payload: dict[str, Any]
) -> list[PluralProbeResult]:
    raw_results = payload.get("results", [])
    expected = request["runtimeProbes"]
    if len(raw_results) != len(expected):
        raise ValueError("Godot plural probe result count does not match the request.")
    normalized: list[PluralProbeResult] = []
    identity_fields = (
        "messageId",
        "locale",
        "godotLocale",
        "singularKey",
        "pluralKey",
        "context",
        "n",
        "expectedFormKey",
        "expectedText",
    )
    for index, (requested, actual) in enumerate(zip(expected, raw_results, strict=True)):
        if not isinstance(actual, dict):
            raise ValueError(f"Godot plural probe result {index} must be an object.")
        for field_name in identity_fields:
            if actual.get(field_name) != requested.get(field_name):
                raise ValueError(
                    f"Godot plural probe result {index} drifted from request field {field_name}."
                )
        actual_text = actual.get("actualText")
        matched = actual.get("matched")
        if not isinstance(actual_text, str) or not isinstance(matched, bool):
            raise ValueError(f"Godot plural probe result {index} has invalid result fields.")
        normalized.append(
            PluralProbeResult(
                message_id=requested["messageId"],
                locale=requested["locale"],
                godot_locale=requested["godotLocale"],
                singular_key=requested["singularKey"],
                plural_key=requested["pluralKey"],
                context=requested["context"],
                n=requested["n"],
                expected_form_key=requested["expectedFormKey"],
                expected_text=requested["expectedText"],
                actual_text=actual_text,
                matched=matched,
            )
        )
    return normalized


def _state_unchanged(before: GitState, after: GitState) -> bool:
    return (
        before.root == after.root
        and before.head == after.head
        and before.origin.casefold() == after.origin.casefold()
        and before.status_porcelain == after.status_porcelain
    )


def run_plural_localization_validation(
    candidate: Path,
    request: dict[str, Any],
    *,
    artifacts_root: Path,
    godot_executable: Path | None = None,
    dotnet_executable: Path | None = None,
    minimum_godot_version: str = "4.6.2",
    timeout_seconds: int = 300,
    boot_frames: int = 5,
    warnings_as_errors: bool = False,
    recovery_diagnostic: bool = True,
    allow_major_upgrade: bool = False,
) -> PluralLocalizationReport:
    validate_plural_testlab_request(request)
    project_root = find_project_root(candidate).resolve(strict=True)
    git_before, git_commands_before = capture_git_state(project_root)
    if git_before.head != request["exactHead"]:
        raise ValueError(
            f"Target Git HEAD {git_before.head} does not match request exactHead {request['exactHead']}."
        )
    if git_before.origin.casefold() != request["repository"].casefold():
        raise ValueError(
            f"Target Git origin {git_before.origin} does not match request repository {request['repository']}."
        )
    git_root = Path(git_before.root)
    artifact_root = artifacts_root.expanduser().resolve()
    if _is_within(artifact_root, git_root):
        raise ValueError("Plural localization Test Lab artifacts must be outside the target Git repository.")
    artifact_root.mkdir(parents=True, exist_ok=True)

    csv_path = _safe_csv_path(project_root, str(request.get("csvPath", "")))
    csv_sha, csv_bytes = _verify_csv(csv_path, request)

    request_path = artifact_root / "request.json"
    request_path.write_text(
        json.dumps(request, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    native_root = artifact_root / "native-validation"
    report = validate_project_pipeline(
        project_root,
        godot_executable=godot_executable,
        dotnet_executable=dotnet_executable,
        minimum_godot_version=minimum_godot_version,
        timeout_seconds=max(1, timeout_seconds),
        boot_frames=max(0, boot_frames),
        run_integrity_audit=True,
        warnings_as_errors=warnings_as_errors,
        recovery_diagnostic=recovery_diagnostic,
        allow_major_upgrade=allow_major_upgrade,
        log_directory=native_root / "engine-logs",
    )
    write_report_bundle(report, native_root)

    findings: list[str] = []
    commands = [_command_payload(item) for item in git_commands_before]
    runtime_results: list[PluralProbeResult] = []
    native_passed = report.status == "passed"
    runtime_passed = False
    probe_command: CommandResult | None = None

    if native_passed:
        godot = _select_godot_executable(report)
        probe_root = artifact_root / "plural-probe"
        probe_root.mkdir(parents=True, exist_ok=True)
        probe_script = probe_root / "plural_probe.gd"
        probe_script.write_text(_probe_script(request), encoding="utf-8")
        probe_log = probe_root / "godot-plural-probe.log"
        probe_command = run_command(
            [
                str(godot),
                "--headless",
                "--path",
                str(project_root),
                "--log-file",
                str(probe_log),
                "--script",
                probe_script.resolve().as_posix(),
            ],
            project_root,
            max(1, timeout_seconds),
        )
        commands.append(_command_payload(probe_command))
        try:
            probe_payload = _parse_probe_payload(probe_command)
            runtime_results = _normalize_probe_results(request, probe_payload)
            runtime_passed = (
                command_succeeded(probe_command)
                and probe_payload.get("status") == "passed"
                and bool(runtime_results)
                and all(item.matched for item in runtime_results)
            )
        except (ValueError, json.JSONDecodeError) as error:
            findings.append(str(error))
            runtime_passed = False
        if probe_command.timed_out:
            findings.append("Godot plural runtime probe timed out.")
        elif probe_command.exit_code != 0:
            findings.append(
                f"Godot plural runtime probe exited with code {probe_command.exit_code}."
            )
        if not runtime_passed and not findings:
            findings.append("One or more Godot plural runtime probes did not match expected text.")
    else:
        findings.append("Native Godot validation did not pass; plural runtime probes were withheld.")

    csv_sha_after, csv_bytes_after = _verify_csv(csv_path, request)
    if csv_sha_after != csv_sha or csv_bytes_after != csv_bytes:
        findings.append("Plural localization CSV bytes changed during validation.")

    git_after, git_commands_after = capture_git_state(project_root)
    commands.extend(_command_payload(item) for item in git_commands_after)
    if git_after.head != request["exactHead"]:
        findings.append("Target Git HEAD changed during validation.")
    if git_after.origin.casefold() != request["repository"].casefold():
        findings.append("Target Git origin changed during validation.")
    git_unchanged = _state_unchanged(git_before, git_after)
    if not git_unchanged:
        findings.append("Target Git state changed during plural localization validation.")

    passed = native_passed and runtime_passed and git_unchanged and not findings
    final_report = PluralLocalizationReport(
        version=_REPORT_VERSION,
        generated_at=_generated_at(),
        status="passed" if passed else "failed",
        request_sha256=request["sha256"],
        project_root=str(project_root),
        repository=request["repository"],
        exact_head=request["exactHead"],
        csv_path=request["csvPath"],
        csv_sha256=csv_sha,
        csv_bytes=csv_bytes,
        git_before=git_before,
        git_after=git_after,
        native_validation={
            "status": report.status,
            "schemaVersion": report.schema_version,
            "runId": report.run_id,
            "reportPath": str(native_root / "report.json"),
            "findings": list(report.findings),
            "diagnostics": list(report.diagnostics),
        },
        runtime_probes=runtime_results,
        findings=findings,
        commands=commands,
        artifacts=[
            str(request_path),
            str(native_root / "report.json"),
            *(
                [str(artifact_root / "plural-probe" / "plural_probe.gd"), str(artifact_root / "plural-probe" / "godot-plural-probe.log")]
                if native_passed
                else []
            ),
        ],
        authority={
            "requestFingerprintVerified": True,
            "exactTargetHeadVerified": git_before.head == request["exactHead"],
            "exactCsvBytesVerified": csv_sha == request["csvSha256"] and csv_bytes == request["csvBytes"],
            "nativeGodotImportVerified": native_passed,
            "runtimePluralLookupVerified": runtime_passed,
            "targetGitStateUnchanged": git_unchanged,
            "targetRepositoryMutationAuthority": False,
            "repairAuthority": False,
            "publicationAuthority": False,
        },
    )
    report_path = artifact_root / "plural-localization-report.json"
    report_path.write_text(final_report.to_json() + "\n", encoding="utf-8")
    final_report.artifacts.append(str(report_path))
    report_path.write_text(final_report.to_json() + "\n", encoding="utf-8")
    return final_report
