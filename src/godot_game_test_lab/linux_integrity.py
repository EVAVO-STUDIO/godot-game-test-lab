from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .integrity import IntegrityReport, audit_project, execution_blocking_findings

_CHECK_ID = "static-project-integrity"
_MAX_SUMMARY_FINDINGS = 100
_MAX_REPORT_BYTES = 64 * 1024 * 1024


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.is_symlink():
        raise OSError(f"refusing to replace symbolic-link report path: {path}")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        if path.is_symlink() or not path.is_file():
            return {}
        if path.stat().st_size > _MAX_REPORT_BYTES:
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _safe_project_root(source_root: Path, project_subpath: str) -> Path:
    root = source_root.expanduser().resolve()
    normalized = project_subpath.strip().replace("\\", "/")
    if normalized in ("", "."):
        relative = Path(".")
    else:
        relative = Path(normalized)
        windows_drive = (
            len(normalized) >= 3
            and normalized[0].isalpha()
            and normalized[1:3] == ":/"
        )
        if (
            windows_drive
            or relative.is_absolute()
            or any(part in ("", ".", "..") for part in relative.parts)
        ):
            raise ValueError(
                "project_subpath must be a canonical relative path without traversal"
            )
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("project_subpath escapes the source root") from exc
    if not candidate.is_dir() or not (candidate / "project.godot").is_file():
        raise FileNotFoundError(
            f"project.godot is missing at the declared project_subpath: {project_subpath}"
        )
    return candidate


def _condensed_findings(
    report: IntegrityReport,
    *,
    include_warnings: bool,
) -> list[str]:
    output: list[str] = []
    for finding in report.findings:
        if finding.severity != "error" and not include_warnings:
            continue
        location = finding.path or "project"
        if finding.line is not None:
            location = f"{location}:{finding.line}"
        output.append(
            f"{_CHECK_ID}: {finding.severity}: {finding.code}: "
            f"{location}: {finding.message}"
        )
        if len(output) >= _MAX_SUMMARY_FINDINGS:
            break
    omitted = sum(
        1
        for finding in report.findings
        if finding.severity == "error" or include_warnings
    ) - len(output)
    if omitted > 0:
        output.append(f"{_CHECK_ID}: {omitted} additional finding(s) are in integrity-report.json")
    if report.findings_truncated:
        output.append(
            f"{_CHECK_ID}: the bounded finding limit was reached; the audit is incomplete"
        )
    return output


def _integrity_check(gate: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _CHECK_ID,
        "status": gate.get("status", "blocked"),
        "errors": gate.get("errors", 0),
        "warnings": gate.get("warnings", 0),
        "findingsTruncated": bool(gate.get("findingsTruncated", False)),
        "executionAllowed": bool(gate.get("executionAllowed", False)),
        "executionBlockers": list(gate.get("executionBlockers", [])),
        "report": "integrity-report.json",
        "evidence": ["integrity-report.json", "integrity-gate.json"],
        "findings": list(gate.get("summaryFindings", [])),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_inventory(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if (
            path.is_symlink()
            or not path.is_file()
            or path.name == "agent-summary.json"
        ):
            continue
        try:
            size = path.stat().st_size
            digest = _sha256_file(path)
        except OSError:
            continue
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": size,
                "sha256": digest,
            }
        )
    return records


def _fallback_summary(status: str, gate: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": "1.0",
        "status": status,
        "targetRepository": os.environ.get("EVAVO_TARGET_REPOSITORY", ""),
        "targetSha": os.environ.get("EVAVO_TARGET_SHA", ""),
        "labSha": os.environ.get("EVAVO_LAB_SHA", ""),
        "projectSubpath": gate.get("projectSubpath", "."),
        "checks": [],
        "findings": [],
    }


