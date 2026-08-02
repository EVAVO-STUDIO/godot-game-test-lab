from __future__ import annotations

import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "src/godot_game_test_lab/agent_bridge.py"
TEST = ROOT / "tests/test_agent_bridge_root_isolation.py"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label} anchor count changed: {count}")
    return source.replace(old, new, 1)


def main() -> int:
    source = BRIDGE.read_text(encoding="utf-8")
    source = replace_once(
        source,
        '''def _is_within(candidate: Path, parent: Path) -> bool:\n    try:\n        candidate.relative_to(parent)\n        return True\n    except ValueError:\n        return False\n\n\ndef _reject_symlink_components(path: Path, label: str) -> Path:\n''',
        '''def _is_within(candidate: Path, parent: Path) -> bool:\n    try:\n        candidate.relative_to(parent)\n        return True\n    except ValueError:\n        return False\n\n\ndef _paths_overlap(left: Path, right: Path) -> bool:\n    return _is_within(left, right) or _is_within(right, left)\n\n\ndef _require_disjoint_root(\n    candidate: Path,\n    protected_roots: tuple[Path, ...],\n    label: str,\n    protected_label: str,\n) -> None:\n    if any(_paths_overlap(candidate, root) for root in protected_roots):\n        raise NativeQaError(f"{label} must remain disjoint from {protected_label}")\n\n\ndef _reject_symlink_components(path: Path, label: str) -> Path:\n''',
        "root overlap helpers",
    )
    source = replace_once(
        source,
        '''        requested_evidence = _reject_symlink_components(\n            evidence_root or _environment_evidence_root(), "Agent evidence root"\n        )\n        requested_evidence.mkdir(parents=True, exist_ok=True)\n        resolved_evidence = requested_evidence.resolve(strict=True)\n        if not resolved_evidence.is_dir():\n            raise NativeQaError("Agent evidence root must be a regular directory")\n        requested_engine = _reject_symlink_components(\n            engine_root or default_engine_root(), "Managed engine root"\n        )\n        requested_engine.mkdir(parents=True, exist_ok=True)\n        resolved_engine = requested_engine.resolve(strict=True)\n        if not resolved_engine.is_dir():\n            raise NativeQaError("Managed engine root must be a regular directory")\n        if _is_within(resolved_engine, resolved_lab):\n            raise NativeQaError("Managed engine root must remain outside the Lab checkout")\n        if any(_is_within(resolved_engine, root) for root in resolved_roots):\n            raise NativeQaError("Managed engine root must remain outside target roots")\n''',
        '''        requested_evidence = _reject_symlink_components(\n            evidence_root or _environment_evidence_root(), "Agent evidence root"\n        )\n        _require_disjoint_root(\n            requested_evidence,\n            (resolved_lab, *resolved_roots),\n            "Agent evidence root",\n            "the Lab checkout and target roots",\n        )\n        requested_engine = _reject_symlink_components(\n            engine_root or default_engine_root(), "Managed engine root"\n        )\n        _require_disjoint_root(\n            requested_engine,\n            (resolved_lab, *resolved_roots, requested_evidence),\n            "Managed engine root",\n            "the Lab, target, and evidence roots",\n        )\n\n        requested_evidence.mkdir(parents=True, exist_ok=True)\n        resolved_evidence = _reject_symlink_components(\n            requested_evidence, "Agent evidence root"\n        ).resolve(strict=True)\n        if not resolved_evidence.is_dir():\n            raise NativeQaError("Agent evidence root must be a regular directory")\n        requested_engine.mkdir(parents=True, exist_ok=True)\n        resolved_engine = _reject_symlink_components(\n            requested_engine, "Managed engine root"\n        ).resolve(strict=True)\n        if not resolved_engine.is_dir():\n            raise NativeQaError("Managed engine root must be a regular directory")\n\n        _require_disjoint_root(\n            resolved_evidence,\n            (resolved_lab, *resolved_roots),\n            "Agent evidence root",\n            "the Lab checkout and target roots",\n        )\n        _require_disjoint_root(\n            resolved_engine,\n            (resolved_lab, *resolved_roots, resolved_evidence),\n            "Managed engine root",\n            "the Lab, target, and evidence roots",\n        )\n''',
        "bridge root construction",
    )
    source = replace_once(
        source,
        '''                "The bridge can execute only beneath configured target roots.",\n                "Retained evidence is written only beneath the configured evidence root.",\n                "Managed editors are official stable archives verified against SHA512-SUMS.txt.",\n''',
        '''                "The bridge can execute only beneath configured target roots.",\n                "The Lab and selected target Git roots must remain disjoint.",\n                "Evidence and managed engines remain outside all source roots and each other.",\n                "Managed editors are official stable archives verified against SHA512-SUMS.txt.",\n''',
        "bridge capability truth boundaries",
    )
    source = replace_once(
        source,
        '''        if not any(_is_within(git_root, root) for root in self.config.allowed_target_roots):\n            raise NativeQaError("Target Git root is outside the configured allowed roots")\n        if project_subpath and project_subpath.strip() != ".":\n''',
        '''        if not any(_is_within(git_root, root) for root in self.config.allowed_target_roots):\n            raise NativeQaError("Target Git root is outside the configured allowed roots")\n        if _paths_overlap(git_root, self.config.lab_root):\n            raise NativeQaError(\n                "Target Git root must remain disjoint from the Lab checkout"\n            )\n        if project_subpath and project_subpath.strip() != ".":\n''',
        "Lab-as-target rejection",
    )
    BRIDGE.write_text(source, encoding="utf-8", newline="\n")

    if TEST.exists() or TEST.is_symlink():
        raise SystemExit(f"test path already exists: {TEST}")
    TEST.write_text(
        textwrap.dedent(
            '''\
            from __future__ import annotations

            import subprocess
            from pathlib import Path

            import pytest

            from godot_game_test_lab.agent_bridge import BridgeConfig, GodotAgentBridge
            from godot_game_test_lab.native_qa_common import NativeQaError


            def _git_repo(root: Path) -> None:
                root.mkdir(parents=True)
                subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
                subprocess.run(
                    ["git", "config", "user.name", "Fixture"], cwd=root, check=True
                )
                subprocess.run(
                    ["git", "config", "user.email", "fixture@example.com"],
                    cwd=root,
                    check=True,
                )
                (root / "project.godot").write_text(
                    'config_version=5\\n[application]\\nrun/main_scene="res://main.tscn"\\n',
                    encoding="utf-8",
                )
                (root / "main.tscn").write_text(
                    '[gd_scene format=3]\\n[node name="Main" type="Node"]\\n',
                    encoding="utf-8",
                )
                subprocess.run(["git", "add", "."], cwd=root, check=True)
                subprocess.run(
                    ["git", "commit", "-q", "-m", "fixture"], cwd=root, check=True
                )


            def test_evidence_inside_lab_is_rejected_before_any_root_is_created(
                tmp_path: Path,
            ) -> None:
                lab = tmp_path / "lab"
                targets = tmp_path / "targets"
                lab.mkdir()
                targets.mkdir()
                evidence = lab / "evidence"
                engine = tmp_path / "engine"

                with pytest.raises(NativeQaError, match="Agent evidence root"):
                    BridgeConfig.from_environment(
                        lab_root=lab,
                        allowed_target_roots=[targets],
                        evidence_root=evidence,
                        engine_root=engine,
                    )

                assert not evidence.exists()
                assert not engine.exists()


            def test_evidence_parent_of_protected_roots_is_rejected(tmp_path: Path) -> None:
                lab = tmp_path / "estate" / "lab"
                targets = tmp_path / "estate" / "targets"
                lab.mkdir(parents=True)
                targets.mkdir()
                engine = tmp_path / "engine"

                with pytest.raises(NativeQaError, match="Agent evidence root"):
                    BridgeConfig.from_environment(
                        lab_root=lab,
                        allowed_target_roots=[targets],
                        evidence_root=tmp_path / "estate",
                        engine_root=engine,
                    )

                assert not engine.exists()


            def test_engine_inside_evidence_is_rejected_without_side_effects(
                tmp_path: Path,
            ) -> None:
                lab = tmp_path / "lab"
                targets = tmp_path / "targets"
                lab.mkdir()
                targets.mkdir()
                evidence = tmp_path / "evidence"
                engine = evidence / "engines"

                with pytest.raises(NativeQaError, match="Managed engine root"):
                    BridgeConfig.from_environment(
                        lab_root=lab,
                        allowed_target_roots=[targets],
                        evidence_root=evidence,
                        engine_root=engine,
                    )

                assert not evidence.exists()
                assert not engine.exists()


            def test_disjoint_bridge_roots_are_created_and_reported(tmp_path: Path) -> None:
                lab = tmp_path / "lab"
                targets = tmp_path / "targets"
                lab.mkdir()
                targets.mkdir()
                evidence = tmp_path / "evidence"
                engine = tmp_path / "engine"

                config = BridgeConfig.from_environment(
                    lab_root=lab,
                    allowed_target_roots=[targets],
                    evidence_root=evidence,
                    engine_root=engine,
                    require_interactive_desktop=False,
                    auto_provision_engines=False,
                )
                capabilities = GodotAgentBridge(config).capabilities()

                assert evidence.is_dir()
                assert engine.is_dir()
                assert capabilities["evidenceRoot"] == str(evidence.resolve())
                assert capabilities["engineRoot"] == str(engine.resolve())
                assert any(
                    "outside all source roots" in boundary
                    for boundary in capabilities["truthBoundaries"]
                )


            def test_lab_repository_cannot_be_selected_as_target(tmp_path: Path) -> None:
                estate = tmp_path / "estate"
                lab = estate / "godot-game-test-lab"
                _git_repo(lab)
                bridge = GodotAgentBridge(
                    BridgeConfig.from_environment(
                        lab_root=lab,
                        allowed_target_roots=[estate],
                        evidence_root=tmp_path / "evidence",
                        engine_root=tmp_path / "engine",
                        require_interactive_desktop=False,
                        auto_provision_engines=False,
                    )
                )

                with pytest.raises(NativeQaError, match="disjoint from the Lab"):
                    bridge.target_record(str(lab))
            '''
        ),
        encoding="utf-8",
        newline="\n",
    )

    helper = ROOT / ".evavo/apply_bridge_root_isolation.py"
    workflow = ROOT / ".github/workflows/apply-bridge-root-isolation.yml"
    helper.unlink(missing_ok=True)
    workflow.unlink(missing_ok=True)
    print("applied MCP bridge root isolation hardening")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
