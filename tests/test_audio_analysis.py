from __future__ import annotations

import hashlib
import json
import math
import struct
import subprocess
import wave
from pathlib import Path

import pytest

from godot_game_test_lab.audio_analysis import (
    ANALYSIS_ID,
    INVENTORY_ID,
    REPORT_ID,
    TARGET_REPOSITORY,
    AudioAnalysisVerificationError,
    validate_audio_analysis,
    write_report,
)


def _run(*args: str, cwd: Path) -> str:
    completed = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"{' '.join(args)}\n{completed.stdout}\n{completed.stderr}"
        )
    return completed.stdout.strip()


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_json(path: Path, value: dict[str, object]) -> tuple[bytes, str]:
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return payload, _sha(payload)


def _write_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = 24_000
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(48_000)
        values = bytearray()
        for index in range(frames):
            sample = int(2048 * math.sin(2 * math.pi * 440 * index / 48_000))
            values.extend(struct.pack("<h", sample))
        target.writeframes(bytes(values))


def _contract() -> dict[str, object]:
    role_rows = [
        (
            "ui-cue",
            "UI",
            ["/audio/ui/", "/audio/interface/"],
            "mono",
            1.5,
            False,
            "wav-pcm16",
        ),
        (
            "personal-weapon-sfx",
            "SFX",
            ["/audio/sfx/weapons/", "/audio/combat/personal/"],
            "mono",
            5.0,
            False,
            "wav-pcm16",
        ),
        (
            "naval-combat-sfx",
            "SFX",
            ["/audio/sfx/naval/", "/audio/combat/naval/"],
            "mono",
            8.0,
            False,
            "wav-pcm16",
        ),
        (
            "ship-mechanical-sfx",
            "SFX",
            ["/audio/sfx/ships/", "/audio/ships/mechanical/"],
            "mono",
            12.0,
            False,
            "wav-pcm16",
        ),
        (
            "port-ambience",
            "Ambience",
            ["/audio/ambience/ports/", "/audio/ports/ambience/"],
            "stereo",
            300.0,
            True,
            "ogg-vorbis",
        ),
        (
            "interior-ambience",
            "Ambience",
            ["/audio/ambience/interiors/", "/audio/venues/ambience/"],
            "stereo",
            240.0,
            True,
            "ogg-vorbis",
        ),
        (
            "sea-ambience",
            "Ambience",
            ["/audio/ambience/sea/", "/audio/voyage/ambience/"],
            "stereo",
            300.0,
            True,
            "ogg-vorbis",
        ),
        (
            "weather-ambience",
            "Ambience",
            ["/audio/ambience/weather/", "/audio/weather/ambience/"],
            "stereo",
            300.0,
            True,
            "ogg-vorbis",
        ),
        (
            "music-state",
            "Music",
            ["/audio/music/"],
            "stereo",
            600.0,
            True,
            "ogg-vorbis",
        ),
        (
            "voice-line",
            "Voice",
            ["/audio/voice/", "/audio/dialogue/voice/"],
            "mono",
            30.0,
            False,
            "ogg-vorbis",
        ),
    ]
    roles = [
        {
            "id": role_id,
            "bus": bus,
            "pathTokens": tokens,
            "channels": channels,
            "maximumDurationSeconds": duration,
            "loopRequired": loops,
            "runtimeFormat": runtime,
            "requiredStages": ["godot-import", "human-listening-approval"],
        }
        for role_id, bus, tokens, channels, duration, loops, runtime in role_rows
    ]
    return {
        "schemaVersion": "1.0",
        "contract": "evavo_brass_brine_audio_production_contract_v1",
        "targetRepository": TARGET_REPOSITORY,
        "sourceRepository": "EVAVO-STUDIO/evavo-audio-studio",
        "engine": {
            "name": "Godot",
            "minimumVersion": "4.6.2",
            "scripting": "csharp",
            "renderer": "compatibility",
        },
        "mastering": {
            "masterSampleRateHz": 48_000,
            "maximumRuntimeSampleRateHz": 48_000,
            "losslessMasterFormats": ["wav-pcm24", "flac"],
            "lowLatencyRuntimeFormat": "wav-pcm16",
            "streamingRuntimeFormat": "ogg-vorbis",
            "truePeakCeilingDbtp": -1.0,
            "clippingSamplesAllowed": 0,
            "dcOffsetAbsoluteMaximum": 0.01,
            "maximumLeadingSilenceMs": 50.0,
            "maximumTrailingSilenceMs": 250.0,
            "maximumLoopBoundarySampleDelta": 0.02,
            "recursiveLossyEncodingAllowed": False,
            "automaticPeakNormalizationIsApproval": False,
            "automaticDenoisingIsApproval": False,
        },
        "buses": [
            {"id": "UI", "integratedLoudnessTargetLufs": -20.0},
            {"id": "SFX", "integratedLoudnessTargetLufs": -18.0},
            {"id": "Ambience", "integratedLoudnessTargetLufs": -24.0},
            {"id": "Music", "integratedLoudnessTargetLufs": -20.0},
            {"id": "Voice", "integratedLoudnessTargetLufs": -18.0},
        ],
        "roles": roles,
        "publication": {
            "workOrdersAreCreateOnly": True,
            "publicationAuthority": False,
            "deletionAuthority": False,
            "humanListeningApprovalRequired": True,
            "godotGameplayMixApprovalRequired": True,
            "provenanceApprovalRequired": True,
            "sealedDevelopmentStudioPublicationRequired": True,
            "forcePushAllowed": False,
        },
    }


