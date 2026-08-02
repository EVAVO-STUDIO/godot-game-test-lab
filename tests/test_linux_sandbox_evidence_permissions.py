from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "scripts" / "linux-sandbox-entrypoint.sh"


def test_sandbox_finalizes_regular_evidence_for_the_host() -> None:
    source = ENTRYPOINT.read_text(encoding="utf-8")

    assert "umask 077" in source
    assert "qa_status=0" in source
    assert "|| qa_status=$?" in source
    assert 'symlink_path=' in source
    assert '-type l -print -quit' in source
    assert '-type d -exec chmod 0755 {} +' in source
    assert '-type f -exec chmod 0644 {} +' in source
    assert 'exit "${qa_status}"' in source
    assert "exec python3" not in source
