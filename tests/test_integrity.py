from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from godot_game_test_lab.integrity import AuditLimits, audit_project


def make_project(root: Path, scene: str | None = None) -> Path:
    root.mkdir()
    (root / "project.godot").write_text(
        'config_version=5\n[application]\n'
        'config/name="Integrity Fixture"\n'
        'run/main_scene="res://main.tscn"\n',
        encoding="utf-8",
    )
    (root / "main.tscn").write_text(
        scene
        or (
            '[gd_scene format=3 uid="uid://mainfixture"]\n\n'
            '[node name="Main" type="Node"]\n'
        ),
        encoding="utf-8",
    )
    return root


def codes(report) -> set[str]:
    return {finding.code for finding in report.findings}


def test_valid_project_passes(tmp_path: Path) -> None:
    project = make_project(tmp_path / "game")

    report = audit_project(project)

    assert report.status == "passed"
    assert report.errors == 0
    assert report.scene_files == 1
    assert report.scanned_files == 2


def test_missing_external_resource_and_reference_are_reported(tmp_path: Path) -> None:
    project = make_project(
        tmp_path / "game",
        '[gd_scene format=3]\n'
        '[ext_resource type="Texture2D" path="res://missing.png" id="1_tex"]\n\n'
        '[node name="Main" type="Node"]\n'
        'metadata/texture = ExtResource("2_unknown")\n',
    )

    report = audit_project(project)

    assert report.status == "failed"
    assert "resource.external_path_missing" in codes(report)
    assert "resource.ext_resource_reference_unresolved" in codes(report)


def test_scene_root_and_duplicate_resource_ids_are_reported(tmp_path: Path) -> None:
    project = make_project(
        tmp_path / "game",
        '[gd_scene format=3]\n'
        '[sub_resource type="Resource" id="same"]\n'
        '[sub_resource type="Resource" id="same"]\n'
        '[node name="One" type="Node"]\n'
        '[node name="Two" type="Node"]\n',
    )

    report = audit_project(project)

    assert "resource.sub_resource_id_duplicate" in codes(report)
    assert "scene.root_count" in codes(report)


def test_merge_markers_and_invalid_json_are_reported(tmp_path: Path) -> None:
    project = make_project(tmp_path / "game")
    (project / "data.json").write_text(
        '<<<<<<< ours\n{"value": 1}\n=======\n{"value": 2}\n>>>>>>> theirs\n',
        encoding="utf-8",
    )

    report = audit_project(project)

    assert "git.conflict_markers" in codes(report)
    assert "json.invalid" in codes(report)


def test_invalid_utf8_and_unmaterialized_lfs_are_reported(tmp_path: Path) -> None:
    project = make_project(tmp_path / "game")
    (project / "broken.gd").write_bytes(b"extends Node\n\xff")
    (project / "sprite.png").write_text(
        "version https://git-lfs.github.com/spec/v1\n"
        "oid sha256:0123456789abcdef\nsize 500\n",
        encoding="utf-8",
    )

    report = audit_project(project)

    assert "text.invalid_utf8" in codes(report)
    assert "git_lfs.pointer_not_materialized" in codes(report)


def test_casefold_collision_and_windows_reserved_name_are_reported(tmp_path: Path) -> None:
    project = make_project(tmp_path / "game")
    (project / "Hero.gd").write_text("extends Node\n", encoding="utf-8")
    (project / "hero.gd").write_text("extends Node\n", encoding="utf-8")
    (project / "CON.txt").write_text("not portable\n", encoding="utf-8")

    report = audit_project(project)

    assert "path.portability_collision" in codes(report)
    assert "path.windows_reserved_name" in codes(report)


def test_main_scene_and_autoload_paths_are_verified(tmp_path: Path) -> None:
    project = make_project(tmp_path / "game")
    (project / "project.godot").write_text(
        'config_version=5\n[application]\nrun/main_scene="res://missing.tscn"\n'
        '[autoload]\nBroken="*res://missing.gd"\n',
        encoding="utf-8",
    )

    report = audit_project(project)

    assert "project.main_scene_missing_file" in codes(report)
    assert "project.autoload_missing" in codes(report)


def test_uid_main_scene_and_duplicate_uid_are_verified(tmp_path: Path) -> None:
    project = make_project(tmp_path / "game")
    (project / "project.godot").write_text(
        'config_version=5\n[application]\nrun/main_scene="uid://sameuid"\n',
        encoding="utf-8",
    )
    (project / "main.tscn").write_text(
        '[gd_scene format=3 uid="uid://sameuid"]\n[node name="Main" type="Node"]\n',
        encoding="utf-8",
    )
    (project / "other.tscn").write_text(
        '[gd_scene format=3 uid="uid://sameuid"]\n[node name="Other" type="Node"]\n',
        encoding="utf-8",
    )

    report = audit_project(project)

    assert "resource.duplicate_uid" in codes(report)
    assert "project.main_scene_uid_unresolved" not in codes(report)