def _fixture(tmp_path: Path) -> dict[str, Path | str]:
    repository = tmp_path / "Brass_Brine"
    evidence = tmp_path / "evidence"
    repository.mkdir()
    evidence.mkdir()
    (repository / "project.godot").write_text(
        '[application]\nconfig/name="Brass & Brine"\n',
        encoding="utf-8",
    )
    audio_relative = "assets/audio/ui/confirm.wav"
    audio_path = repository.joinpath(*audio_relative.split("/"))
    _write_wav(audio_path)
    import_path = Path(f"{audio_path}.import")
    import_path.write_text(
        '[remap]\nimporter="wav"\n'
        '[deps]\nsource_file="res://assets/audio/ui/confirm.wav"\n'
        '[params]\ncompress/mode=0\nforce/8_bit=false\nforce/mono=false\n'
        'force/max_rate=false\nedit/trim=false\nedit/normalize=false\n'
        'edit/loop_mode=0\n',
        encoding="utf-8",
    )
    _run("git", "init", "-b", "main", cwd=repository)
    _run("git", "config", "user.name", "Test", cwd=repository)
    _run("git", "config", "user.email", "test@example.invalid", cwd=repository)
    _run(
        "git",
        "remote",
        "add",
        "origin",
        "https://github.com/EVAVO-STUDIO/Brass_Brine.git",
        cwd=repository,
    )
    _run("git", "add", ".", cwd=repository)
    _run("git", "commit", "-m", "fixture", cwd=repository)
    head = _run("git", "rev-parse", "HEAD", cwd=repository)
    status_payload = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        ],
        check=True,
        capture_output=True,
    ).stdout
    status_sha = _sha(status_payload)

    contract_path = evidence / "contract.json"
    selection_path = evidence / "selection.json"
    inventory_path = evidence / "inventory.json"
    analysis_path = evidence / "analysis.json"
    _, contract_sha = _write_json(contract_path, _contract())
    _, selection_sha = _write_json(
        selection_path,
        {
            "schemaVersion": "1.0",
            "selection": "evavo_brass_brine_audio_selection_v1",
            "repository": TARGET_REPOSITORY,
            "headSha": head,
            "paths": [audio_relative],
        },
    )
    audio_payload = audio_path.read_bytes()
    audio_sha = _sha(audio_payload)
    import_payload = import_path.read_bytes()
    import_sha = _sha(import_payload)
    source_state = {
        "branch": "main",
        "origin": "https://github.com/EVAVO-STUDIO/Brass_Brine.git",
        "statusSha256Before": status_sha,
        "statusSha256After": status_sha,
        "unchanged": True,
    }
    inventory_row = {
        "path": audio_relative,
        "sha256": audio_sha,
        "bytes": len(audio_payload),
        "sampleRateHz": 48_000,
        "bitDepth": 16,
        "channels": 1,
        "durationSeconds": 0.5,
        "integratedLufs": -20.0,
        "truePeakDbtp": -3.0,
        "rmsDbfs": -20.0,
        "dcOffset": 0.0,
        "leadingSilenceMs": 0.0,
        "trailingSilenceMs": 0.0,
        "clippingSamples": 0,
        "loopStartSamples": None,
        "loopEndSamples": None,
        "loopBoundarySampleDelta": None,
        "codec": "pcm_s16le",
        "format": "wav",
        "role": "ui-cue",
        "bus": "UI",
        "findings": [],
    }
    inventory_doc = {
        "schemaVersion": "1.0",
        "inventory": INVENTORY_ID,
        "repository": TARGET_REPOSITORY,
        "targetHeadSha": head,
        "contractSha256": contract_sha,
        "selectionSha256": selection_sha,
        "sourceState": source_state,
        "files": [inventory_row],
        "mutationPerformed": False,
        "publicationAuthority": False,
    }
    inventory_payload, inventory_sha = _write_json(inventory_path, inventory_doc)
    assert _sha(inventory_payload) == inventory_sha
    metrics = {
        "codec": "pcm_s16le",
        "format": "wav",
        "sampleFormat": "s16",
        "sampleRateHz": 48_000,
        "bitDepth": 16,
        "channels": 1,
        "channelLayout": "mono",
        "durationSeconds": 0.5,
        "tags": {},
        "nonAudioStreams": 0,
        "integratedLufs": -20.0,
        "truePeakDbtp": -3.0,
        "loudnessRangeLu": 0.0,
        "loudnessThresholdLufs": -30.0,
        "dcOffset": 0.0,
        "rmsDbfs": -20.0,
        "samplePeakDbfs": -3.0,
        "peakCount": 0,
        "sampleCount": 24_000,
        "measuredBitDepth": 16,
        "leadingSilenceMs": 0.0,
        "trailingSilenceMs": 0.0,
        "loopStartSamples": None,
        "loopEndSamples": None,
        "loopMarkerSource": None,
        "loopMarkerConflict": False,
        "loopBoundarySampleDelta": None,
        "clippingSamples": 0,
        "bytes": len(audio_payload),
        "godotImport": {
            "path": f"{audio_relative}.import",
            "present": True,
            "sha256": import_sha,
            "bytes": len(import_payload),
            "parameters": {
                "__importer": "wav",
                "__source_file": f"res://{audio_relative}",
                "compress/mode": "0",
                "force/8_bit": "false",
                "force/mono": "false",
                "force/max_rate": "false",
                "edit/trim": "false",
                "edit/normalize": "false",
                "edit/loop_mode": "0",
            },
            "loopStartSamples": None,
            "loopEndSamples": None,
            "loopEnabled": False,
        },
    }
    _write_json(
        analysis_path,
        {
            "schemaVersion": "1.0",
            "report": ANALYSIS_ID,
            "targetRepository": TARGET_REPOSITORY,
            "targetHeadSha": head,
            "contractSha256": contract_sha,
            "inventorySha256": inventory_sha,
            "selectionSha256": selection_sha,
            "status": "passed",
            "analyzedPaths": [audio_relative],
            "results": [
                {
                    "path": audio_relative,
                    "sourceSha256": audio_sha,
                    "runtimeSha256": audio_sha,
                    "sourceRelationship": "selected-runtime-self",
                    "role": "ui-cue",
                    "bus": "UI",
                    "status": "passed",
                    "blockers": [],
                    "metrics": metrics,
                    "requiredStages": [
                        "godot-import",
                        "human-listening-approval",
                    ],
                }
            ],
            "sourceState": source_state,
            "toolchain": {
                "ffprobe": "ffprobe",
                "ffmpeg": "ffmpeg",
            },
            "mutationPerformed": False,
            "publicationAuthority": False,
            "humanListeningApproval": False,
            "godotGameplayMixApproval": False,
            "provenanceApproval": False,
            "truthBoundaries": ["technical only"],
        },
    )
    return {
        "repository": repository,
        "evidence": evidence,
        "contract": contract_path,
        "selection": selection_path,
        "inventory": inventory_path,
        "analysis": analysis_path,
        "audio": audio_path,
        "head": head,
    }


