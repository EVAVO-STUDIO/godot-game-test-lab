from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from .audio_analysis_io import _integer, _number, _portable, _strings
from .audio_analysis_types import (
    ANALYSIS_ID,
    AUDIO_PATTERN,
    AUDIO_SUFFIXES,
    CONTRACT_ID,
    EXPECTED_BUS_IDS,
    EXPECTED_ROLE_IDS,
    INVENTORY_ID,
    MAXIMUM_PATHS,
    SELECTION_ID,
    TARGET_REPOSITORY,
    AudioAnalysisVerificationError,
)


def _contract_authority(
    document: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    if (
        document.get("schemaVersion") != "1.0"
        or document.get("contract") != CONTRACT_ID
        or document.get("targetRepository") != TARGET_REPOSITORY
        or document.get("sourceRepository") != "EVAVO-STUDIO/evavo-audio-studio"
        or document.get("engine")
        != {
            "name": "Godot",
            "minimumVersion": "4.6.2",
            "scripting": "csharp",
            "renderer": "compatibility",
        }
    ):
        raise AudioAnalysisVerificationError(
            "Audio production contract identity is invalid"
        )
    buses_source = document.get("buses")
    roles_source = document.get("roles")
    if not isinstance(buses_source, list) or not isinstance(roles_source, list):
        raise AudioAnalysisVerificationError("Audio contract roles or buses are missing")
    if tuple(row.get("id") for row in buses_source if isinstance(row, dict)) != EXPECTED_BUS_IDS:
        raise AudioAnalysisVerificationError("Audio bus authority changed")
    if tuple(row.get("id") for row in roles_source if isinstance(row, dict)) != EXPECTED_ROLE_IDS:
        raise AudioAnalysisVerificationError("Audio role authority changed")
    buses: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(buses_source):
        if not isinstance(row, dict):
            raise AudioAnalysisVerificationError(f"buses[{index}] must be an object")
        buses[str(row["id"])] = dict(row)
    roles: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(roles_source):
        if not isinstance(row, dict):
            raise AudioAnalysisVerificationError(f"roles[{index}] must be an object")
        role_id = str(row["id"])
        if row.get("bus") not in buses:
            raise AudioAnalysisVerificationError(f"{role_id} has an invalid bus")
        if row.get("channels") not in {"mono", "stereo"}:
            raise AudioAnalysisVerificationError(f"{role_id} has invalid channels")
        if row.get("runtimeFormat") not in {"wav-pcm16", "ogg-vorbis"}:
            raise AudioAnalysisVerificationError(f"{role_id} has an invalid runtime format")
        if not isinstance(row.get("loopRequired"), bool):
            raise AudioAnalysisVerificationError(f"{role_id}.loopRequired must be boolean")
        _strings(row.get("pathTokens"), f"{role_id}.pathTokens")
        _strings(row.get("requiredStages"), f"{role_id}.requiredStages")
        roles[role_id] = dict(row)
    mastering = document.get("mastering")
    publication = document.get("publication")
    if not isinstance(mastering, dict) or not isinstance(publication, dict):
        raise AudioAnalysisVerificationError(
            "Audio mastering or publication authority is missing"
        )
    if (
        mastering.get("masterSampleRateHz") != 48_000
        or mastering.get("lowLatencyRuntimeFormat") != "wav-pcm16"
        or mastering.get("streamingRuntimeFormat") != "ogg-vorbis"
        or mastering.get("recursiveLossyEncodingAllowed") is not False
        or publication.get("publicationAuthority") is not False
        or publication.get("deletionAuthority") is not False
        or publication.get("humanListeningApprovalRequired") is not True
        or publication.get("godotGameplayMixApprovalRequired") is not True
        or publication.get("provenanceApprovalRequired") is not True
        or publication.get("sealedDevelopmentStudioPublicationRequired") is not True
        or publication.get("forcePushAllowed") is not False
    ):
        raise AudioAnalysisVerificationError(
            "Audio production safety boundary is invalid"
        )
    return roles, buses, dict(mastering)


def _selected_audio(document: dict[str, Any], head: str) -> list[str]:
    identity = document.get("selection")
    paths_source = document.get("paths")
    if (
        document.get("schemaVersion") != "1.0"
        or document.get("repository") != TARGET_REPOSITORY
        or document.get("headSha") != head
        or (identity is not None and identity != SELECTION_ID)
        or not isinstance(paths_source, list)
        or not paths_source
        or len(paths_source) > MAXIMUM_PATHS
    ):
        raise AudioAnalysisVerificationError(
            "Audio publication selection identity is invalid"
        )
    paths = [
        _portable(value, f"selection.paths[{index}]")
        for index, value in enumerate(paths_source)
    ]
    folded = [value.casefold() for value in paths]
    if len(folded) != len(set(folded)):
        raise AudioAnalysisVerificationError(
            "Audio publication selection contains a portable collision"
        )
    audio = sorted(
        (
            value
            for value in paths
            if AUDIO_PATTERN.match(value)
            and PurePosixPath(value).suffix.casefold() in AUDIO_SUFFIXES
        ),
        key=str.casefold,
    )
    if not audio:
        raise AudioAnalysisVerificationError(
            "Audio publication selection contains no governed runtime audio"
        )
    return audio


def _role_for_path(
    path_value: str,
    roles: dict[str, dict[str, Any]],
) -> str | None:
    candidate = f"/{path_value.casefold()}"
    matches = [
        role_id
        for role_id, role in roles.items()
        if any(str(token).casefold() in candidate for token in role["pathTokens"])
    ]
    return sorted(matches, key=str.casefold)[0] if len(matches) == 1 else None


def _validate_source_state(
    source: Any,
    observed: dict[str, Any],
    label: str,
) -> None:
    if not isinstance(source, dict):
        raise AudioAnalysisVerificationError(f"{label} must be an object")
    if (
        source.get("branch") != "main"
        or source.get("origin") != observed["origin"]
        or source.get("statusSha256Before") != observed["statusSha256"]
        or source.get("statusSha256After") != observed["statusSha256"]
        or source.get("unchanged") is not True
    ):
        raise AudioAnalysisVerificationError(
            f"{label} does not bind the current unchanged repository state"
        )


def _validate_inventory_authority(
    document: dict[str, Any],
    *,
    head: str,
    contract_sha: str,
    selection_sha: str,
    observed_state: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = document.get("files")
    if (
        document.get("schemaVersion") != "1.0"
        or document.get("inventory") != INVENTORY_ID
        or document.get("repository") != TARGET_REPOSITORY
        or document.get("targetHeadSha") != head
        or document.get("contractSha256") != contract_sha
        or document.get("selectionSha256") != selection_sha
        or document.get("mutationPerformed") is not False
        or document.get("publicationAuthority") is not False
        or not isinstance(rows, list)
        or len(rows) > MAXIMUM_PATHS
    ):
        raise AudioAnalysisVerificationError("Audio inventory authority is invalid")
    _validate_source_state(document.get("sourceState"), observed_state, "inventory.sourceState")
    return [dict(row) if isinstance(row, dict) else {} for row in rows]


def _validate_analysis_authority(
    document: dict[str, Any],
    *,
    head: str,
    contract_sha: str,
    selection_sha: str,
    inventory_sha: str,
    observed_state: dict[str, Any],
) -> tuple[list[str], list[dict[str, Any]]]:
    paths = document.get("analyzedPaths")
    rows = document.get("results")
    if (
        document.get("schemaVersion") != "1.0"
        or document.get("report") != ANALYSIS_ID
        or document.get("targetRepository") != TARGET_REPOSITORY
        or document.get("targetHeadSha") != head
        or document.get("contractSha256") != contract_sha
        or document.get("selectionSha256") != selection_sha
        or document.get("inventorySha256") != inventory_sha
        or document.get("status") not in {"passed", "blocked"}
        or document.get("mutationPerformed") is not False
        or document.get("publicationAuthority") is not False
        or document.get("humanListeningApproval") is not False
        or document.get("godotGameplayMixApproval") is not False
        or document.get("provenanceApproval") is not False
        or not isinstance(paths, list)
        or not isinstance(rows, list)
        or len(paths) > MAXIMUM_PATHS
        or len(rows) > MAXIMUM_PATHS
    ):
        raise AudioAnalysisVerificationError(
            "Audio Studio analysis report authority is invalid"
        )
    _validate_source_state(document.get("sourceState"), observed_state, "analysis.sourceState")
    normalized = [
        _portable(value, f"analysis.analyzedPaths[{index}]")
        for index, value in enumerate(paths)
    ]
    if len({value.casefold() for value in normalized}) != len(normalized):
        raise AudioAnalysisVerificationError(
            "Audio analysis paths contain a portable collision"
        )
    return normalized, [dict(row) if isinstance(row, dict) else {} for row in rows]


def _index_rows(
    rows: list[dict[str, Any]],
    *,
    label: str,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    identities: set[str] = set()
    for index, row in enumerate(rows):
        path_value = _portable(row.get("path"), f"{label}[{index}].path")
        identity = path_value.casefold()
        if identity in identities:
            raise AudioAnalysisVerificationError(
                f"{label} contains duplicate path {path_value}"
            )
        identities.add(identity)
        result[path_value] = row
    return result


def _runtime_format_blockers(
    relative: str,
    role: dict[str, Any],
    metadata: dict[str, Any],
) -> list[str]:
    suffix = PurePosixPath(relative).suffix.casefold()
    codec = str(metadata["codec"]).casefold()
    format_name = str(metadata["format"]).casefold()
    if role["runtimeFormat"] == "wav-pcm16":
        if (
            suffix != ".wav"
            or metadata["bitDepth"] != 16
            or not codec.startswith("pcm_s16")
            or "wav" not in format_name
        ):
            return ["runtime-format-mismatch"]
    elif (
        suffix not in {".ogg", ".oga"}
        or codec != "vorbis"
        or "ogg" not in format_name
    ):
        return ["runtime-format-mismatch"]
    return []


def _policy_blockers(
    inventory: dict[str, Any],
    role: dict[str, Any],
    bus: dict[str, Any],
    mastering: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    sample_rate = _integer(inventory.get("sampleRateHz"), "sampleRateHz", minimum=1)
    channels = _integer(inventory.get("channels"), "channels", minimum=1)
    duration = _number(inventory.get("durationSeconds"), "durationSeconds")
    loudness = _number(
        inventory.get("integratedLufs"),
        "integratedLufs",
        allow_none=True,
    )
    true_peak = _number(
        inventory.get("truePeakDbtp"),
        "truePeakDbtp",
        allow_none=True,
    )
    dc_offset = _number(
        inventory.get("dcOffset"),
        "dcOffset",
        allow_none=True,
    )
    clipping = _integer(inventory.get("clippingSamples"), "clippingSamples")
    if sample_rate != int(mastering["masterSampleRateHz"]):
        blockers.append("resample-to-48000-required")
    if channels != (1 if role["channels"] == "mono" else 2):
        blockers.append("channel-layout-mismatch")
    if duration is None or not 0 < duration <= float(role["maximumDurationSeconds"]):
        blockers.append("duration-outside-role-limit")
    if loudness is None:
        blockers.append("integrated-loudness-unavailable")
    elif abs(loudness - float(bus["integratedLoudnessTargetLufs"])) > 3.0:
        blockers.append("integrated-loudness-outside-tolerance")
    if true_peak is None:
        blockers.append("true-peak-unavailable")
    elif true_peak > float(mastering["truePeakCeilingDbtp"]):
        blockers.append("true-peak-ceiling-exceeded")
    if dc_offset is None:
        blockers.append("dc-offset-unavailable")
    elif abs(dc_offset) > float(mastering["dcOffsetAbsoluteMaximum"]):
        blockers.append("dc-offset-exceeded")
    if clipping > int(mastering["clippingSamplesAllowed"]):
        blockers.append("clipping-detected")
    if role["loopRequired"]:
        start = inventory.get("loopStartSamples")
        end = inventory.get("loopEndSamples")
        delta = _number(
            inventory.get("loopBoundarySampleDelta"),
            "loopBoundarySampleDelta",
            allow_none=True,
        )
        if (
            isinstance(start, bool)
            or not isinstance(start, int)
            or isinstance(end, bool)
            or not isinstance(end, int)
            or start < 0
            or end <= start
        ):
            blockers.append("valid-loop-markers-required")
        elif delta is None:
            blockers.append("loop-boundary-audit-unavailable")
        elif delta > float(mastering["maximumLoopBoundarySampleDelta"]):
            blockers.append("loop-boundary-delta-exceeded")
    else:
        leading = _number(inventory.get("leadingSilenceMs"), "leadingSilenceMs")
        trailing = _number(inventory.get("trailingSilenceMs"), "trailingSilenceMs")
        if leading is not None and leading > float(mastering["maximumLeadingSilenceMs"]):
            blockers.append("leading-silence-trim-required")
        if trailing is not None and trailing > float(mastering["maximumTrailingSilenceMs"]):
            blockers.append("trailing-silence-trim-required")
    return blockers
