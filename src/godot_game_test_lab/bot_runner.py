from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import sys
import time
import uuid
from collections import deque
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .bot_profile import normalize_bot_profile
from .command_guard import validate_scene_argument
from .core import inspect_project
from .native_qa_common import (
    _ERROR_MARKERS,
    _VERSION_RE,
    NativeQaError,
    _archive_checkout,
    _canonical_json,
    _directory_usage,
    _git_text,
    _load_json_object,
    _native_desktop_lease,
    _process_findings,
    _read_bounded_text,
    _require_clean_checkout,
    _require_tracked_file,
    _resolve_child,
    _run_process,
    _safe_relative_path,
    _sha256_file,
    _validate_exact_checkout,
    _validate_sha,
    _write_process_evidence,
)
from .native_qa_evidence import (
    _artifact_inventory,
    _extract_video_evidence,
    _hardware_evidence,
    _required_visual_capabilities,
    _validate_png,
)
from .native_qa_runner import (
    _artifact_remaining,
    _artifact_root_budget,
    _process_receipt,
    _read_validation_status,
    _remaining_seconds,
    _validate_roots,
)
from .pipeline import discover_godot_binary

_INTERACTIVE_CLASSES = {
    "BaseButton",
    "Button",
    "CheckBox",
    "CheckButton",
    "ColorPickerButton",
    "ItemList",
    "LinkButton",
    "MenuButton",
    "OptionButton",
    "TabBar",
    "TextureButton",
    "Tree",
}
_SAFE_ACTION_RE = re.compile(r"^[^\x00\r\n]{1,128}$")


def _casefold_contains(value: str, terms: list[str]) -> bool:
    folded = value.casefold()
    return any(term.casefold() in folded for term in terms)