def test_exact_audio_evidence_passes_independent_validation(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    report = validate_audio_analysis(
        fixture["repository"],
        fixture["contract"],
        fixture["selection"],
        fixture["inventory"],
        fixture["analysis"],
        strict=True,
    )
    assert report["report"] == REPORT_ID
    assert report["status"] == "passed"
    assert report["targetHeadSha"] == fixture["head"]
    assert report["summary"] == {
        "selectedPaths": 1,
        "passedPaths": 1,
        "failedPaths": 0,
        "findings": 0,
    }
    assert report["results"][0]["independentMetadata"]["bitDepth"] == 16
    assert report["finalIdentityRecheck"] is True
    assert report["mutationPerformed"] is False
    assert report["publicationAuthority"] is False


def test_current_runtime_drift_fails_before_admission(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    fixture["audio"].write_bytes(fixture["audio"].read_bytes() + b"drift")
    with pytest.raises(
        AudioAnalysisVerificationError,
        match="current unchanged repository state|changed",
    ):
        validate_audio_analysis(
            fixture["repository"],
            fixture["contract"],
            fixture["selection"],
            fixture["inventory"],
            fixture["analysis"],
        )


def test_generic_passed_document_is_rejected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _write_json(fixture["analysis"], {"status": "passed"})
    with pytest.raises(
        AudioAnalysisVerificationError,
        match="analysis report authority",
    ):
        validate_audio_analysis(
            fixture["repository"],
            fixture["contract"],
            fixture["selection"],
            fixture["inventory"],
            fixture["analysis"],
        )


def test_duplicate_json_properties_are_rejected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    fixture["analysis"].write_text(
        '{"status":"passed","status":"blocked"}\n',
        encoding="utf-8",
    )
    with pytest.raises(
        AudioAnalysisVerificationError,
        match="duplicate JSON property",
    ):
        validate_audio_analysis(
            fixture["repository"],
            fixture["contract"],
            fixture["selection"],
            fixture["inventory"],
            fixture["analysis"],
        )


def test_selected_path_omission_fails_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    document = json.loads(fixture["analysis"].read_text(encoding="utf-8"))
    document["analyzedPaths"] = []
    document["results"] = []
    _write_json(fixture["analysis"], document)
    with pytest.raises(
        AudioAnalysisVerificationError,
        match="analyzedPaths do not equal",
    ):
        validate_audio_analysis(
            fixture["repository"],
            fixture["contract"],
            fixture["selection"],
            fixture["inventory"],
            fixture["analysis"],
        )


def test_create_only_report_output_is_root_restricted(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    report = validate_audio_analysis(
        fixture["repository"],
        fixture["contract"],
        fixture["selection"],
        fixture["inventory"],
        fixture["analysis"],
    )
    output = write_report(
        report,
        output=Path("test-lab-audio.json"),
        evidence_root=fixture["evidence"],
        protected_roots=(fixture["repository"],),
    )
    assert output.is_file()
    with pytest.raises(AudioAnalysisVerificationError, match="already exists"):
        write_report(
            report,
            output=Path("test-lab-audio.json"),
            evidence_root=fixture["evidence"],
            protected_roots=(fixture["repository"],),
        )
    with pytest.raises(AudioAnalysisVerificationError, match="below the evidence root"):
        write_report(
            report,
            output=tmp_path / "outside.json",
            evidence_root=fixture["evidence"],
            protected_roots=(fixture["repository"],),
        )
