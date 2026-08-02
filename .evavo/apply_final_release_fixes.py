from __future__ import annotations

import os
from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    source = path.read_text(encoding="utf-8")
    if source.count(old) != 1:
        raise SystemExit(f"{label} anchor count changed: {source.count(old)}")
    path.write_text(source.replace(old, new), encoding="utf-8", newline="\n")


def main() -> int:
    stage = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True) / "final-source-tree"
    if stage.is_symlink() or not stage.is_dir():
        raise SystemExit(f"final source staging directory is missing or unsafe: {stage}")

    checker = stage / "scripts/check_repository_toolchain.py"
    replace_once(
        checker,
        '    require_tokens(\n'
        '        "scripts/Install-GodotLab.ps1",\n'
        '        (\n'
        '            "engine bootstrap",\n',
        '    require_tokens(\n'
        '        "scripts/Install-GodotLab.ps1",\n'
        '        (\n'
        '            \'"engine", "bootstrap"\',\n',
        "Windows installer bootstrap token",
    )
    core = stage / "scripts/check_repository_toolchain_core.py"
    core.write_text(checker.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")

    wrapper = '''#!/usr/bin/env python3
"""Preflight the immutable workflow boundary, then run the toolchain core."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

ROOT = Path.cwd().resolve(strict=True)
CORE_PATH = ROOT / "scripts" / "check_repository_toolchain_core.py"
EXPECTED_WORKFLOWS = {
    "ci.yml",
    "evavo-linux-godot-sandbox.yml",
    "evavo-mainline-confirmation.yml",
    "evavo-native-godot-validation.yml",
    "linux-sandbox-smoke.yml",
    "reusable-godot-linux-sandbox.yml",
}
FORBIDDEN_STAGING_PATHS = (
    ".evavo/bootstrap",
    ".evavo/agent-audio-upgrade-diagnostic.txt",
    ".evavo/managed-sandbox-0.7-diagnostic.txt",
    ".github/workflows/apply-agent-audio-upgrade.yml",
    ".github/workflows/apply-managed-sandbox-0.7.yml",
    ".github/workflows/dispatch-agent-audio-upgrade.yml",
    "scripts/apply_agent_audio_upgrade.py",
)


def _preflight_errors() -> list[str]:
    errors: list[str] = []
    workflow_root = ROOT / ".github" / "workflows"
    try:
        observed = {
            path.name
            for path in workflow_root.iterdir()
            if path.is_file() and not path.is_symlink() and path.suffix in {".yml", ".yaml"}
        }
    except OSError as error:
        return [f"workflow inventory could not be read: {error}"]
    if observed != EXPECTED_WORKFLOWS:
        errors.append(
            "workflow inventory changed; "
            f"missing={sorted(EXPECTED_WORKFLOWS - observed)} "
            f"extra={sorted(observed - EXPECTED_WORKFLOWS)}"
        )

    for relative in FORBIDDEN_STAGING_PATHS:
        path = ROOT.joinpath(*Path(relative).parts)
        if path.exists() or path.is_symlink():
            errors.append(f"one-time publication residue remains: {relative}")

    if CORE_PATH.is_symlink() or not CORE_PATH.is_file():
        errors.append("toolchain core must be a regular file")
    else:
        try:
            if CORE_PATH.resolve(strict=True) != CORE_PATH.absolute():
                errors.append("toolchain core path must be canonical")
            elif CORE_PATH.stat().st_size > 4_000_000:
                errors.append("toolchain core exceeds the bounded source limit")
            else:
                source = CORE_PATH.read_text(encoding="utf-8")
                if source.startswith(chr(0xFEFF)):
                    errors.append("toolchain core contains a UTF-8 BOM")
                if "def main() -> int:" not in source:
                    errors.append("toolchain core does not expose its expected entrypoint")
        except (OSError, UnicodeError) as error:
            errors.append(f"toolchain core could not be validated: {error}")
    return errors


def main() -> int:
    errors = _preflight_errors()
    if errors:
        print("Godot lab toolchain preflight failed:", file=sys.stderr)
        print(file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    namespace = runpy.run_path(str(CORE_PATH), run_name="godot_toolchain_core")
    core_main = namespace.get("main")
    if not callable(core_main):
        raise RuntimeError("toolchain core does not expose callable main")
    result = core_main()
    if not isinstance(result, int):
        raise RuntimeError("toolchain core main must return an integer exit code")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
'''
    checker.write_text(wrapper, encoding="utf-8", newline="\n")

    replace_once(
        stage / "scripts/test_repository_toolchain.py",
        '    "schemas/repository-owned-reliability-profile.schema.json",\n'
        '    "scripts/check_repository_toolchain.py",\n'
        '    "src/godot_game_test_lab/__init__.py",\n',
        '    "schemas/repository-owned-reliability-profile.schema.json",\n'
        '    "scripts/check_repository_toolchain.py",\n'
        '    "scripts/check_repository_toolchain_core.py",\n'
        '    "src/godot_game_test_lab/__init__.py",\n',
        "adversarial fixture core inventory",
    )

    stale_core_test = stage / "scripts/test_repository_toolchain_core.py"
    if stale_core_test.exists() or stale_core_test.is_symlink():
        stale_core_test.unlink()

    linux_test = stage / "tests/test_linux_sandbox_contract.py"
    source = linux_test.read_text(encoding="utf-8")
    source = source.replace("from pathlib import Path\n", "import json\nfrom pathlib import Path\n", 1)
    source = source.replace(
        '    assert "GODOT_VERSION=4.6.2" in dockerfile\n',
        '    assert "ARG GODOT_VERSION=4.6.3" in dockerfile\n'
        '    engine_lock = json.loads(_read("src/godot_game_test_lab/godot-engine-lock.json"))\n'
        '    assert engine_lock["minimumVersion"] == "4.6.2"\n'
        '    assert engine_lock["defaultVersion"] == "4.6.3"\n',
        1,
    )
    source = source.replace(
        '    assert "sha512sum --check" in dockerfile\n',
        '    assert "digest = hashlib.sha512()" in dockerfile\n'
        '    assert "SHA-512 mismatch" in dockerfile\n',
        1,
    )
    linux_test.write_text(source, encoding="utf-8", newline="\n")

    replace_once(
        stage / "tests/test_native_workflow_policy.py",
        "pip install --disable-pip-version-check -e '.[dev]'",
        "pip install --disable-pip-version-check -e '.[dev,agent]'",
        "native workflow dependency assertion",
    )

    replace_once(
        stage / "src/godot_game_test_lab/dotnet_manager.py",
        '                raise DotNetProvisionError(f"Timed out waiting for .NET install lock: {path}")\n',
        '                raise DotNetProvisionError(\n'
        '                    f"Timed out waiting for .NET install lock: {path}"\n'
        '                ) from None\n',
        ".NET lock timeout exception chain",
    )
    replace_once(
        stage / "src/godot_game_test_lab/engine_manager.py",
        '                raise EngineProvisionError(\n'
        '                    f"Timed out waiting for engine installation lock: {path}"\n'
        '                )\n',
        '                raise EngineProvisionError(\n'
        '                    f"Timed out waiting for engine installation lock: {path}"\n'
        '                ) from None\n',
        "Godot lock timeout exception chain",
    )
    workflow_test = stage / "tests/test_workflow_inventory.py"
    replace_once(
        workflow_test,
        '    spec = importlib.util.spec_from_file_location("workflow_guarded_toolchain_checker", CHECKER_PATH)\n',
        '    spec = importlib.util.spec_from_file_location(\n'
        '        "workflow_guarded_toolchain_checker", CHECKER_PATH\n'
        '    )\n',
        "workflow checker import line",
    )
    replace_once(
        workflow_test,
        'def test_checker_main_returns_core_result_without_nested_system_exit(monkeypatch: pytest.MonkeyPatch) -> None:\n',
        'def test_checker_main_returns_core_result_without_nested_system_exit(\n'
        '    monkeypatch: pytest.MonkeyPatch,\n'
        ') -> None:\n',
        "workflow checker regression signature",
    )

    replace_once(
        stage / "scripts/Build-GodotLabSandboxes.ps1",
        '        throw "$Command failed with exit code $LASTEXITCODE: $($Arguments -join \' \')"\n',
        '        throw "$Command failed with exit code ${LASTEXITCODE}: $($Arguments -join \' \')"\n',
        "sandbox image builder PowerShell interpolation",
    )
    sandbox_wrapper = stage / "scripts/Invoke-GodotLabSandbox.ps1"
    replace_once(
        sandbox_wrapper,
        '        throw "$Command failed with exit code $LASTEXITCODE: $($Arguments -join \' \')"\n',
        '        throw "$Command failed with exit code ${LASTEXITCODE}: $($Arguments -join \' \')"\n',
        "sandbox runner PowerShell exit-code interpolation",
    )
    replace_once(
        sandbox_wrapper,
        '        throw "Git command failed in $Root: $($Arguments -join \' \')"\n',
        '        throw "Git command failed in ${Root}: $($Arguments -join \' \')"\n',
        "sandbox runner PowerShell path interpolation",
    )
    powershell_test = stage / "tests/test_powershell_contract.py"
    if powershell_test.exists() or powershell_test.is_symlink():
        raise SystemExit("PowerShell interpolation regression test path already exists")
    powershell_test.write_text(
        '''from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AMBIGUOUS_VARIABLE_COLON = re.compile(r"(?<!\\{)\\$([A-Za-z_][A-Za-z0-9_]*):")
POWERSHELL_SCOPES = {
    "alias",
    "env",
    "function",
    "global",
    "local",
    "private",
    "script",
    "using",
    "variable",
}


def test_powershell_strings_do_not_use_ambiguous_variable_colons() -> None:
    findings: list[str] = []
    for path in sorted((ROOT / "scripts").glob("*.ps1")):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in AMBIGUOUS_VARIABLE_COLON.finditer(line):
                if match.group(1).casefold() in POWERSHELL_SCOPES:
                    continue
                findings.append(f"{path.name}:{line_number}: ${match.group(1)}:")
    assert findings == []
''',
        encoding="utf-8",
        newline="\n",
    )

    linux_sandbox = stage / "src/godot_game_test_lab/linux_sandbox.py"
    replace_once(
        linux_sandbox,
        '_EXCLUDED_NAMES = frozenset({".git", ".godot", ".qa", ".cache", "artifacts"})\n',
        '_EXCLUDED_NAMES = frozenset(\n'
        '    {\n'
        '        ".git",\n'
        '        ".godot",\n'
        '        ".qa",\n'
        '        ".cache",\n'
        '        ".mypy_cache",\n'
        '        ".nox",\n'
        '        ".pytest_cache",\n'
        '        ".ruff_cache",\n'
        '        ".tox",\n'
        '        ".venv",\n'
        '        "__pycache__",\n'
        '        "artifacts",\n'
        '    }\n'
        ')\n'
        '_EXCLUDED_SUFFIXES = (".egg-info", ".pyc", ".pyo")\n',
        "Linux sandbox transient copy exclusions",
    )
    replace_once(
        linux_sandbox,
        '    def ignore(_directory: str, names: list[str]) -> set[str]:\n'
        '        return {name for name in names if name in _EXCLUDED_NAMES}\n',
        '    def ignore(_directory: str, names: list[str]) -> set[str]:\n'
        '        return {\n'
        '            name\n'
        '            for name in names\n'
        '            if name in _EXCLUDED_NAMES or name.endswith(_EXCLUDED_SUFFIXES)\n'
        '        }\n',
        "Linux sandbox transient copy filter",
    )

    sandbox_copy_test = stage / "tests/test_linux_sandbox_transient_copy.py"
    if sandbox_copy_test.exists() or sandbox_copy_test.is_symlink():
        raise SystemExit("Linux sandbox transient-copy regression test path already exists")
    sandbox_copy_test.write_text(
        '''from __future__ import annotations

from pathlib import Path

from godot_game_test_lab.linux_sandbox import prepare_ephemeral_copy


def test_ephemeral_copy_skips_unreadable_transient_tool_caches(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "project.godot").write_text(
        '[application]\\nconfig/name="Fixture"\\n',
        encoding="utf-8",
    )
    (source / "keep.txt").write_text("keep", encoding="utf-8")

    transient_directories = (
        ".mypy_cache",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
    )
    for name in transient_directories:
        directory = source / name
        directory.mkdir()
        (directory / "ignored.txt").write_text("ignored", encoding="utf-8")

    unreadable = source / ".ruff_cache" / "private-cache-entry"
    unreadable.write_text("private", encoding="utf-8")
    unreadable.chmod(0)
    (source / "stale.pyc").write_bytes(b"compiled")
    egg_info = source / "fixture.egg-info"
    egg_info.mkdir()
    (egg_info / "PKG-INFO").write_text("generated", encoding="utf-8")

    destination = prepare_ephemeral_copy(source, tmp_path / "work")

    assert (destination / "keep.txt").read_text(encoding="utf-8") == "keep"
    for name in transient_directories:
        assert not (destination / name).exists()
    assert not (destination / "stale.pyc").exists()
    assert not (destination / "fixture.egg-info").exists()
''',
        encoding="utf-8",
        newline="\n",
    )

    temporary = stage / ".evavo/apply_final_release_fixes.py"
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    print("applied final 0.7 release integration fixes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
