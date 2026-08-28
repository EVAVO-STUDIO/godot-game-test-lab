#!/usr/bin/env python3
"""Compare the canonical Godot web descriptor fixture across local repositories."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LAB_FIXTURE = ROOT / "tests" / "fixtures" / "generated-descriptor.v2.json"
RUNTIME_FIXTURE_RELATIVE = Path(
    "packages/godot-loader/fixtures/generated-descriptor.v2.json"
)
MAX_FIXTURE_BYTES = 256 * 1024
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


class FixtureContractError(RuntimeError):
    """Raised when the cross-repository fixture contract fails closed."""


def _regular_canonical_file(path: Path, label: str) -> Path:
    absolute = path.expanduser().absolute()
    if absolute.is_symlink() or not absolute.is_file():
        raise FixtureContractError(f"{label} must be a regular non-linked file: {absolute}")
    resolved = absolute.resolve(strict=True)
    if resolved != absolute:
        raise FixtureContractError(f"{label} must use its canonical path: {absolute}")
    size = resolved.stat().st_size
    if size < 1 or size > MAX_FIXTURE_BYTES:
        raise FixtureContractError(
            f"{label} must contain 1 to {MAX_FIXTURE_BYTES} bytes: {resolved}"
        )
    return resolved


def _load_canonical_fixture(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    canonical = _regular_canonical_file(path, label)
    raw = canonical.read_bytes()
    try:
        text = raw.decode("utf-8")
        value = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FixtureContractError(f"{label} is not valid UTF-8 JSON: {error}") from error
    if not isinstance(value, dict):
        raise FixtureContractError(f"{label} must contain a JSON object")
    expected = (json.dumps(value, indent=2) + "\n").encode("utf-8")
    if raw != expected:
        raise FixtureContractError(f"{label} is not canonical indented JSON with LF ending")
    _validate_fixture_contract(value, label)
    return raw, value


def _validate_fixture_contract(value: dict[str, Any], label: str) -> None:
    expected_assets = {
        "./contract-fixture.js",
        "./contract-fixture.wasm",
        "./contract-fixture.pck",
    }
    if value.get("schemaVersion") != 2:
        raise FixtureContractError(f"{label} schemaVersion must be 2")
    if value.get("id") != "contract-fixture":
        raise FixtureContractError(f"{label} id must be contract-fixture")
    if value.get("executable") != "contract-fixture":
        raise FixtureContractError(f"{label} executable must be contract-fixture")
    if value.get("renderer") != "compatibility":
        raise FixtureContractError(f"{label} renderer must be compatibility")
    if value.get("webRuntimeProfile") != "threaded":
        raise FixtureContractError(f"{label} must exercise the threaded profile")
    if value.get("ensureCrossOriginIsolationHeaders") is not True:
        raise FixtureContractError(f"{label} must exercise threaded isolation intent")
    if value.get("requiresAgentBridge") is not True:
        raise FixtureContractError(f"{label} must exercise the required bridge boundary")
    if value.get("bridgeTimeoutMs") != 10_000:
        raise FixtureContractError(f"{label} bridgeTimeoutMs must be 10000")

    sizes = value.get("fileSizes")
    integrity = value.get("assetIntegrity")
    if not isinstance(sizes, dict) or set(sizes) != expected_assets:
        raise FixtureContractError(f"{label} fileSizes asset set drifted")
    if not isinstance(integrity, dict) or set(integrity) != expected_assets:
        raise FixtureContractError(f"{label} assetIntegrity asset set drifted")
    if set(sizes.values()) != {0}:
        raise FixtureContractError(f"{label} fixture asset sizes must remain zero")
    if set(integrity.values()) != {EMPTY_SHA256}:
        raise FixtureContractError(f"{label} fixture hashes must bind empty assets")


def compare_fixtures(
    runtime_root: Path,
    *,
    lab_fixture: Path = LAB_FIXTURE,
) -> dict[str, object]:
    runtime_absolute = runtime_root.expanduser().absolute()
    if runtime_absolute.is_symlink() or not runtime_absolute.is_dir():
        raise FixtureContractError(
            f"runtime root must be a regular non-linked directory: {runtime_absolute}"
        )
    runtime_canonical = runtime_absolute.resolve(strict=True)
    if runtime_canonical != runtime_absolute:
        raise FixtureContractError(
            f"runtime root must use its canonical path: {runtime_absolute}"
        )

    lab_bytes, _lab_value = _load_canonical_fixture(lab_fixture, "Test Lab fixture")
    runtime_fixture = runtime_canonical / RUNTIME_FIXTURE_RELATIVE
    runtime_bytes, _runtime_value = _load_canonical_fixture(
        runtime_fixture,
        "Web Runtime fixture",
    )
    if lab_bytes != runtime_bytes:
        raise FixtureContractError(
            "canonical Godot descriptor fixtures differ between Test Lab and Web Runtime"
        )

    return {
        "schemaVersion": "1.0",
        "status": "passed",
        "contract": "evavo.godot-web-export-descriptor.v2",
        "sha256": hashlib.sha256(lab_bytes).hexdigest(),
        "bytes": len(lab_bytes),
        "testLabFixture": str(lab_fixture.resolve(strict=True)),
        "webRuntimeFixture": str(runtime_fixture.resolve(strict=True)),
        "mutationAuthority": False,
        "publicationAuthority": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=ROOT.parent / "godot-web-runtime",
        help="Canonical local EVAVO Godot Web Runtime repository root.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Write the machine-readable receipt to stdout.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        report = compare_fixtures(arguments.runtime_root)
    except (OSError, FixtureContractError) as error:
        if arguments.json:
            print(
                json.dumps(
                    {
                        "schemaVersion": "1.0",
                        "status": "failed",
                        "contract": "evavo.godot-web-export-descriptor.v2",
                        "error": str(error),
                        "mutationAuthority": False,
                        "publicationAuthority": False,
                    },
                    indent=2,
                )
            )
        else:
            print(f"FAIL {error}", file=sys.stderr)
        return 1

    if arguments.json:
        print(json.dumps(report, indent=2))
    else:
        print(
            "PASS canonical Godot web descriptor fixtures match exactly at "
            f"{report['sha256']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
