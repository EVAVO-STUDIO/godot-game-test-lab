from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from godot_game_test_lab.core import CommandResult
from godot_game_test_lab.localization_plural import (
    GitState,
    _MARKER,
    _normalize_origin,
    _probe_script,
    _request_fingerprint,
    _safe_csv_path,
    load_plural_testlab_request,
    run_plural_localization_validation,
    validate_plural_testlab_request,
)
from godot_game_test_lab.pipeline import PipelineReport, ToolIdentity


def _request(csv_bytes: bytes) -> dict[str, object]:
    request: dict[str, object] = {
        "version": "localization-godot-plural-testlab-request-v1",
        "projectId": "plural-test",
        "repository": "EVAVO-STUDIO/Brass_Brine",
        "exactHead": "a" * 40,
        "csvPath": "localization/plurals.csv",
        "csvSha256": hashlib.sha256(csv_bytes).hexdigest(),
        "csvBytes": len(csv_bytes),
        "csvArtifactManifestSha256": "b" * 64,
        "pluralPlanSha256": "c" * 64,
        "minimumGodotVersion": "4.6",
        "probeReview": {
            "reviewed": True,
            "reviewedBy": "fixture",
            "reviewedAt": "2026-08-19T06:00:00Z",
        },
        "localeProbes": {
            "en": [{"formKey": "one", "n": 1}, {"formKey": "*", "n": 2}],
            "cs": [
                {"formKey": "one", "n": 1},
                {"formKey": "few", "n": 2},
                {"formKey": "*", "n": 5},
            ],
        },
        "runtimeProbes": [
            {
                "messageId": "ui.items",
                "locale": "cs",
                "godotLocale": "cs",
                "singularKey": "ui.items",
                "pluralKey": "ui.items.__plural",
                "context": "",
                "n": 2,
                "expectedFormKey": "few",
                "expectedText": "Máte {count} položky.",
            }
        ],
        "requiredChecks": ["fixture"],
        "downstream": {
            "authorityRepository": "EVAVO-STUDIO/godot-game-test-lab",
            "requiredCapability": "testlab.project.validate-runtime",
        },
        "authority": {
            "requestExecutesGodot": False,
            "requestWritesTarget": False,
            "requestPublishesTarget": False,
            "nativeGodotImportVerified": False,
            "runtimePluralLookupVerified": False,
            "testLabExecutionRequired": True,
        },
    }
    request["sha256"] = _request_fingerprint(request)
    return request


def _command(command: list[str], *, stdout: str = "", stderr: str = "", exit_code: int = 0) -> CommandResult:
    return CommandResult(
        command=command,
        exit_code=exit_code,
        duration_seconds=0.01,
        stdout=stdout,
        stderr=stderr,
        timed_out=False,
    )


def test_request_fingerprint_is_canonical_and_rejects_tampering(tmp_path: Path) -> None:
    csv_bytes = b"keys,?plural,en\nui.items,ui.items.__plural,one\n,,many\n"
    request = _request(csv_bytes)
    validate_plural_testlab_request(request)
    first = request["sha256"]
    reordered = dict(reversed(list(request.items())))
    assert _request_fingerprint(reordered) == first
    reordered["csvBytes"] = int(reordered["csvBytes"]) + 1
    with pytest.raises(ValueError, match="fingerprint is invalid or stale"):
        validate_plural_testlab_request(reordered)

    path = tmp_path / "request.json"
    path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
    assert load_plural_testlab_request(path)["sha256"] == first


def test_supported_git_origin_forms_normalize_to_one_repository_identity() -> None:
    for value in (
        "https://github.com/EVAVO-STUDIO/Brass_Brine.git",
        "https://github.com/EVAVO-STUDIO/Brass_Brine",
        "git@github.com:EVAVO-STUDIO/Brass_Brine.git",
        "ssh://git@github.com/EVAVO-STUDIO/Brass_Brine.git",
    ):
        assert _normalize_origin(value) == "EVAVO-STUDIO/Brass_Brine"
    with pytest.raises(ValueError, match="supported github.com"):
        _normalize_origin("https://example.com/EVAVO-STUDIO/Brass_Brine.git")


def test_csv_path_is_project_relative_real_and_not_symlinked(tmp_path: Path) -> None:
    project = tmp_path / "project"
    target = project / "localization" / "plurals.csv"
    target.parent.mkdir(parents=True)
    target.write_text("keys,en\na,a\n", encoding="utf-8")
    assert _safe_csv_path(project.resolve(), "localization/plurals.csv") == target.resolve()
    for invalid in ("../plurals.csv", "/tmp/plurals.csv", "C:/temp/plurals.csv", "localization//plurals.csv"):
        with pytest.raises(ValueError, match="CSV path"):
            _safe_csv_path(project.resolve(), invalid)


