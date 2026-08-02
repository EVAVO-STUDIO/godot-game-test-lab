# MCP Agent Bridge

`godot-lab-mcp` connects Chat, Claude, Development Studio and other MCP clients
to the local Godot Game Test Lab. It gives an agent bounded tools to inspect,
build, run, play, see and hear a Godot game in another repository while keeping
the target source read-only.

## What the bridge exposes

The MCP server provides tools for:

- toolchain and GPU/audio diagnostics;
- project inventory and corruption audits;
- C# compilation, Godot import, recovery diagnosis and bounded startup;
- generated bot-profile proposals outside the target repository;
- target-authored native journeys;
- deterministic mouse, keyboard, semantic-action and synthetic-gamepad bot QA;
- screenshots, checkpoints, waveforms and spectrograms returned as MCP image
  content;
- bounded WAV, FLAC, OGG and MP3 evidence returned as MCP audio content;
- objective audio metrics, including mean and peak dBFS, integrated loudness,
  loudness range, true peak, silence segments and audio/video duration drift;
- compact run summaries, exact traces and bounded artifact browsing.

The server defaults to MCP `stdio`, which is the safest local client transport.
It can also use Streamable HTTP, but only on an explicit loopback host.

## Install

```powershell
Set-Location C:\GitRepos\godot-game-test-lab

git pull --ff-only origin main
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --disable-pip-version-check -e ".[dev,agent]"

godot-lab-mcp `
  --lab-root C:\GitRepos\godot-game-test-lab `
  --allowed-root C:\GitRepos `
  --evidence-root C:\GodotLabEvidence `
  --self-test
```

The `agent` extra pins the production MCP Python SDK v1 line. Core validation,
bot and media code remain dependency-free and usable without MCP installed.

FFmpeg and FFprobe must be on `PATH` for synchronized sound extraction,
waveforms, spectrograms and loudness/silence analysis.

## Generate a client configuration

```powershell
.\scripts\Write-GodotLabMcpConfig.ps1 `
  -AllowedTargetRoots C:\GitRepos `
  -EvidenceRoot C:\GodotLabEvidence `
  -OutputPath C:\GodotLabEvidence\mcp\godot-lab-mcp.json
```

The generated JSON is a standalone `mcpServers` snippet. Review it and merge it
into the relevant Claude Desktop, Claude Code, Chat or Development Studio MCP
configuration. The generator does not overwrite an existing client
configuration implicitly.

A typical server entry is:

```json
{
  "mcpServers": {
    "evavo-godot-game-test-lab": {
      "command": "C:\\GitRepos\\godot-game-test-lab\\.venv\\Scripts\\python.exe",
      "args": [
        "-m",
        "godot_game_test_lab.mcp_server",
        "--transport",
        "stdio",
        "--lab-root",
        "C:\\GitRepos\\godot-game-test-lab",
        "--allowed-root",
        "C:\\GitRepos",
        "--evidence-root",
        "C:\\GodotLabEvidence"
      ]
    }
  }
}
```

## Agent workflow

A strong agent sequence is:

1. `godot_capabilities`
2. `godot_doctor`
3. `godot_inspect`
4. `godot_audit`
5. `godot_validate`
6. `godot_propose_bot_profile` when the game has no committed profile
7. commit the reviewed profile through the target repository's own governed
   change process
8. `godot_run_bot_qa` or `godot_run_native_qa`
9. `godot_review_run`
10. `godot_view_image` for final checkpoints, screenshots, waveforms and
    spectrograms
11. `godot_hear_audio` for a bounded audio preview
12. use the exact failing trace and engine/build evidence to plan a separate
    target-repository repair

The run tools automatically scan retained gameplay movies for synchronized
audio evidence after execution. A target can govern audio expectations through
the tool's `media_policy`, including:

```json
{
  "requireAudioTrack": true,
  "failOnSilence": true,
  "failOnClipping": true,
  "failOnAvSyncDrift": true,
  "silenceNoiseDb": -60,
  "minimumSilenceDurationSeconds": 0.75,
  "maximumSilenceRatio": 0.8,
  "minimumAudiblePeakDbfs": -70,
  "maximumPeakDbfs": -0.1,
  "maximumAvSyncDriftSeconds": 0.25
}
```

## What Chat or Claude can genuinely review

Through the MCP bridge, a capable client can directly receive:

- screenshots and state checkpoints;
- control-tree, focus, overlap and clipping telemetry;
- exact mouse, keyboard, semantic and synthetic-gamepad traces;
- Godot, .NET and process logs;
- recorded gameplay audio previews;
- audio waveform and frequency spectrogram images;
- silence, loudness, peak and A/V-duration diagnostics;
- requested renderer, rendering driver and GPU-index evidence.

This lets the model correlate what it sees and hears with the exact input trace
and engine output. It is substantially stronger than source inspection or a
headless startup pass alone.

## Security and truth boundaries

- The server accepts targets only beneath explicitly configured roots.
- Evidence is written only beneath the configured external evidence root.
- Exact native and bot runs refuse dirty Lab and target checkouts.
- The target profile must be tracked by the exact target commit.
- The Lab runs an isolated exact-SHA archive copy and never edits the original
  game checkout.
- Only bounded JSON, image and audio artifacts can be returned through MCP.
- Streamable HTTP is loopback-only; use `stdio` by default.
- The interactive native worker must run in Greg's logged-in Windows session,
  not Session 0.
- Synthetic gamepad events prove Godot event routing and InputMap handling, not
  physical controller enumeration, Steam Input, rumble or latency.
- Objective audio analysis can expose silence, clipping, loudness and sync
  defects. It cannot decide whether music, voice, ambience, spatialization or
  the overall mix is artistically good.
- Screenshots, movies and model review support human QA but do not replace final
  human judgment of art direction, accessibility, game feel, pacing or polish.

## Managed engine provisioning

The bridge now owns a separate managed-engine root and auto-provisions the
project-appropriate official Standard or .NET editor when no explicit Godot path
is supplied. `godot_ensure_engine` exposes this as a standalone MCP operation.
Provisioning is governed by `godot-engine-lock.json`, validates
`SHA512-SUMS.txt`, uses portable self-contained mode, installs matching export
templates, verifies the extracted payload digest, and never writes into a game
repository. Start the MCP server with `--no-auto-provision` to require explicit
engine paths, or use `--engine-root` to select a different external cache.

See `docs/MANAGED_GODOT_ENGINES.md` for Windows/Linux setup, estate prewarming,
and offline mirrors.
