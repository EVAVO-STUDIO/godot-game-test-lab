from __future__ import annotations

from pathlib import Path

import pytest

from godot_game_test_lab.localization_plural_runtime import (
    run_plural_localization_runtime_validation,
)


def test_runtime_facade_rejects_symlinked_godot_cache(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "project.godot").write_text(
        '[application]\nconfig/name="Fixture"\n', encoding="utf-8"
    )
    external = tmp_path / "external-cache"
    external.mkdir()
    try:
        (project / ".godot").symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("Symbolic links are not available in this test environment.")
    with pytest.raises(ValueError, match=r"\.godot may not be a symbolic link"):
        run_plural_localization_runtime_validation(
            project,
            {},
            artifacts_root=tmp_path / "artifacts",
        )