def test_generated_probe_script_uses_plural_aware_translation_and_machine_marker() -> None:
    request = _request(b"keys,en\n")
    script = _probe_script(request)
    assert "TranslationServer.translate_plural" in script
    assert "TranslationServer.set_locale" in script
    assert _MARKER in script
    assert "quit(0 if all_matched else 3)" in script


def test_full_plural_validation_passes_only_with_native_pipeline_probe_and_unchanged_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "repo"
    project.mkdir()
    (project / "project.godot").write_text(
        '[application]\nconfig/name="Fixture"\nrun/main_scene="res://main.tscn"\n',
        encoding="utf-8",
    )
    (project / "main.tscn").write_text(
        '[gd_scene format=3]\n\n[node name="Main" type="Node"]\n',
        encoding="utf-8",
    )
    csv_bytes = "keys,?plural,cs\nui.items,ui.items.__plural,Máte {count} položku.\n,,Máte {count} položky.\n,,Máte {count} položek.\n".encode()
    csv_path = project / "localization" / "plurals.csv"
    csv_path.parent.mkdir()
    csv_path.write_bytes(csv_bytes)
    request = _request(csv_bytes)
    request["csvPath"] = "localization/plurals.csv"
    request["sha256"] = _request_fingerprint(request)

    godot = tmp_path / "godot"
    godot.write_text("fixture", encoding="utf-8")
    git_state = GitState(
        root=str(project.resolve()),
        head="a" * 40,
        origin="EVAVO-STUDIO/Brass_Brine",
        status_porcelain="",
    )
    monkeypatch.setattr(
        "godot_game_test_lab.localization_plural.capture_git_state",
        lambda _root: (git_state, []),
    )
    pipeline = PipelineReport(
        schema_version="1.0",
        run_id="fixture-run",
        generated_at="2026-08-19T06:00:00Z",
        status="passed",
        project=None,  # type: ignore[arg-type]
        workload="godot-gdscript",
        tools=[
            ToolIdentity(
                id="godot",
                executable=str(godot),
                version="4.6.2",
                available=True,
                required=True,
                compatible=True,
            )
        ],
    )
    monkeypatch.setattr(
        "godot_game_test_lab.localization_plural.validate_project_pipeline",
        lambda *_args, **_kwargs: pipeline,
    )

    def fake_write_report_bundle(_report: PipelineReport, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        (root / "report.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(
        "godot_game_test_lab.localization_plural.write_report_bundle",
        fake_write_report_bundle,
    )

    probe_payload = {
        "version": "evavo-godot-plural-probe-v1",
        "status": "passed",
        "results": [
            {
                **request["runtimeProbes"][0],  # type: ignore[index]
                "actualText": "Máte {count} položky.",
                "matched": True,
            }
        ],
    }

    def fake_run_command(command: list[str], _cwd: Path, _timeout: int) -> CommandResult:
        return _command(command, stdout=_MARKER + json.dumps(probe_payload, ensure_ascii=False))

    monkeypatch.setattr(
        "godot_game_test_lab.localization_plural.run_command", fake_run_command
    )

    artifacts = tmp_path / "artifacts"
    report = run_plural_localization_validation(
        project,
        request,
        artifacts_root=artifacts,
    )
    assert report.status == "passed"
    assert report.authority["requestFingerprintVerified"] is True
    assert report.authority["nativeGodotImportVerified"] is True
    assert report.authority["runtimePluralLookupVerified"] is True
    assert report.authority["targetGitStateUnchanged"] is True
    assert report.authority["publicationAuthority"] is False
    assert report.runtime_probes[0].matched is True
    assert (artifacts / "plural-localization-report.json").is_file()
    assert not (project / "plural_probe.gd").exists()


def test_runtime_probe_mismatch_fails_even_when_native_pipeline_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "repo"
    project.mkdir()
    (project / "project.godot").write_text('[application]\nconfig/name="Fixture"\n', encoding="utf-8")
    csv_bytes = b"keys,?plural,cs\nui.items,ui.items.__plural,source\n"
    csv_path = project / "localization" / "plurals.csv"
    csv_path.parent.mkdir()
    csv_path.write_bytes(csv_bytes)
    request = _request(csv_bytes)
    request["sha256"] = _request_fingerprint(request)
    godot = tmp_path / "godot"
    godot.write_text("fixture", encoding="utf-8")
    state = GitState(str(project.resolve()), "a" * 40, "EVAVO-STUDIO/Brass_Brine", "")
    monkeypatch.setattr(
        "godot_game_test_lab.localization_plural.capture_git_state",
        lambda _root: (state, []),
    )
    monkeypatch.setattr(
        "godot_game_test_lab.localization_plural.validate_project_pipeline",
        lambda *_args, **_kwargs: PipelineReport(
            schema_version="1.0",
            run_id="fixture-run",
            generated_at="2026-08-19T06:00:00Z",
            status="passed",
            project=None,  # type: ignore[arg-type]
            workload="godot-gdscript",
            tools=[ToolIdentity("godot", str(godot), "4.6.2", True, True, True)],
        ),
    )
    monkeypatch.setattr(
        "godot_game_test_lab.localization_plural.write_report_bundle",
        lambda _report, root: (root.mkdir(parents=True, exist_ok=True), (root / "report.json").write_text("{}", encoding="utf-8")),
    )
    result_payload = {
        "version": "evavo-godot-plural-probe-v1",
        "status": "failed",
        "results": [
            {
                **request["runtimeProbes"][0],  # type: ignore[index]
                "actualText": "ui.items",
                "matched": False,
            }
        ],
    }
    monkeypatch.setattr(
        "godot_game_test_lab.localization_plural.run_command",
        lambda command, _cwd, _timeout: _command(
            command,
            stdout=_MARKER + json.dumps(result_payload, ensure_ascii=False),
            exit_code=3,
        ),
    )
    report = run_plural_localization_validation(
        project,
        request,
        artifacts_root=tmp_path / "artifacts",
    )
    assert report.status == "failed"
    assert report.authority["nativeGodotImportVerified"] is True
    assert report.authority["runtimePluralLookupVerified"] is False
    assert report.authority["publicationAuthority"] is False


def test_git_state_drift_fails_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "repo"
    project.mkdir()
    (project / "project.godot").write_text('[application]\nconfig/name="Fixture"\n', encoding="utf-8")
    csv_bytes = b"keys,?plural,cs\nui.items,ui.items.__plural,source\n"
    csv_path = project / "localization" / "plurals.csv"
    csv_path.parent.mkdir()
    csv_path.write_bytes(csv_bytes)
    request = _request(csv_bytes)
    request["sha256"] = _request_fingerprint(request)
    godot = tmp_path / "godot"
    godot.write_text("fixture", encoding="utf-8")
    before = GitState(str(project.resolve()), "a" * 40, "EVAVO-STUDIO/Brass_Brine", "")
    after = GitState(str(project.resolve()), "a" * 40, "EVAVO-STUDIO/Brass_Brine", " M tracked.txt")
    states = iter([(before, []), (after, [])])
    monkeypatch.setattr(
        "godot_game_test_lab.localization_plural.capture_git_state",
        lambda _root: next(states),
    )
    monkeypatch.setattr(
        "godot_game_test_lab.localization_plural.validate_project_pipeline",
        lambda *_args, **_kwargs: PipelineReport(
            schema_version="1.0",
            run_id="fixture-run",
            generated_at="2026-08-19T06:00:00Z",
            status="passed",
            project=None,  # type: ignore[arg-type]
            workload="godot-gdscript",
            tools=[ToolIdentity("godot", str(godot), "4.6.2", True, True, True)],
        ),
    )
    monkeypatch.setattr(
        "godot_game_test_lab.localization_plural.write_report_bundle",
        lambda _report, root: (root.mkdir(parents=True, exist_ok=True), (root / "report.json").write_text("{}", encoding="utf-8")),
    )
    result_payload = {
        "version": "evavo-godot-plural-probe-v1",
        "status": "passed",
        "results": [
            {
                **request["runtimeProbes"][0],  # type: ignore[index]
                "actualText": "Máte {count} položky.",
                "matched": True,
            }
        ],
    }
    monkeypatch.setattr(
        "godot_game_test_lab.localization_plural.run_command",
        lambda command, _cwd, _timeout: _command(
            command, stdout=_MARKER + json.dumps(result_payload, ensure_ascii=False)
        ),
    )
    report = run_plural_localization_validation(
        project,
        request,
        artifacts_root=tmp_path / "artifacts",
    )
    assert report.status == "failed"
    assert report.authority["runtimePluralLookupVerified"] is True
    assert report.authority["targetGitStateUnchanged"] is False
    assert any("Git state changed" in finding for finding in report.findings)