def _merge_check(
    summary: dict[str, Any],
    gate: dict[str, Any],
    *,
    runner_exit_code: int,
) -> dict[str, Any]:
    check = _integrity_check(gate)
    checks = summary.get("checks", [])
    if not isinstance(checks, list):
        checks = []
    checks = [
        value
        for value in checks
        if not (isinstance(value, dict) and value.get("id") == _CHECK_ID)
    ]
    summary["checks"] = [check, *checks]

    existing_findings = summary.get("findings", [])
    if not isinstance(existing_findings, list):
        existing_findings = [str(existing_findings)]
    retained = [
        str(value)
        for value in existing_findings
        if not str(value).startswith(f"{_CHECK_ID}:")
    ]
    if gate.get("status") != "passed":
        retained.extend(str(value) for value in gate.get("summaryFindings", []))
    summary["findings"] = list(dict.fromkeys(retained))

    runner_status = str(summary.get("status", "failed"))
    gate_status = str(gate.get("status", "blocked"))
    if gate_status == "blocked" or runner_status == "blocked":
        status = "blocked"
    elif gate_status != "passed" or runner_exit_code != 0 or runner_status != "passed":
        status = "failed"
    else:
        status = "passed"
    summary["status"] = status
    summary["runnerExitCode"] = runner_exit_code
    summary["integrity"] = {
        "schemaVersion": gate.get("schemaVersion", "1.0"),
        "status": gate_status,
        "errors": gate.get("errors", 0),
        "warnings": gate.get("warnings", 0),
        "warningsAsErrors": bool(gate.get("warningsAsErrors", False)),
        "executionAllowed": bool(gate.get("executionAllowed", False)),
        "executionBlockers": list(gate.get("executionBlockers", [])),
        "report": "integrity-report.json",
        "gate": "integrity-gate.json",
        "sampleFindings": list(gate.get("sampleFindings", [])),
        "truthBoundary": (
            "Static inspection diagnoses source and materialization defects; the matching "
            "Godot editor import remains authoritative for engine parsing and import behavior."
        ),
    }
    return summary


def _merge_sandbox_report(artifacts_root: Path, gate: dict[str, Any]) -> None:
    path = artifacts_root / "sandbox-report.json"
    report = _read_json_object(path)
    if not report:
        return
    findings = report.get("findings", [])
    if not isinstance(findings, list):
        findings = [str(findings)]
    findings = [
        str(value)
        for value in findings
        if not str(value).startswith(f"{_CHECK_ID}:")
    ]
    if gate.get("status") != "passed":
        findings.extend(str(value) for value in gate.get("summaryFindings", []))
    report["findings"] = list(dict.fromkeys(findings))

    artifacts = report.get("artifacts", [])
    if not isinstance(artifacts, list):
        artifacts = []
    report["artifacts"] = list(
        dict.fromkeys([*map(str, artifacts), "integrity-report.json", "integrity-gate.json"])
    )
    report["integrity"] = {
        "schemaVersion": gate.get("schemaVersion", "1.0"),
        "status": gate.get("status", "blocked"),
        "errors": gate.get("errors", 0),
        "warnings": gate.get("warnings", 0),
        "warningsAsErrors": bool(gate.get("warningsAsErrors", False)),
        "executionAllowed": bool(gate.get("executionAllowed", False)),
        "executionBlockers": list(gate.get("executionBlockers", [])),
        "report": "integrity-report.json",
        "gate": "integrity-gate.json",
    }
    if gate.get("status") == "blocked":
        report["status"] = "blocked"
    elif gate.get("status") != "passed" and report.get("status") == "passed":
        report["status"] = "failed"
    _write_json(path, report)


