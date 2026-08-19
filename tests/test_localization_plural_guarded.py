from __future__ import annotations

import json
from pathlib import Path

import pytest

from godot_game_test_lab.core import CommandResult
from godot_game_test_lab.localization_plural import GitState, _MARKER, _request_fingerprint
from godot_game_test_lab.localization_plural_safe import (
    _cleanup_transient_probe,
    _transient_probe_path,
    run_plural_localization_validation_safe,
)
from godot_game_test_lab.pipeline import PipelineReport, ToolIdentity


def _command(command: list[str], stdout: str = "", exit_code: int = 0) -> CommandResult:
    return CommandResult(
        command=command,
        exit_code=exit_code,
        duration_seconds=0.01,
        stdout=stdout,
        stderr="",
        timed_out=False,
    )


def _fixture(tmp_path: Path) -> tuple[Path, dict[str, object], Path]:
    project = tmp_path / "repo"
    project.mkdir()
    (project / "project.godot").write_text(
        '[application]\nconfig/name="Fixture"\n', encoding="utf-8"
    )
    csv_bytes = (
        "keys,?plural,cs\n"
        "ui.items,ui.items.__plural,Máte {count} položku.\n"
        ",,Máte {count} položky.\n"
        ",,Máte {count} položek.\n"
    ).encode("utf-8")
    csv_path = project / "localization" / "plurals.csv"
    csv_path.parent.mkdir()
    csv_path.write_bytes(csv_bytes)
    import hashlib

    request: dict[str, object] = {
        "version": "localization-godot-plural-testlab-request-v1",
        "projectId": "guarded-probe",
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
        "localeProbes": {"cs": [{"formKey": "few", "n": 2}]},
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
    godot = tmp_path / "godot"
    godot.write_text("fixture", encoding="utf-8")
    return project, request, godot


def test_transient_probe_is_scoped_to_godot_cache_and_cleanup_removes_it(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    probe = _transient_probe_path(project, "a" * 64)
    assert probe.parent == project / ".godot" / "evavo-test-lab"
    probe.write_text("extends SceneTree\n", encoding="utf-8")
    assert _cleanup_transient_probe(probe) is None
    assert not probe.exists()
    assert not probe.parent.exists()


def test_guarded_executor_uses_in_project_transient_script_but_preserves_external_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, request, godot = _fixture(tmp_path)
    state = GitState(str(project.resolve()), "a" * 40, "EVAVO-STUDIO/Brass_Brine", "")
    monkeypatch.setattr(
        "godot_game_test_lab.localization_plural_safe.capture_git_state",
        lambda _root: (state, []),
    )
    pipeline = PipelineReport(
        schema_version="1.0",
        run_id="fixture",
        generated_at="2026-08-19T06:00:00Z",
        status="passed",
        project=None,  # type: ignore[arg-type]
        workload="godot-gdscript",
        tools=[ToolIdentity("godot", str(godot), "4.6.2", True, True, True)],
    )
    monkeypatch.setattr(
        "godot_game_test_lab.localization_plural_safe.validate_project_pipeline",
        lambda *_args, **_kwargs: pipeline,
    )

    def write_bundle(_report: PipelineReport, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        (root / "report.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(
        "godot_game_test_lab.localization_plural_safe.write_report_bundle", write_bundle
    )
    payload = {
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
    observed: dict[str, list[str]] = {}

    def run_probe(command: list[str], _cwd: Path, _timeout: int) -> CommandResult:
        observed["command"] = command
        script = Path(command[command.index("--script") + 1])
        assert script.is_file()
        assert project.resolve() in script.resolve().parents
        assert ".godot" in script.parts
        assert "--log-file" not in command
        return _command(command, _MARKER + json.dumps(payload, ensure_ascii=False))

    monkeypatch.setattr(
        "godot_game_test_lab.localization_plural_safe.run_command", run_probe
    )
    artifacts = tmp_path / "evidence"
    report = run_plural_localization_validation_safe(
        project, request, artifacts_root=artifacts
    )
    assert report.status == "passed"
    transient_path = Path(observed["command"][observed["command"].index("--script") + 1])
    assert not transient_path.exists()
    assert report.authority["transientProbeRemovedBeforeAcceptance"] is True
    assert (artifacts / "plural-probe" / "plural_probe.gd").is_file()
    assert (artifacts / "plural-probe" / "probe-execution.json").is_file()
    assert not (project / "plural_probe.gd").exists()


def test_guarded_executor_fails_when_transient_cleanup_cannot_be_proven(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, request, godot = _fixture(tmp_path)
    state = GitState(str(project.resolve()), "a" * 40, "EVAVO-STUDIO/Brass_Brine", "")
    monkeypatch.setattr(
        "godot_game_test_lab.localization_plural_safe.capture_git_state",
        lambda _root: (state, []),
    )
    monkeypatch.setattr(
        "godot_game_test_lab.localization_plural_safe.validate_project_pipeline",
        lambda *_args, **_kwargs: PipelineReport(
            schema_version="1.0",
            run_id="fixture",
            generated_at="2026-08-19T06:00:00Z",
            status="passed",
            project=None,  # type: ignore[arg-type]
            workload="godot-gdscript",
            tools=[ToolIdentity("godot", str(godot), "4.6.2", True, True, True)],
        ),
    )
    monkeypatch.setattr(
        "godot_game_test_lab.localization_plural_safe.write_report_bundle",
        lambda _report, root: (
            root.mkdir(parents=True, exist_ok=True),
            (root / "report.json").write_text("{}", encoding="utf-8"),
        ),
    )
    payload = {
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
        "godot_game_test_lab.localization_plural_safe.run_command",
        lambda command, _cwd, _timeout: _command(
            command, _MARKER + json.dumps(payload, ensure_ascii=False)
        ),
    )
    monkeypatch.setattr(
        "godot_game_test_lab.localization_plural_safe._cleanup_transient_probe",
        lambda _path: "synthetic cleanup failure",
    )
    report = run_plural_localization_validation_safe(
        project, request, artifacts_root=tmp_path / "evidence"
    )
    assert report.status == "failed"
    assert "synthetic cleanup failure" in report.findings
    assert report.authority["publicationAuthority"] is False
