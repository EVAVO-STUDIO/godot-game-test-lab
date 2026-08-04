#!/usr/bin/env python3
"""Fail closed when the Brass audio-analysis verification authority drifts."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import py_compile
import sys
import tempfile
import tomllib

ROOT = Path.cwd().resolve(strict=True)
MAXIMUM_SOURCE_BYTES = 1_000_000
FILES = {
    "core": "src/godot_game_test_lab/audio_analysis.py",
    "mcp": "src/godot_game_test_lab/audio_analysis_mcp.py",
    "tests": "tests/test_audio_analysis.py",
    "mcpTests": "tests/test_audio_analysis_mcp.py",
    "docs": "docs/BRASS_BRINE_AUDIO_ANALYSIS.md",
    "pyproject": "pyproject.toml",
}
ERRORS: list[str] = []


def fail(message: str) -> None:
    ERRORS.append(message)


def read_text(relative: str) -> str:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts:
        raise RuntimeError(f"AUDIO_ANALYSIS_SOURCE_PATH_INVALID:{relative}")
    candidate = ROOT.joinpath(*pure.parts)
    if not candidate.is_file() or candidate.is_symlink():
        raise RuntimeError(f"AUDIO_ANALYSIS_SOURCE_FILE_INVALID:{relative}")
    if candidate.resolve(strict=True) != candidate.absolute():
        raise RuntimeError(f"AUDIO_ANALYSIS_SOURCE_FILE_NONCANONICAL:{relative}")
    if candidate.stat().st_size > MAXIMUM_SOURCE_BYTES:
        raise RuntimeError(f"AUDIO_ANALYSIS_SOURCE_FILE_TOO_LARGE:{relative}")
    source = candidate.read_text(encoding="utf-8")
    if source.startswith("\ufeff"):
        raise RuntimeError(f"AUDIO_ANALYSIS_SOURCE_FILE_BOM:{relative}")
    return source


def require_tokens(label: str, source: str, tokens: tuple[str, ...]) -> None:
    for token in tokens:
        if token not in source:
            fail(f"{label} is missing required token: {token}")


def forbid_tokens(label: str, source: str, tokens: tuple[str, ...]) -> None:
    for token in tokens:
        if token in source:
            fail(f"{label} contains prohibited material: {token}")


def compile_sources() -> None:
    with tempfile.TemporaryDirectory(prefix="godot-lab-audio-compile-") as value:
        cache = Path(value)
        for index, key in enumerate(("core", "mcp", "tests", "mcpTests")):
            source = ROOT.joinpath(*PurePosixPath(FILES[key]).parts)
            try:
                py_compile.compile(
                    str(source),
                    cfile=str(cache / f"{index}.pyc"),
                    doraise=True,
                )
            except py_compile.PyCompileError as error:
                fail(f"{FILES[key]} does not compile: {error.msg}")


def main() -> int:
    try:
        sources = {name: read_text(path) for name, path in FILES.items()}
    except (OSError, UnicodeError, RuntimeError) as error:
        print(f"Brass audio-analysis toolchain check failed: {error}", file=sys.stderr)
        return 1

    try:
        pyproject = tomllib.loads(sources["pyproject"])
    except tomllib.TOMLDecodeError:
        fail("pyproject.toml must remain valid TOML")
        pyproject = {}
    per_file = (
        pyproject.get("tool", {})
        .get("ruff", {})
        .get("lint", {})
        .get("per-file-ignores", {})
    )
    if any("audio_analysis" in path for path in per_file):
        fail("Brass audio-analysis source may not use a Ruff per-file exemption")

    require_tokens(
        "audio-analysis core",
        sources["core"],
        (
            'CONTRACT_ID = "evavo_brass_brine_audio_production_contract_v1"',
            'SELECTION_ID = "evavo_brass_brine_audio_selection_v1"',
            'INVENTORY_ID = "evavo_brass_brine_audio_inventory_v1"',
            'ANALYSIS_ID = "evavo_brass_brine_audio_analysis_report_v1"',
            'REPORT_ID = "evavo_brass_brine_audio_test_lab_report_v1"',
            "duplicate JSON property",
            "negative zero is not accepted",
            "Brass & Brine repository state changed during Test Lab validation",
            "Audio Studio analyzedPaths do not equal the selected audio paths",
            "current-runtime-identity-mismatch",
            "analysis-source-sha256-mismatch",
            "analysis-runtime-sha256-mismatch",
            'f"independent-{key}-mismatch"',
            "independent-duration-mismatch",
            "godot-wav-pcm-import-required",
            "loop-boundary-delta-exceeded",
            "wave.open",
            'shutil.which("ffprobe")',
            '"finalIdentityRecheck": True',
            '"mutationPerformed": False',
            '"publicationAuthority": False',
            '"humanListeningApproval": False',
            '"godotGameplayMixApproval": False',
            '"provenanceApproval": False',
            'target.open("xb")',
        ),
    )
    forbid_tokens(
        "audio-analysis core",
        sources["core"],
        (
            "shell=True",
            "shell: true",
            'add_argument("--ffprobe"',
            'add_argument("--ffmpeg"',
            "git push",
            "git commit",
            "git reset",
            "unlink(",
            "rmtree(",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
        ),
    )
    require_tokens(
        "audio-analysis MCP",
        sources["mcp"],
        (
            "AudioAnalysisMcpConfig",
            "EVAVO_GODOT_LAB_ALLOWED_ROOTS",
            "EVAVO_GODOT_AUDIO_CONTRACT_ROOTS",
            "EVAVO_GODOT_LAB_EVIDENCE_ROOT",
            "godot_audio_analysis_capabilities",
            "godot_validate_audio_analysis",
            '"arbitraryShellAllowed": False',
            '"arbitraryGitArgumentsAllowed": False',
            '"arbitraryExecutablePathsAllowed": False',
            "Streamable HTTP is restricted to an explicit loopback host",
            "write_report",
        ),
    )
    forbid_tokens(
        "audio-analysis MCP",
        sources["mcp"],
        (
            "shell=True",
            "git push",
            "git commit",
            "--ffprobe",
            "--ffmpeg",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
        ),
    )
    require_tokens(
        "audio-analysis tests",
        sources["tests"],
        (
            "test_exact_audio_evidence_passes_independent_validation",
            "test_current_runtime_drift_fails_before_admission",
            "test_generic_passed_document_is_rejected",
            "test_duplicate_json_properties_are_rejected",
            "test_selected_path_omission_fails_closed",
            "test_create_only_report_output_is_root_restricted",
        ),
    )
    require_tokens(
        "audio-analysis MCP tests",
        sources["mcpTests"],
        (
            "test_capability_document_retains_no_effect_authority",
            "test_root_resolution_is_fail_closed",
            "test_evidence_root_must_be_disjoint_from_sources",
        ),
    )
    require_tokens(
        "audio-analysis documentation",
        sources["docs"],
        (
            "evavo_brass_brine_audio_test_lab_report_v1",
            "duplicate-key-safe",
            "independent WAV metadata",
            "fixed system `ffprobe`",
            "godot_audio_analysis_capabilities",
            "godot_validate_audio_analysis",
            "human listening approval",
            "Development Studio",
        ),
    )
    if len(sources["core"].encode("utf-8")) > 64_000:
        fail("audio-analysis core exceeds the bounded 64 KiB source limit")
    if len(sources["mcp"].encode("utf-8")) > 32_000:
        fail("audio-analysis MCP exceeds the bounded 32 KiB source limit")

    compile_sources()
    if ERRORS:
        print("Brass audio-analysis toolchain check failed:", file=sys.stderr)
        print(file=sys.stderr)
        for error in ERRORS:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Brass audio-analysis toolchain check passed.")
    print("- exact Audio Studio identities and selected paths remain fail-closed")
    print("- current runtime bytes, Godot imports and metadata are independently checked")
    print("- MCP, report output, listening and publication boundaries remain separate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
