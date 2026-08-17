"""Isolated Godot rig-motion acceptance runner for v4.1."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FAMILIES = {
    "humanoid", "quadruped", "rodent", "arachnid",
    "wheeled-vehicle", "tracked-vehicle", "helicopter",
}


class GodotRigAcceptanceError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_env() -> dict[str, str]:
    allowed = {"PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG"}
    env = {key: value for key, value in os.environ.items() if key in allowed}
    env["NO_PROXY"] = "*"
    env["no_proxy"] = "*"
    return env


def validate_probe_receipt(receipt: Mapping[str, Any], family: str) -> None:
    if receipt.get("schemaVersion") != 1 or receipt.get("kind") != "evavo-godot-rig-motion-probe-v4.1":
        raise GodotRigAcceptanceError("probe receipt identity invalid")
    if receipt.get("family") != family:
        raise GodotRigAcceptanceError("probe receipt family mismatch")
    if receipt.get("loadOk") is not True or receipt.get("instantiateOk") is not True:
        raise GodotRigAcceptanceError("Godot could not load and instantiate the asset")
    if int(receipt.get("meshInstanceCount", 0)) < 1:
        raise GodotRigAcceptanceError("no imported mesh instances")
    motion = receipt.get("motion")
    if not isinstance(motion, Mapping) or not motion:
        raise GodotRigAcceptanceError("no motion evidence")
    for group, evidence in motion.items():
        if not isinstance(evidence, Mapping):
            raise GodotRigAcceptanceError(f"invalid motion evidence for {group}")
        if evidence.get("sampleCount", 0) < 4:
            raise GodotRigAcceptanceError(f"insufficient motion samples for {group}")
        if float(evidence.get("maximumTransformDelta", 0.0)) <= 0.00001:
            raise GodotRigAcceptanceError(f"no measurable motion for {group}")
    authority = receipt.get("authority")
    if not isinstance(authority, Mapping):
        raise GodotRigAcceptanceError("authority missing")
    for key in ("runtimeAdmission", "targetRepositoryMutation", "gitMutation", "deployment", "publication"):
        if authority.get(key) is not False:
            raise GodotRigAcceptanceError(f"authority escalation: {key}")


def run_acceptance(
    *,
    godot: str,
    godot_sha256: str,
    asset: str,
    asset_sha256: str,
    rig_manifest: str,
    rig_manifest_sha256: str,
    family: str,
    probe_script: str,
    probe_script_sha256: str,
    output: str,
    timeout_seconds: int = 600,
) -> dict[str, Any]:
    if family not in FAMILIES:
        raise GodotRigAcceptanceError("unsupported family")
    paths = {
        "godot": Path(godot).expanduser().resolve(strict=True),
        "asset": Path(asset).expanduser().resolve(strict=True),
        "manifest": Path(rig_manifest).expanduser().resolve(strict=True),
        "probe": Path(probe_script).expanduser().resolve(strict=True),
    }
    expected = {
        "godot": godot_sha256,
        "asset": asset_sha256,
        "manifest": rig_manifest_sha256,
        "probe": probe_script_sha256,
    }
    for key, path in paths.items():
        if not SHA256_RE.fullmatch(expected[key]):
            raise GodotRigAcceptanceError(f"{key} expected SHA-256 invalid")
        if sha256_file(path) != expected[key]:
            raise GodotRigAcceptanceError(f"{key} SHA-256 mismatch")
    destination = Path(output).expanduser().resolve()
    if destination.exists():
        raise GodotRigAcceptanceError("output must not already exist")
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="evavo-godot-rig-v4-") as temporary:
        project = Path(temporary)
        asset_target = project / f"candidate{paths['asset'].suffix.lower()}"
        manifest_target = project / "rig-manifest.json"
        probe_target = project / "rig_motion_probe_v4_1.gd"
        receipt_target = project / "probe-receipt.json"
        shutil.copy2(paths["asset"], asset_target)
        shutil.copy2(paths["manifest"], manifest_target)
        shutil.copy2(paths["probe"], probe_target)
        (project / "project.godot").write_text(
            '[application]\nconfig/name="EVAVO Rig Motion Probe"\n'
            '[rendering]\nrenderer/rendering_method="gl_compatibility"\n',
            encoding="utf-8",
            newline="\n",
        )
        arguments = [
            str(paths["godot"]),
            "--headless",
            "--path",
            str(project),
            "--script",
            str(probe_target),
            "--",
            f"--asset=res://{asset_target.name}",
            f"--manifest={manifest_target}",
            f"--family={family}",
            f"--output={receipt_target}",
        ]
        completed = subprocess.run(
            arguments,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            env=safe_env(),
        )
        if completed.returncode != 0 or not receipt_target.is_file():
            raise GodotRigAcceptanceError(
                f"Godot probe failed with exit {completed.returncode}: "
                f"{completed.stderr[-4000:]}"
            )
        receipt = json.loads(receipt_target.read_text(encoding="utf-8"))
        validate_probe_receipt(receipt, family)
        final = {
            "schemaVersion": 1,
            "kind": "evavo-godot-rig-motion-acceptance-v4.1",
            "status": "godot-rig-motion-accepted-for-human-review",
            "family": family,
            "assetSha256": asset_sha256,
            "rigManifestSha256": rig_manifest_sha256,
            "godotExecutableSha256": godot_sha256,
            "probeScriptSha256": probe_script_sha256,
            "probeReceipt": receipt,
            "stdoutTail": completed.stdout[-8000:],
            "stderrTail": completed.stderr[-8000:],
            "authority": {
                "runtimeAdmission": False,
                "targetRepositoryMutation": False,
                "gitMutation": False,
                "deployment": False,
                "publication": False,
                "namedHumanReviewRequired": True,
            },
        }
        with destination.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(final, indent=2, sort_keys=True) + "\n")
        return final


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--godot", required=True)
    parser.add_argument("--godot-sha256", required=True)
    parser.add_argument("--asset", required=True)
    parser.add_argument("--asset-sha256", required=True)
    parser.add_argument("--rig-manifest", required=True)
    parser.add_argument("--rig-manifest-sha256", required=True)
    parser.add_argument("--family", required=True)
    parser.add_argument("--probe-script", required=True)
    parser.add_argument("--probe-script-sha256", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    args = parser.parse_args(argv)
    try:
        result = run_acceptance(
            godot=args.godot,
            godot_sha256=args.godot_sha256.lower(),
            asset=args.asset,
            asset_sha256=args.asset_sha256.lower(),
            rig_manifest=args.rig_manifest,
            rig_manifest_sha256=args.rig_manifest_sha256.lower(),
            family=args.family,
            probe_script=args.probe_script,
            probe_script_sha256=args.probe_script_sha256.lower(),
            output=args.output,
            timeout_seconds=args.timeout_seconds,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, GodotRigAcceptanceError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
