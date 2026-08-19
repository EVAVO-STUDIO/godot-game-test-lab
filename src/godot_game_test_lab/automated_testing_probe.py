from __future__ import annotations

import json
import sys
from collections.abc import Callable, Sequence
from typing import Any

from . import __version__
from .engine_manager import list_installations
from .pipeline import doctor_payload

PROBE_SCHEMA = "evavo_godot_game_test_lab_probe_v1"


def _record(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _ready_tool(value: object) -> bool:
    item = _record(value)
    return item.get("editorCompatible") is True


def _available_tool(value: object) -> bool:
    item = _record(value)
    return item.get("available") is True or item.get("compatible") is True


def build_probe(
    *,
    doctor_fn: Callable[..., dict[str, Any]] = doctor_payload,
    installations_fn: Callable[[], list[dict[str, Any]]] = list_installations,
) -> dict[str, Any]:
    doctor = _record(doctor_fn())
    installations = installations_fn()
    managed_ready = any(
        isinstance(item, dict) and item.get("status") == "ready" for item in installations
    )
    godot_ready = _ready_tool(doctor.get("godot"))
    mono_ready = _ready_tool(doctor.get("godotMono"))
    dotnet_available = _available_tool(doctor.get("dotnet"))
    ready = godot_ready or mono_ready or managed_ready

    return {
        "schema": PROBE_SCHEMA,
        "tool": "godot-game-test-lab",
        "toolVersion": __version__,
        "ready": ready,
        "host": {
            "pythonVersion": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "godotEditorCompatible": godot_ready,
            "godotMonoEditorCompatible": mono_ready,
            "dotnetAvailable": dotnet_available,
            "managedEngineReady": managed_ready,
            "managedEngineCount": sum(
                1
                for item in installations
                if isinstance(item, dict) and item.get("status") == "ready"
            ),
        },
        "capabilities": {
            "staticAudit": True,
            "nativeValidation": ready,
            "boundedNativeRun": ready,
            "movieEvidence": ready,
            "linuxSandbox": True,
            "nativeAuthoredQa": ready,
            "multiplayerQa": ready,
            "nativeBotQa": ready,
            "mediaQa": True,
            "mcpBridge": True,
        },
        "truth": {
            "probeOnly": True,
            "projectSelected": False,
            "targetProjectExecuted": False,
            "targetProjectMutated": False,
            "repositoryMutationPerformed": False,
            "engineProvisioningPerformed": False,
            "networkProvisioningPerformed": False,
            "rawExecutablePathsRetained": False,
            "projectPathsRetained": False,
            "multiplayerTargetSelected": False,
            "multiplayerRolesExecuted": False,
            "physicalControllerCertified": False,
            "networkConditionCertified": False,
            "humanGameFeelApprovalClaimed": False,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(argv) if argv is not None else sys.argv[1:]
    if arguments not in ([], ["--json"]):
        raise SystemExit("Usage: automated-testing-probe [--json]")
    print(json.dumps(build_probe(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