def write_integrity_preflight_failure(
    artifacts_root: Path,
    *,
    project_subpath: str,
    error: Exception | str,
    warnings_as_errors: bool = False,
) -> dict[str, Any]:
    artifacts = artifacts_root.expanduser().resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    message = (
        f"{_CHECK_ID}: preflight could not establish safe project integrity: {error}"
    )
    gate: dict[str, Any] = {
        "schemaVersion": "1.0",
        "status": "blocked",
        "projectSubpath": project_subpath,
        "errors": 1,
        "warnings": 0,
        "warningsAsErrors": warnings_as_errors,
        "findingsTruncated": False,
        "executionAllowed": False,
        "executionBlockers": ["integrity.preflight_failed"],
        "summaryFindings": [message],
        "sampleFindings": [message],
        "evidence": ["integrity-gate.json"],
    }
    _write_json(artifacts / "integrity-gate.json", gate)
    summary = _merge_check(_fallback_summary("blocked", gate), gate, runner_exit_code=2)
    summary["artifacts"] = _artifact_inventory(artifacts)
    _write_json(artifacts / "agent-summary.json", summary)
    return gate


def run_integrity_preflight(
    source_root: Path,
    *,
    project_subpath: str,
    artifacts_root: Path,
    warnings_as_errors: bool = False,
) -> dict[str, Any]:
    artifacts = artifacts_root.expanduser().resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    try:
        project_root = _safe_project_root(source_root, project_subpath)
        report = audit_project(project_root)
        _write_json(artifacts / "integrity-report.json", report.to_dict())
        blockers = sorted({finding.code for finding in execution_blocking_findings(report)})
        if report.findings_truncated and "limits.findings_truncated" not in blockers:
            blockers.append("limits.findings_truncated")
        policy_failed = report.errors > 0 or (warnings_as_errors and report.warnings > 0)
        status = "blocked" if blockers else "failed" if policy_failed else "passed"
        sample_findings = _condensed_findings(report, include_warnings=True)
        summary_findings = _condensed_findings(
            report,
            include_warnings=warnings_as_errors,
        )
        gate: dict[str, Any] = {
            "schemaVersion": "1.0",
            "status": status,
            "projectSubpath": project_subpath,
            "projectRoot": report.project_root,
            "errors": report.errors,
            "warnings": report.warnings,
            "warningsAsErrors": warnings_as_errors,
            "findingsTruncated": report.findings_truncated,
            "executionAllowed": not blockers,
            "executionBlockers": blockers,
            "summaryFindings": summary_findings,
            "sampleFindings": sample_findings,
            "evidence": ["integrity-report.json", "integrity-gate.json"],
        }
    except (FileNotFoundError, OSError, UnicodeError, ValueError) as error:
        return write_integrity_preflight_failure(
            artifacts,
            project_subpath=project_subpath,
            error=error,
            warnings_as_errors=warnings_as_errors,
        )
    _write_json(artifacts / "integrity-gate.json", gate)
    if gate["status"] == "blocked":
        summary = _merge_check(_fallback_summary("blocked", gate), gate, runner_exit_code=2)
        summary["artifacts"] = _artifact_inventory(artifacts)
        _write_json(artifacts / "agent-summary.json", summary)
    return gate


def merge_integrity_evidence(
    artifacts_root: Path,
    *,
    runner_exit_code: int,
) -> dict[str, Any]:
    artifacts = artifacts_root.expanduser().resolve()
    gate = _read_json_object(artifacts / "integrity-gate.json")
    if not gate:
        gate = {
            "schemaVersion": "1.0",
            "status": "blocked",
            "projectSubpath": ".",
            "errors": 1,
            "warnings": 0,
            "warningsAsErrors": False,
            "findingsTruncated": False,
            "executionAllowed": False,
            "executionBlockers": ["integrity.gate_missing"],
            "summaryFindings": [
                f"{_CHECK_ID}: integrity-gate.json is missing or invalid"
            ],
            "sampleFindings": [
                f"{_CHECK_ID}: integrity-gate.json is missing or invalid"
            ],
        }
    summary_path = artifacts / "agent-summary.json"
    summary = _read_json_object(summary_path)
    if not summary:
        summary = _fallback_summary(
            "passed" if runner_exit_code == 0 else "failed",
            gate,
        )
    summary = _merge_check(summary, gate, runner_exit_code=runner_exit_code)
    _merge_sandbox_report(artifacts, gate)
    summary["artifacts"] = _artifact_inventory(artifacts)
    _write_json(summary_path, summary)
    return summary
