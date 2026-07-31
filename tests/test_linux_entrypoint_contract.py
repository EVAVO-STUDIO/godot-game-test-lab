from pathlib import Path


def test_linux_entrypoint_preserves_read_only_mount_guards_and_integrity_wrapper() -> None:
    source = (
        Path(__file__).parents[1] / "scripts" / "linux-sandbox-entrypoint.sh"
    ).read_text(encoding="utf-8")

    assert 'findmnt -T "${source_root}"' in source
    assert 'findmnt -T "${profile_path}"' in source
    assert "run_agent_godot_qa_with_integrity.py" in source
    assert 'exec python3 /opt/godot-lab/scripts/run_agent_godot_qa_with_integrity.py' in source
    assert "run_agent_godot_qa_with_process_exit.py" in source