def _candidate_signature(candidate: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(candidate["steps"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _control_candidates(report: dict[str, Any], campaign: dict[str, Any]) -> list[dict[str, Any]]:
    if campaign["mode"] == "action_fuzz" or "mouse" not in campaign["devices"]:
        return []
    ui = report.get("ui", {})
    if not isinstance(ui, dict):
        return []
    controls = ui.get("controls", [])
    if not isinstance(controls, list):
        return []
    blocked = campaign["blockedText"]
    result: list[dict[str, Any]] = []
    for item in controls:
        if not isinstance(item, dict):
            continue
        control_class = str(item.get("class", ""))
        focus_mode = item.get("focusMode", 0)
        if control_class not in _INTERACTIVE_CLASSES and focus_mode in {0, None}:
            continue
        if item.get("insideViewport") is not True:
            continue
        width = float(item.get("width", 0.0))
        height = float(item.get("height", 0.0))
        if width < 4.0 or height < 4.0:
            continue
        identity = " ".join(
            str(item.get(key, "")) for key in ("path", "name", "text", "class")
        )
        if _casefold_contains(identity, blocked):
            continue
        x = float(item.get("x", 0.0)) + width / 2.0
        y = float(item.get("y", 0.0)) + height / 2.0
        label = str(item.get("text") or item.get("name") or item.get("path") or control_class)
        steps = [
            {"type": "mouse_move", "x": x, "y": y, "relativeX": 0.0, "relativeY": 0.0},
            {"type": "mouse_click", "buttonIndex": 1, "x": x, "y": y, "holdFrames": 1},
            {"type": "wait", "frames": campaign["settleFrames"]},
        ]
        candidate = {
            "kind": "control_click",
            "label": label[:160],
            "controlPath": str(item.get("path", "")),
            "device": "mouse",
            "steps": steps,
        }
        candidate["signature"] = _candidate_signature(candidate)
        result.append(candidate)
    return result


def _input_event_step(
    event: dict[str, Any],
    action_name: str,
    device: str,
    campaign: dict[str, Any],
    viewport: dict[str, Any],
) -> list[dict[str, Any]] | None:
    if device == "semantic":
        return [
            {"type": "action_tap", "action": action_name, "holdFrames": 1, "strength": 1.0},
            {"type": "wait", "frames": campaign["settleFrames"]},
        ]
    if device == "keyboard" and event.get("category") == "keyboard":
        keycode = int(event.get("physicalKeycode") or event.get("keycode") or 0)
        if keycode > 0:
            return [
                {"type": "key_tap", "physicalKeycode": keycode, "holdFrames": 1},
                {"type": "wait", "frames": campaign["settleFrames"]},
            ]
    if device == "gamepad" and event.get("category") == "gamepad":
        if event.get("type") == "InputEventJoypadButton":
            button = int(event.get("buttonIndex", -1))
            if button >= 0:
                return [
                    {
                        "type": "joy_button_tap",
                        "deviceId": 0,
                        "buttonIndex": button,
                        "holdFrames": 1,
                    },
                    {"type": "wait", "frames": campaign["settleFrames"]},
                ]
        if event.get("type") == "InputEventJoypadMotion":
            axis = int(event.get("axis", -1))
            value = float(event.get("axisValue", 0.0))
            if axis >= 0 and value != 0.0:
                return [
                    {"type": "joy_axis", "deviceId": 0, "axis": axis, "value": value},
                    {"type": "wait", "frames": 2},
                    {"type": "joy_axis", "deviceId": 0, "axis": axis, "value": 0.0},
                    {"type": "wait", "frames": campaign["settleFrames"]},
                ]
    if device == "mouse" and event.get("category") == "mouse":
        button = int(event.get("buttonIndex", -1))
        if button > 0:
            x = float(viewport.get("width", campaign["width"])) / 2.0
            y = float(viewport.get("height", campaign["height"])) / 2.0
            return [
                {"type": "mouse_move", "x": x, "y": y, "relativeX": 0.0, "relativeY": 0.0},
                {"type": "mouse_click", "buttonIndex": button, "x": x, "y": y, "holdFrames": 1},
                {"type": "wait", "frames": campaign["settleFrames"]},
            ]
    return None


def _action_candidates(report: dict[str, Any], campaign: dict[str, Any]) -> list[dict[str, Any]]:
    if campaign["mode"] == "ui_graph":
        action_scope = "ui_only"
    else:
        action_scope = "all"
    input_map = report.get("inputMap", {})
    if not isinstance(input_map, dict):
        return []
    raw_actions = input_map.get("actions", [])
    if not isinstance(raw_actions, list):
        return []
    allowlist = {value.casefold() for value in campaign["actionAllowlist"]}
    denylist = campaign["actionDenylist"]
    viewport = report.get("ui", {}).get("viewport", {})
    if not isinstance(viewport, dict):
        viewport = {}
    result: list[dict[str, Any]] = []
    for action in raw_actions:
        if not isinstance(action, dict):
            continue
        name = str(action.get("name", ""))
        if _SAFE_ACTION_RE.fullmatch(name) is None:
            continue
        folded = name.casefold()
        if allowlist and folded not in allowlist:
            continue
        if not allowlist and action_scope == "ui_only" and not folded.startswith("ui_"):
            continue
        if _casefold_contains(name, denylist):
            continue
        events = action.get("events", [])
        if not isinstance(events, list):
            events = []
        for device in campaign["devices"]:
            steps: list[dict[str, Any]] | None = None
            if device == "semantic":
                steps = _input_event_step({}, name, device, campaign, viewport)
            else:
                for event in events:
                    if not isinstance(event, dict):
                        continue
                    steps = _input_event_step(event, name, device, campaign, viewport)
                    if steps is not None:
                        break
            if steps is None:
                continue
            candidate = {
                "kind": "input_action",
                "label": name,
                "action": name,
                "device": device,
                "steps": steps,
            }
            candidate["signature"] = _candidate_signature(candidate)
            result.append(candidate)
    return result


def plan_candidates(
    report: dict[str, Any], campaign: dict[str, Any], *, state_index: int
) -> list[dict[str, Any]]:
    candidates = [*_control_candidates(report, campaign), *_action_candidates(report, campaign)]
    unique: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        unique.setdefault(candidate["signature"], candidate)
    ordered = sorted(
        unique.values(),
        key=lambda item: (item["kind"], item["label"], item["signature"]),
    )
    random.Random(campaign["seed"] ^ state_index).shuffle(ordered)
    return ordered[: campaign["maxActionsPerState"]]


def state_fingerprint(report: dict[str, Any], screenshot: Path | None) -> str:
    ui = report.get("ui", {})
    if not isinstance(ui, dict):
        ui = {}
    controls: list[dict[str, Any]] = []
    for item in ui.get("controls", []) if isinstance(ui.get("controls", []), list) else []:
        if not isinstance(item, dict):
            continue
        controls.append(
            {
                "path": str(item.get("path", "")),
                "class": str(item.get("class", "")),
                "name": str(item.get("name", "")),
                "text": str(item.get("text", "")),
                "x": round(float(item.get("x", 0.0)), 2),
                "y": round(float(item.get("y", 0.0)), 2),
                "width": round(float(item.get("width", 0.0)), 2),
                "height": round(float(item.get("height", 0.0)), 2),
                "focusMode": item.get("focusMode"),
            }
        )
    controls.sort(key=lambda item: (item["path"], item["class"], item["text"]))
    payload: dict[str, Any] = {
        "scene": report.get("scene"),
        "focusOwner": ui.get("focusOwner"),
        "mouseMode": ui.get("mouseMode"),
        "controls": controls,
    }
    payload["screenshotRetained"] = bool(
        screenshot is not None and screenshot.is_file() and not screenshot.is_symlink()
    )
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _checkpoint_path(report: dict[str, Any], checkpoint_root: Path) -> Path | None:
    records = report.get("checkpoints", [])
    if not isinstance(records, list):
        return None
    for item in reversed(records):
        if not isinstance(item, dict):
            continue
        name = str(item.get("path", ""))
        if not name or Path(name).name != name:
            continue
        path = checkpoint_root / name
        if _validate_png(path):
            return path
    return None


def _compact_report(report: dict[str, Any]) -> dict[str, Any]:
    ui = report.get("ui", {}) if isinstance(report.get("ui"), dict) else {}
    return {
        "status": report.get("status"),
        "scene": report.get("scene"),
        "elapsedFrames": report.get("elapsedFrames"),
        "failures": report.get("failures", []),
        "focusOwner": ui.get("focusOwner"),
        "visibleControlCount": ui.get("visibleControlCount"),
        "interactiveControlCount": ui.get("interactiveControlCount"),
        "outOfBoundsInteractiveCount": len(ui.get("outOfBoundsInteractive", [])),
        "smallInteractiveTargetCount": len(ui.get("smallInteractiveTargets", [])),
        "overlapCount": len(ui.get("overlappingInteractivePairs", [])),
        "performance": report.get("performance", {}),
    }


def _isolated_environment(base: dict[str, str], root: Path) -> dict[str, str]:
    root.mkdir(parents=True, exist_ok=False)
    appdata = root / "appdata"
    local = root / "localappdata"
    home = root / "home"
    temporary = root / "temp"
    for path in (appdata, local, home, temporary):
        path.mkdir(parents=True, exist_ok=True)
    environment = dict(base)
    environment.update(
        {
            "APPDATA": str(appdata),
            "LOCALAPPDATA": str(local),
            "HOME": str(home),
            "USERPROFILE": str(home),
            "XDG_DATA_HOME": str(home / ".local" / "share"),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "TEMP": str(temporary),
            "TMP": str(temporary),
        }
    )
    return environment


def _build_journey(
    campaign: dict[str, Any], journey_id: str, trace: list[dict[str, Any]]
) -> dict[str, Any]:
    steps = [dict(step) for step in trace]
    if campaign["checkpointEveryState"]:
        steps.append({"type": "checkpoint", "id": "state"})
    return {
        "id": journey_id,
        "required": True,
        "scene": campaign["scene"],
        "device": "semantic",
        "settleFrames": campaign["settleFrames"],
        "maxFrames": campaign["maxFrames"],
        "fps": campaign["fps"],
        "width": campaign["width"],
        "height": campaign["height"],
        "renderingMethod": campaign["renderingMethod"],
        "renderingDriver": campaign["renderingDriver"],
        "gpuIndex": campaign["gpuIndex"],
        "userArguments": campaign["userArguments"],
        "requiredActions": [],
        "steps": steps,
        "assertions": [{"type": "scene_loaded"}],
        "ux": campaign["ux"],
    }


def _run_journey(
    *,
    campaign: dict[str, Any],
    trace: list[dict[str, Any]],
    journey_id: str,
    journey_root: Path,
    artifacts: Path,
    work_container: Path,
    harness_root: Path,
    project_root: Path,
    godot: Path,
    help_text: str,
    window_position: str,
    timeout: int,
    maximum_artifact_bytes: int,
    record_movie: bool,
) -> dict[str, Any]:
    journey_root.mkdir(parents=True, exist_ok=False)
    checkpoints = journey_root / "checkpoints"
    checkpoints.mkdir()
    journey = _build_journey(campaign, journey_id, trace)
    missing = _required_visual_capabilities(help_text, journey)
    if missing:
        return {
            "status": "blocked",
            "findings": ["Godot is missing required bot QA capabilities: " + ", ".join(missing)],
            "evidence": [],
            "report": {},
            "fingerprint": None,
            "screenshot": None,
        }
    journey_file = harness_root / f"bot-{journey_id}.json"
    journey_file.write_text(_canonical_json(journey), encoding="utf-8")
    retained = journey_root / "journey.normalized.json"
    retained.write_text(_canonical_json(journey), encoding="utf-8")
    report_path = journey_root / "journey-report.json"
    engine_log = journey_root / "godot.log"
    movie = journey_root / "gameplay.avi"
    command = [
        str(godot),
        "--verbose",
        "--path",
        str(project_root),
        "--rendering-method",
        campaign["renderingMethod"],
        "--rendering-driver",
        campaign["renderingDriver"],
    ]
    if campaign["renderingMethod"] != "gl_compatibility":
        command.extend(["--gpu-index", str(campaign["gpuIndex"])])
    command.extend(
        [
            "--windowed",
            "--resolution",
            f"{campaign['width']}x{campaign['height']}",
            "--position",
            window_position,
            "--log-file",
            str(engine_log),
            "--fixed-fps",
            str(campaign["fps"]),
            "--quit-after",
            str(campaign["maxFrames"] + 240),
            "--script",
            "res://.evavo-lab/godot_input_journey.gd",
        ]
    )
    if record_movie:
        command.extend(["--write-movie", str(movie)])
    if campaign["userArguments"]:
        command.append("--")
        command.extend(campaign["userArguments"])
    user_root = work_container / "user-data" / journey_id
    environment = _isolated_environment(os.environ.copy(), user_root)
    environment.update(
        {
            "EVAVO_JOURNEY_PATH": f"res://.evavo-lab/{journey_file.name}",
            "EVAVO_JOURNEY_REPORT": str(report_path),
            "EVAVO_JOURNEY_CHECKPOINT_ROOT": str(checkpoints),
            "EVAVO_JOURNEY_SCENE": campaign["scene"],
            "EVAVO_JOURNEY_MAX_FRAMES": str(campaign["maxFrames"]),
        }
    )
    process = _run_process(
        command,
        project_root,
        timeout,
        environment=environment,
        artifact_budget_root=journey_root,
        maximum_artifact_bytes=maximum_artifact_bytes,
    )
    evidence = [retained.relative_to(artifacts).as_posix()]
    evidence.extend(_write_process_evidence(process, artifacts, f"bot-{journey_id}"))
    findings = _process_findings(process, f"bot journey {journey_id}")
    if engine_log.is_file() and not engine_log.is_symlink():
        evidence.append(engine_log.relative_to(artifacts).as_posix())
        engine_text = _read_bounded_text(engine_log)
        for marker in _ERROR_MARKERS:
            if marker.casefold() in engine_text.casefold():
                findings.append(f"bot journey engine log contains error marker: {marker}")
    else:
        findings.append("bot journey engine log was not produced")
    report: dict[str, Any] = {}
    if report_path.is_file() and not report_path.is_symlink():
        try:
            report = _load_json_object(report_path, "bot journey report")
            evidence.append(report_path.relative_to(artifacts).as_posix())
        except NativeQaError as error:
            findings.append(str(error))
    else:
        findings.append("bot journey report was not produced")
    if report.get("status") != "passed":
        raw_failures = report.get("failures", [])
        for failure in raw_failures if isinstance(raw_failures, list) else []:
            findings.append(f"bot harness: {failure}")
    screenshot = _checkpoint_path(report, checkpoints)
    if screenshot is None:
        findings.append("bot journey did not produce a valid final checkpoint PNG")
    else:
        evidence.append(screenshot.relative_to(artifacts).as_posix())
    visual: dict[str, Any] = {"status": "not-recorded", "findings": [], "evidence": []}
    if record_movie:
        visual = _extract_video_evidence(
            movie,
            artifacts,
            timeout,
            campaign["ux"],
            maximum_artifact_bytes=maximum_artifact_bytes,
        )
        findings.extend(visual["findings"])
        evidence.extend(visual["evidence"])
    fingerprint = state_fingerprint(report, screenshot) if report else None
    return {
        "status": "passed" if not findings else "failed",
        "process": _process_receipt(process),
        "findings": sorted(set(findings)),
        "evidence": sorted(set(evidence)),
        "report": report,
        "reportSummary": _compact_report(report),
        "fingerprint": fingerprint,
        "screenshot": (
            screenshot.relative_to(artifacts).as_posix() if screenshot is not None else None
        ),
        "visual": visual,
    }


def _run_campaign(
    *,
    campaign: dict[str, Any],
    campaign_root: Path,
    artifacts: Path,
    work_container: Path,
    harness_root: Path,
    project_root: Path,
    godot: Path,
    help_text: str,
    window_position: str,
    started: float,
    maximum_total_seconds: int,
    timeout: int,
    maximum_artifact_bytes: int,
) -> dict[str, Any]:
    campaign_root.mkdir(parents=True, exist_ok=False)
    probes_root = campaign_root / "probes"
    replays_root = campaign_root / "representative-replays"
    probes_root.mkdir()
    replays_root.mkdir()
    states: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    fingerprints: dict[str, int] = {}
    queue: deque[int] = deque()
    runs = 0
    stalls = 0
    reserved_replays = (
        min(campaign["maxRepresentativePaths"], campaign["maxRuns"] - 1)
        if campaign["recordRepresentativePaths"]
        else 0
    )
    probe_run_limit = campaign["maxRuns"] - reserved_replays

    def execute(trace: list[dict[str, Any]], label: str, record: bool = False) -> dict[str, Any]:
        nonlocal runs
        runs += 1
        root = (replays_root if record else probes_root) / label
        scoped_budget = _artifact_root_budget(artifacts, root, maximum_artifact_bytes)
        return _run_journey(
            campaign=campaign,
            trace=trace,
            journey_id=f"{campaign['id']}-{label}",
            journey_root=root,
            artifacts=artifacts,
            work_container=work_container,
            harness_root=harness_root,
            project_root=project_root,
            godot=godot,
            help_text=help_text,
            window_position=window_position,
            timeout=_remaining_seconds(started, maximum_total_seconds, timeout),
            maximum_artifact_bytes=scoped_budget,
            record_movie=record,
        )

    baseline = execute([], "probe-0000")
    if not baseline.get("report") or baseline.get("fingerprint") is None:
        return {
            "id": campaign["id"],
            "required": campaign["required"],
            "status": "failed",
            "runs": runs,
            "states": [],
            "transitions": [],
            "failures": [
                {
                    "trace": [],
                    "findings": baseline.get("findings", ["baseline survey failed"]),
                    "evidence": baseline.get("evidence", []),
                }
            ],
            "findings": ["bot campaign could not survey its baseline state"],
        }
    baseline_state = {
        "id": "s0000",
        "index": 0,
        "depth": 0,
        "trace": [],
        "fingerprint": baseline["fingerprint"],
        "screenshot": baseline["screenshot"],
        "reportSummary": baseline["reportSummary"],
        "report": baseline["report"],
        "findings": baseline["findings"],
        "evidence": baseline["evidence"],
    }
    states.append(baseline_state)
    fingerprints[baseline["fingerprint"]] = 0
    queue.append(0)
    if baseline["findings"]:
        failures.append(
            {
                "state": "s0000",
                "trace": [],
                "findings": baseline["findings"],
                "evidence": baseline["evidence"],
            }
        )

    while queue and len(states) < campaign["maxStates"] and runs < probe_run_limit:
        state_index = queue.popleft()
        state = states[state_index]
        if state["depth"] >= campaign["maxDepth"]:
            continue
        candidates = plan_candidates(state["report"], campaign, state_index=state_index)
        for candidate in candidates:
            if len(states) >= campaign["maxStates"] or runs >= probe_run_limit:
                break
            trace = [*state["trace"], *candidate["steps"]]
            label = f"probe-{runs:04d}"
            outcome = execute(trace, label)
            transition: dict[str, Any] = {
                "from": state["id"],
                "candidate": {key: value for key, value in candidate.items() if key != "steps"},
                "trace": trace,
                "run": label,
                "status": outcome["status"],
                "findings": outcome["findings"],
                "evidence": outcome["evidence"],
            }
            fingerprint = outcome.get("fingerprint")
            if fingerprint is None:
                transition["result"] = "no-state"
                failures.append(
                    {
                        "state": state["id"],
                        "candidate": candidate["label"],
                        "trace": trace,
                        "findings": outcome["findings"],
                        "evidence": outcome["evidence"],
                    }
                )
                stalls += 1
            elif fingerprint in fingerprints:
                target_index = fingerprints[fingerprint]
                transition["to"] = states[target_index]["id"]
                transition["result"] = (
                    "no-change" if target_index == state_index else "known-state"
                )
                stalls += 1
                if outcome["findings"]:
                    failures.append(
                        {
                            "state": state["id"],
                            "candidate": candidate["label"],
                            "trace": trace,
                            "findings": outcome["findings"],
                            "evidence": outcome["evidence"],
                        }
                    )
            else:
                new_index = len(states)
                new_state = {
                    "id": f"s{new_index:04d}",
                    "index": new_index,
                    "depth": state["depth"] + 1,
                    "trace": trace,
                    "fingerprint": fingerprint,
                    "screenshot": outcome["screenshot"],
                    "reportSummary": outcome["reportSummary"],
                    "report": outcome["report"],
                    "findings": outcome["findings"],
                    "evidence": outcome["evidence"],
                }
                states.append(new_state)
                fingerprints[fingerprint] = new_index
                queue.append(new_index)
                transition["to"] = new_state["id"]
                transition["result"] = "new-state"
                stalls = 0
                if outcome["findings"]:
                    failures.append(
                        {
                            "state": new_state["id"],
                            "candidate": candidate["label"],
                            "trace": trace,
                            "findings": outcome["findings"],
                            "evidence": outcome["evidence"],
                        }
                    )
            transitions.append(transition)
            if stalls >= campaign["stallLimit"]:
                break
        if stalls >= campaign["stallLimit"]:
            break

    representative: list[dict[str, Any]] = []
    if campaign["recordRepresentativePaths"] and campaign["maxRepresentativePaths"] > 0:
        ranked = sorted(states, key=lambda item: (-item["depth"], item["id"]))
        for index, state in enumerate(ranked[: campaign["maxRepresentativePaths"]]):
            if runs >= campaign["maxRuns"]:
                break
            replay = execute(state["trace"], f"replay-{index:02d}", record=True)
            representative.append(
                {
                    "state": state["id"],
                    "depth": state["depth"],
                    "trace": state["trace"],
                    "status": replay["status"],
                    "findings": replay["findings"],
                    "evidence": replay["evidence"],
                    "visual": replay["visual"],
                }
            )
            if replay["findings"]:
                failures.append(
                    {
                        "state": state["id"],
                        "trace": state["trace"],
                        "findings": replay["findings"],
                        "evidence": replay["evidence"],
                    }
                )

    state_records = [
        {key: value for key, value in state.items() if key != "report"} for state in states
    ]
    findings: list[str] = []
    if failures:
        findings.append("one or more deterministic bot traces exposed a runtime or UX failure")
    if len(states) == 1 and transitions:
        findings.append("bot campaign did not discover a changed runtime state")
    if stalls >= campaign["stallLimit"]:
        findings.append("bot campaign stopped after reaching its deterministic stall limit")
    return {
        "id": campaign["id"],
        "required": campaign["required"],
        "status": "failed" if failures else "passed",
        "mode": campaign["mode"],
        "seed": campaign["seed"],
        "runs": runs,
        "stateCount": len(states),
        "transitionCount": len(transitions),
        "states": state_records,
        "transitions": transitions,
        "representativeReplays": representative,
        "failures": failures,
        "findings": findings,
        "truthBoundary": (
            "The bot explores a bounded deterministic graph by replaying synthetic Godot "
            "InputEvents in fresh processes with isolated user data. It is not a proof of "
            "complete gameplay, physical-controller behavior or human visual quality."
        ),
    }


def run_bot_qa(args: argparse.Namespace) -> dict[str, Any]:
    started = time.monotonic()
    run_id = f"bot-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:12]}"
    expected_lab_sha = _validate_sha(args.expected_lab_sha, "expected_lab_sha")
    expected_target_sha = _validate_sha(args.expected_target_sha, "expected_target_sha")
    if _VERSION_RE.fullmatch(args.minimum_godot_version) is None:
        raise NativeQaError("minimum_godot_version must be an explicit Godot 4.x.y version")
    lab_root, target_root, _allowed_artifact_root, artifacts = _validate_roots(args)
    work_container = artifacts / "work"
    target_git_root: Path | None = None
    status_before = ""
    try:
        _validate_exact_checkout(lab_root, expected_lab_sha, "test lab")
        _require_clean_checkout(lab_root, "test lab")
        target_git_root = Path(_git_text(target_root, ["rev-parse", "--show-toplevel"])).resolve()
        _validate_exact_checkout(target_git_root, expected_target_sha, "target repository")
        _require_clean_checkout(target_git_root, "target repository")
        status_before = _git_text(
            target_git_root, ["status", "--porcelain=v1", "--untracked-files=all"]
        )
        project_subpath = _safe_relative_path(args.project_subpath, "project_subpath")
        profile_input = args.profile.expanduser()
        if not profile_input.is_absolute():
            profile_input = target_git_root / profile_input
        profile_path = profile_input.resolve(strict=True)
        profile_relative = _require_tracked_file(target_git_root, profile_path, "profile")
        profile = normalize_bot_profile(_load_json_object(profile_path, "bot QA profile"))
        (artifacts / "profile.normalized.json").write_text(
            _canonical_json(profile), encoding="utf-8"
        )
        (artifacts / "run-context.json").write_text(
            _canonical_json(
                {
                    "schemaVersion": "1.0",
                    "runId": run_id,
                    "labSha": expected_lab_sha,
                    "targetSha": expected_target_sha,
                    "projectSubpath": project_subpath.as_posix(),
                    "profile": profile_relative,
                    "profileSha256": _sha256_file(profile_path),
                    "maximumTotalSeconds": args.max_total_seconds,
                    "maximumArtifactBytes": args.max_artifact_bytes,
                }
            ),
            encoding="utf-8",
        )
        with _native_desktop_lease(enabled=os.name == "nt") as desktop_lease:
            hardware = _hardware_evidence(target_git_root)
            (artifacts / "hardware.json").write_text(
                _canonical_json(hardware), encoding="utf-8"
            )
            interactive = bool(hardware["session"]["interactive"])
            if args.require_interactive_desktop and not interactive:
                raise NativeQaError(
                    "bot QA requires Greg's logged-in interactive Windows desktop session"
                )
            work_root = work_container / "repository"
            archive_receipt = _archive_checkout(
                target_git_root,
                expected_target_sha,
                work_root,
                _remaining_seconds(started, args.max_total_seconds, args.timeout),
            )
            (artifacts / "source-archive.json").write_text(
                _canonical_json(archive_receipt), encoding="utf-8"
            )
            project_root = _resolve_child(work_root, project_subpath, "project_subpath")
            if not (project_root / "project.godot").is_file():
                raise NativeQaError("selected project_subpath does not contain project.godot")
            archived_profile = _resolve_child(
                work_root,
                Path(*PurePosixPath(profile_relative).parts),
                "archived profile",
            )
            if _sha256_file(archived_profile) != _sha256_file(profile_path):
                raise NativeQaError("archived bot profile does not match the exact target checkout")

            validation_root = artifacts / "validation"
            validation_root.mkdir()
            remaining = _remaining_seconds(started, args.max_total_seconds, args.max_total_seconds)
            validation_command = [
                sys.executable,
                "-m",
                "godot_game_test_lab.cli",
                "validate",
                str(project_root),
                "--minimum-godot-version",
                args.minimum_godot_version,
                "--timeout",
                str(min(args.timeout, remaining)),
                "--boot-frames",
                str(args.boot_frames),
                "--artifacts",
                str(validation_root),
            ]
            if args.godot is not None:
                validation_command.extend(["--godot", str(args.godot)])
            if args.dotnet is not None:
                validation_command.extend(["--dotnet", str(args.dotnet)])
            validation_process = _run_process(
                validation_command,
                lab_root,
                remaining,
                artifact_budget_root=validation_root,
                maximum_artifact_bytes=_artifact_root_budget(
                    artifacts, validation_root, args.max_artifact_bytes
                ),
            )
            validation_evidence = _write_process_evidence(
                validation_process, artifacts, "bot-validation"
            )
            validation_findings = _process_findings(validation_process, "bot validation")
            try:
                validation_status = _read_validation_status(validation_root / "report.json")
            except NativeQaError as error:
                validation_status = "failed"
                validation_findings.append(str(error))
            if validation_findings and validation_status == "passed":
                validation_status = "failed"

            campaigns: list[dict[str, Any]] = []
            if validation_status == "passed":
                inventory = inspect_project(project_root)
                godot = discover_godot_binary(
                    args.godot, requires_mono=bool(inventory.csharp_projects)
                )
                if godot is None:
                    raise NativeQaError("compatible Godot executable was not found for bot QA")
                help_result = _run_process(
                    [str(godot), "--help"],
                    project_root,
                    _remaining_seconds(started, args.max_total_seconds, 30),
                )
                _write_process_evidence(help_result, artifacts, "bot-godot-help")
                if _process_findings(help_result, "Godot --help"):
                    raise NativeQaError("Godot --help failed before bot execution")
                help_text = f"{help_result['stdout']}\n{help_result['stderr']}"
                harness_root = project_root / ".evavo-lab"
                harness_root.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(
                    lab_root / "scripts" / "godot_input_journey.gd",
                    harness_root / "godot_input_journey.gd",
                )
                for campaign in profile["campaigns"]:
                    if campaign["scene"]:
                        campaign = dict(campaign)
                        campaign["scene"] = validate_scene_argument(
                            campaign["scene"], project_root
                        )
                    campaigns.append(
                        _run_campaign(
                            campaign=campaign,
                            campaign_root=artifacts / "campaigns" / campaign["id"],
                            artifacts=artifacts,
                            work_container=work_container,
                            harness_root=harness_root,
                            project_root=project_root,
                            godot=godot,
                            help_text=help_text,
                            window_position=args.window_position,
                            started=started,
                            maximum_total_seconds=args.max_total_seconds,
                            timeout=args.timeout,
                            maximum_artifact_bytes=args.max_artifact_bytes,
                        )
                    )
                    _artifact_remaining(artifacts, args.max_artifact_bytes)

            required_failures = [
                campaign
                for campaign in campaigns
                if campaign["required"] and campaign["status"] != "passed"
            ]
            optional_failures = [
                campaign
                for campaign in campaigns
                if not campaign["required"] and campaign["status"] != "passed"
            ]
            findings: list[str] = []
            status = "passed"
            if validation_status != "passed":
                status = "failed"
                findings.append("canonical Godot validation did not pass")
            if required_failures:
                status = "failed"
                findings.append("one or more required bot campaigns did not pass")
            if optional_failures:
                findings.append("one or more optional bot campaigns did not pass")
            if not campaigns and validation_status == "passed":
                status = "failed"
                findings.append("no bot campaigns were executed")
            if not interactive:
                findings.append("execution was non-interactive and is not desktop evidence")

            status_after = _git_text(
                target_git_root, ["status", "--porcelain=v1", "--untracked-files=all"]
            )
            mutation = status_after != status_before
            if mutation:
                status = "failed"
                findings.append("bot QA changed the target repository checkout")
            shutil.rmtree(work_container, ignore_errors=True)
            used_bytes, used_files, complete = _directory_usage(artifacts)
            if not complete or used_bytes > args.max_artifact_bytes:
                status = "failed"
                findings.append("bot QA exceeded its bounded artifact budget")
            summary: dict[str, Any] = {
                "schemaVersion": "1.0",
                "runId": run_id,
                "status": status,
                "generatedAt": datetime.now(UTC).isoformat(),
                "durationSeconds": round(time.monotonic() - started, 3),
                "labSha": expected_lab_sha,
                "targetSha": expected_target_sha,
                "targetGitRoot": str(target_git_root),
                "projectSubpath": project_subpath.as_posix(),
                "profile": profile_relative,
                "profileSha256": _sha256_file(profile_path),
                "nativeDesktopEvidence": interactive,
                "desktopLease": desktop_lease,
                "hardware": hardware,
                "sourceArchive": archive_receipt,
                "validationStatus": validation_status,
                "validationProcess": _process_receipt(validation_process),
                "validationEvidence": validation_evidence,
                "validationFindings": sorted(set(validation_findings)),
                "campaigns": campaigns,
                "targetMutationDetected": mutation,
                "executionBudget": {
                    "maximumTotalSeconds": args.max_total_seconds,
                    "maximumArtifactBytes": args.max_artifact_bytes,
                    "retainedArtifactBytes": used_bytes,
                    "retainedArtifactFiles": used_files,
                    "measurementComplete": complete,
                },
                "findings": sorted(set(findings)),
                "truthBoundary": (
                    "This receipt proves bounded deterministic synthetic exploration of the "
                    "retained exact target SHA. It does not prove complete gameplay, physical "
                    "controller behavior, accessibility, game feel or human visual approval."
                ),
            }
            summary["artifacts"] = _artifact_inventory(
                artifacts, maximum_total_bytes=args.max_artifact_bytes
            )
            (artifacts / "bot-agent-summary.json").write_text(
                _canonical_json(summary), encoding="utf-8"
            )
            return summary
    finally:
        shutil.rmtree(work_container, ignore_errors=True)
        if target_git_root is not None:
            final_status = _git_text(
                target_git_root, ["status", "--porcelain=v1", "--untracked-files=all"]
            )
            if final_status != status_before and sys.exc_info()[0] is None:
                raise NativeQaError("bot QA changed the target checkout after finalization")


__all__ = ["plan_candidates", "run_bot_qa", "state_fingerprint"]
