# EVAVO Game Runtime UI Matrix

This lane executes the real `EVAVO-STUDIO/evavo-game-runtime` Godot project from
the repository root. It is a native Windows visual/UI evidence lane, not a
source-only claim.

## What it proves

For every declared viewport, the reference runtime journey:

- imports and launches through the selected Godot executable;
- traverses splash, main menu, options, lobby, server browser, credits, modal,
  loading and results states;
- drives Godot semantic actions through `Input.parse_input_event`;
- verifies that focus exists and moves where the journey expects;
- records actual `Control` rectangles and detects interactive overlap,
  undersized targets, zero-size targets, off-screen controls, ancestor clipping
  and safe-area violations;
- captures one PNG per checkpoint after `RenderingServer.frame_post_draw`;
- verifies every PNG path, SHA-256, byte count and dimensions;
- records exact Runtime and Test Lab Git SHAs;
- optionally assembles checkpoint PNGs into a small review MP4 with FFmpeg.

Evidence is written outside both repositories by default:

```text
C:\GodotLabEvidence\evavo-game-runtime-ui\<run-id>\<scenario>\
```

This prevents evidence from dirtying either source checkout.

## Run

```powershell
Set-Location C:\GitRepos\godot-game-test-lab
git pull --ff-only origin main

.\scripts\run-evavo-game-runtime-ui.ps1 `
  -GodotPath "$env:LOCALAPPDATA\EVAVO\GodotGameTestLab\engines\<installation>\Godot.exe" `
  -RuntimeRepo "C:\GitRepos\evavo-game-runtime"
```

Use `-SkipVideo` when FFmpeg is unavailable. PNG evidence remains mandatory.
Use `-RequireClean` for an exact clean-checkout admission run.

## Receipts

Each scenario receives:

- `stdout.log` and `stderr.log`;
- import logs;
- `frame_0001.png` through the final checkpoint;
- optional `journey.mp4`;
- `receipt.json`.

The run root receives `summary.json`. The runner fails if Godot exits
non-zero, times out, omits markers, loses required focus, reports geometry
errors, produces too few checkpoints, or produces invalid screenshot evidence.

`validate-evavo-game-runtime-ui-receipt.py` reopens the evidence from disk,
parses the PNG IHDR, recomputes SHA-256 and independently admits or rejects the
receipt.
