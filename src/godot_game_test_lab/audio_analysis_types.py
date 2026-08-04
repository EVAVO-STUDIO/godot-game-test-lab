from __future__ import annotations

import re

TARGET_REPOSITORY = "EVAVO-STUDIO/Brass_Brine"
CONTRACT_ID = "evavo_brass_brine_audio_production_contract_v1"
SELECTION_ID = "evavo_brass_brine_audio_selection_v1"
INVENTORY_ID = "evavo_brass_brine_audio_inventory_v1"
ANALYSIS_ID = "evavo_brass_brine_audio_analysis_report_v1"
REPORT_ID = "evavo_brass_brine_audio_test_lab_report_v1"
CHECK_ID = "brass-brine-audio-analysis"
MAXIMUM_JSON_BYTES = 64 * 1024 * 1024
MAXIMUM_AUDIO_BYTES = 2 * 1024 * 1024 * 1024
MAXIMUM_PATHS = 100_000
HEAD_PATTERN = re.compile(r"^[a-f0-9]{40}$")
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
AUDIO_PATTERN = re.compile(r"^(?:assets|game/assets|src/assets)/audio/", re.I)
AUDIO_SUFFIXES = frozenset({".wav", ".ogg", ".oga", ".flac", ".mp3"})
ORIGIN_PATTERN = re.compile(
    r"(?:github\.com[:/])EVAVO-STUDIO/Brass_Brine(?:\.git)?$",
    re.I,
)
RESERVED_PATTERN = re.compile(
    r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$",
    re.I,
)
EXPECTED_BUS_IDS = ("UI", "SFX", "Ambience", "Music", "Voice")
EXPECTED_ROLE_IDS = (
    "ui-cue",
    "personal-weapon-sfx",
    "naval-combat-sfx",
    "ship-mechanical-sfx",
    "port-ambience",
    "interior-ambience",
    "sea-ambience",
    "weather-ambience",
    "music-state",
    "voice-line",
)


class AudioAnalysisVerificationError(RuntimeError):
    """Raised when retained Brass audio evidence cannot be admitted safely."""
