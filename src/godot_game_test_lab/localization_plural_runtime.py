from __future__ import annotations

from pathlib import Path
from typing import Any

from .core import find_project_root
from .localization_plural import PluralLocalizationReport
from .localization_plural_safe import run_plural_localization_validation_safe


def run_plural_localization_runtime_validation(
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
    """Canonical plural-localization runtime validation entrypoint.

    This facade performs the path-level cache check before delegating to the guarded executor.
    """

    project_root = find_project_root(candidate).resolve(strict=True)
    godot_cache = project_root / ".godot"
    if godot_cache.exists() and godot_cache.is_symlink():
        raise ValueError("Godot project cache .godot may not be a symbolic link.")
    return run_plural_localization_validation_safe(
        project_root,
        request,
        artifacts_root=artifacts_root,
        godot_executable=godot_executable,
        dotnet_executable=dotnet_executable,
        minimum_godot_version=minimum_godot_version,
        timeout_seconds=timeout_seconds,
        boot_frames=boot_frames,
        warnings_as_errors=warnings_as_errors,
        recovery_diagnostic=recovery_diagnostic,
        allow_major_upgrade=allow_major_upgrade,
    )
