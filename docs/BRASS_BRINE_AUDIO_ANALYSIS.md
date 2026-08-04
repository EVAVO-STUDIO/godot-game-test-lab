# Brass & Brine audio-analysis verification

Godot Game Test Lab independently validates the exact Audio Studio evidence for audio selected in a Brass & Brine publication.

The verifier consumes:

```text
EVAVO Audio Studio production contract
Development Studio publication selection
Audio Studio exact inventory
Audio Studio analysis report
current Brass & Brine runtime audio
current Godot import sidecars
```

It emits:

```text
evavo_brass_brine_audio_test_lab_report_v1
```

## Command line

```powershell
python -m godot_game_test_lab.audio_analysis `
  C:\GitRepos\Brass_Brine `
  C:\GitRepos\evavo-audio-studio\migration\brass-brine-audio\brass_brine_audio_production_contract_v1.json `
  C:\EVAVO-Evidence\Brass_Brine\audio-selection.json `
  C:\EVAVO-Evidence\Brass_Brine\audio-inventory.json `
  C:\EVAVO-Evidence\Brass_Brine\audio-analysis.json `
  --strict `
  --evidence-root C:\EVAVO-Evidence\Brass_Brine `
  --output test-lab-audio-analysis.json
```

Evidence output is create-only. The evidence root must remain disjoint from the game and Test Lab source roots.

## Independent checks

The gate verifies:

- exact current `EVAVO-STUDIO/Brass_Brine` `main` head and unchanged Git status;
- duplicate-key-safe UTF-8 JSON for the contract, selection, inventory and analysis report;
- exact contract, selection, inventory and Audio Studio report SHA-256 binding;
- equality of selected audio paths across every evidence document;
- current runtime SHA-256 and byte length;
- role, bus and runtime-format coherence;
- independent WAV metadata through Python's standard-library decoder;
- compressed audio metadata through the fixed system `ffprobe` executable;
- sample rate, bit depth, channels and duration;
- contract-owned loudness, true-peak, clipping, DC, silence and loop policy;
- current Godot `.import` source identity, PCM policy and loop settings;
- a second read of all retained evidence, runtime audio, import sidecars and Git state.

A generic `{ "status": "passed" }` document cannot satisfy the gate.

## MCP

The root-restricted MCP entry point is:

```powershell
$env:EVAVO_GODOT_LAB_ALLOWED_ROOTS = "C:\GitRepos"
$env:EVAVO_GODOT_AUDIO_CONTRACT_ROOTS = "C:\GitRepos\evavo-audio-studio"
$env:EVAVO_GODOT_LAB_EVIDENCE_ROOT = "C:\EVAVO-Evidence\Brass_Brine"
python -m godot_game_test_lab.audio_analysis_mcp
```

It exposes:

```text
godot_audio_analysis_capabilities
godot_validate_audio_analysis
```

The MCP accepts no arbitrary shell command, Git argument or executable path. It can read allowlisted source roots and create a report below the configured evidence root. It cannot modify game files, grant listening or gameplay-mix approval, commit, push or publish.

## Truth boundary

A passing report establishes independent technical evidence only. It does not grant:

- human listening approval;
- native Godot gameplay-mix approval;
- historical or provenance approval;
- release readiness;
- repository mutation or publication authority.

Those remain separate Development Studio evidence requirements.