def test_tres_header_root_and_references_are_verified(tmp_path: Path) -> None:
    project = make_project(tmp_path / "game")
    (project / "bad.tres").write_text(
        '[gd_resource type="Resource" format=2]\n'
        '[resource]\n'
        'metadata/value = SubResource("missing")\n',
        encoding="utf-8",
    )

    report = audit_project(project)

    assert "resource.unsupported_format" in codes(report)
    assert "resource.sub_resource_reference_unresolved" in codes(report)


def test_export_presets_are_bounded_and_unique(tmp_path: Path) -> None:
    project = make_project(tmp_path / "game")
    (project / "export_presets.cfg").write_text(
        '[preset.0]\nname="Desktop"\nplatform="Windows Desktop"\n'
        '[preset.1]\nname="Desktop"\n',
        encoding="utf-8",
    )

    report = audit_project(project)

    assert "export.preset_name_duplicate" in codes(report)
    assert "export.preset_platform_missing" in codes(report)


def test_invalid_csproj_xml_is_reported(tmp_path: Path) -> None:
    project = make_project(tmp_path / "game")
    (project / "Game.csproj").write_text("<Project><Broken></Project>\n", encoding="utf-8")

    report = audit_project(project)

    assert "xml.invalid" in codes(report)


def test_tracked_export_credentials_are_reported(tmp_path: Path) -> None:
    project = make_project(tmp_path / "game")
    credentials = project / ".godot" / "export_credentials.cfg"
    credentials.parent.mkdir()
    credentials.write_text('password="secret"\n', encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(["git", "-C", str(project), "add", "-f", "."], check=True)

    report = audit_project(project)

    assert "git.export_credentials_tracked" in codes(report)


def test_bounded_file_limit_fails_closed(tmp_path: Path) -> None:
    project = make_project(tmp_path / "game")
    (project / "extra.gd").write_text("extends Node\n", encoding="utf-8")

    report = audit_project(project, limits=AuditLimits(max_files=2))

    assert report.status == "failed"
    assert "limits.file_count_exceeded" in codes(report)


def test_limit_values_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_files"):
        AuditLimits(max_files=0)


@pytest.mark.skipif(os.name == "nt", reason="Windows symlink creation requires varying privileges")
def test_internal_symlink_is_a_portability_warning_without_following_it(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path / "game")
    target = project / "scripts" / "shared.gd"
    target.parent.mkdir()
    target.write_text("extends Node\n", encoding="utf-8")
    (project / "linked.gd").symlink_to(target.relative_to(project))

    report = audit_project(project)

    assert "filesystem.symlink_present" in codes(report)
    assert "filesystem.symlink_escape" not in codes(report)


@pytest.mark.skipif(os.name == "nt", reason="Windows symlink creation requires varying privileges")
def test_symlink_escape_fails_closed_without_following_it(tmp_path: Path) -> None:
    project = make_project(tmp_path / "game")
    outside = tmp_path / "outside.gd"
    outside.write_text("extends Node\n", encoding="utf-8")
    (project / "linked.gd").symlink_to(outside)

    report = audit_project(project)

    assert "filesystem.symlink_escape" in codes(report)


def test_report_is_json_serializable(tmp_path: Path) -> None:
    project = make_project(tmp_path / "game")
    report = audit_project(project)

    payload = json.loads(report.to_json())

    assert payload["schema_version"] == "1.0"
    assert payload["status"] == "passed"


def test_valid_external_internal_resources_and_connection_pass(tmp_path: Path) -> None:
    project = make_project(
        tmp_path / "game",
        '[gd_scene format=3 uid="uid://validscene"]\n'
        '[ext_resource type="Script" path="res://player.gd" id="1_script"]\n'
        '[sub_resource type="Resource" id="Resource_data"]\n'
        '[node name="Main" type="Node"]\n'
        'script = ExtResource("1_script")\n'
        'metadata/data = SubResource("Resource_data")\n'
        '[node name="Child" type="Node" parent="."]\n'
        '[connection signal="ready" from="." to="Child" method="_on_ready"]\n',
    )
    (project / "player.gd").write_text("extends Node\n", encoding="utf-8")

    report = audit_project(project)

    assert report.status == "passed"
    assert "resource.ext_resource_reference_unresolved" not in codes(report)
    assert "resource.sub_resource_reference_unresolved" not in codes(report)
    assert "scene.connection_fields_missing" not in codes(report)


def test_malformed_scene_header_and_connection_are_reported(tmp_path: Path) -> None:
    project = make_project(
        tmp_path / "game",
        '[gd_scene format=3\n'
        '[node name="Main" type="Node"]\n'
        '[connection signal="ready" from="."]\n',
    )

    report = audit_project(project)

    assert "resource.invalid_header" in codes(report)


def test_missing_connection_fields_are_reported(tmp_path: Path) -> None:
    project = make_project(
        tmp_path / "game",
        '[gd_scene format=3]\n'
        '[node name="Main" type="Node"]\n'
        '[connection signal="ready" from="."]\n',
    )

    report = audit_project(project)

    assert "scene.connection_fields_missing" in codes(report)


def test_project_duplicate_settings_and_sections_are_reported(tmp_path: Path) -> None:
    project = make_project(tmp_path / "game")
    (project / "project.godot").write_text(
        'config_version=5\n'
        '[application]\nrun/main_scene="res://main.tscn"\n'
        'run/main_scene="res://main.tscn"\n'
        '[application]\nconfig/name="Duplicate"\n',
        encoding="utf-8",
    )

    report = audit_project(project)

    assert "project.setting_duplicate" in codes(report)
    assert "project.section_duplicate" in codes(report)


def test_non_finite_json_and_invalid_gltf_are_reported(tmp_path: Path) -> None:
    project = make_project(tmp_path / "game")
    (project / "bad.json").write_text('{"value": NaN}\n', encoding="utf-8")
    (project / "model.gltf").write_text('{broken\n', encoding="utf-8")

    report = audit_project(project)

    assert "json.non_finite_number" in codes(report)
    assert "json.invalid" in codes(report)


def test_binary_asset_signatures_are_checked(tmp_path: Path) -> None:
    project = make_project(tmp_path / "game")
    (project / "broken.png").write_bytes(b"not a png")
    (project / "broken.wav").write_bytes(b"RIFFxxxxNOPE")

    report = audit_project(project)

    signature_findings = [
        finding for finding in report.findings if finding.code == "asset.signature_invalid"
    ]
    assert {finding.path for finding in signature_findings} == {"broken.png", "broken.wav"}


def test_tool_scripts_gdextensions_and_editor_plugins_are_visible(tmp_path: Path) -> None:
    project = make_project(tmp_path / "game")
    addon = project / "addons" / "fixture"
    addon.mkdir(parents=True)
    (addon / "plugin.cfg").write_text('[plugin]\nname="Fixture"\n', encoding="utf-8")
    (addon / "plugin.gd").write_text("@tool\nextends EditorPlugin\n", encoding="utf-8")
    (project / "native.gdextension").write_text(
        '[configuration]\nentry_symbol="fixture_init"\n', encoding="utf-8"
    )
    (project / "project.godot").write_text(
        'config_version=5\n'
        '[application]\nrun/main_scene="res://main.tscn"\n'
        '[editor_plugins]\n'
        'enabled=PackedStringArray("res://addons/fixture/plugin.cfg")\n',
        encoding="utf-8",
    )

    report = audit_project(project)

    assert "execution.tool_script_present" in codes(report)
    assert "execution.gdextension_present" in codes(report)
    assert "execution.editor_plugin_enabled" in codes(report)
    assert "project.editor_plugin_missing" not in codes(report)


def test_main_scene_uid_must_resolve_to_a_scene_not_a_resource(tmp_path: Path) -> None:
    project = make_project(tmp_path / "game")
    (project / "project.godot").write_text(
        'config_version=5\n[application]\nrun/main_scene="uid://resourceonly"\n',
        encoding="utf-8",
    )
    (project / "resource.tres").write_text(
        '[gd_resource type="Resource" format=3 uid="uid://resourceonly"]\n[resource]\n',
        encoding="utf-8",
    )

    report = audit_project(project)

    assert "project.main_scene_uid_unresolved" in codes(report)


def test_findings_limit_sets_truncation_and_fails_closed(tmp_path: Path) -> None:
    project = make_project(tmp_path / "game")
    for index in range(5):
        (project / f"bad-{index}.json").write_text("{", encoding="utf-8")

    report = audit_project(project, limits=AuditLimits(max_findings=2))

    assert report.status == "failed"
    assert report.findings_truncated is True
    assert report.errors >= 1


def test_audit_detects_crlf_text_lfs_pointer_and_invalid_toml(tmp_path: Path) -> None:
    project = make_project(tmp_path / "game")
    (project / "broken.tscn").write_bytes(
        b"version https://git-lfs.github.com/spec/v1\r\n"
        b"oid sha256:0123456789abcdef\r\nsize 123\r\n"
    )
    (project / "broken.toml").write_text("section = [\n", encoding="utf-8")

    report = audit_project(project)
    codes = {finding.code for finding in report.findings}

    assert "git_lfs.pointer_not_materialized" in codes
    assert "toml.invalid" in codes


def test_audit_counts_binary_scene_files(tmp_path: Path) -> None:
    project = make_project(tmp_path / "game")
    (project / "binary.scn").write_bytes(b"RSCCfixture")

    report = audit_project(project)

    assert report.scene_files == 2


def test_findings_include_machine_actionable_category_and_repair_hint(tmp_path: Path) -> None:
    project = make_project(tmp_path / "game")
    (project / "main.tscn").write_text("not a scene\n", encoding="utf-8")

    report = audit_project(project)
    finding = next(item for item in report.findings if item.code == "resource.invalid_header")

    assert finding.category == "resource"
    assert "Godot --import" in finding.suggested_action
