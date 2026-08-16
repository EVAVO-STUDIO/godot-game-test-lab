# Classic Adventure VGA QA

Godot Game Test Lab can independently admit classic adventure source PNGs before the Linux sandbox imports, builds, exports and interacts with the game.

The checker is intentionally narrow. It validates original, project-owned source art against a repository-owned contract and does not compare against or redistribute commercial game assets.

## Contract

```json
{
  "schemaVersion": "1.0",
  "nativeCanvas": { "width": 320, "height": 200 },
  "assets": [
    {
      "path": "assets/room.png",
      "role": "room-background",
      "width": 320,
      "height": 160,
      "maximumColours": 64,
      "alpha": "opaque",
      "maximumIsolatedVisiblePixelRatio": 0.03
    },
    {
      "path": "assets/actor.png",
      "role": "actor-cel",
      "width": 32,
      "height": 64,
      "maximumColours": 16,
      "alpha": "binary",
      "maximumIsolatedVisiblePixelRatio": 0.02
    }
  ]
}
```

`alpha: opaque` requires every decoded pixel to be fully opaque. `alpha: binary` requires both genuine transparent pixels and fully opaque pixels, rejects partial alpha, and rejects hidden RGB beneath transparent pixels.

The checker validates PNG structure and CRCs through the existing Test Lab image probe, independently decodes 8-bit non-interlaced indexed, RGB and RGBA scanlines, verifies exact dimensions, counts actual RGBA colours and reports a bounded isolated-pixel proxy. The proxy is evidence for technical review, not a substitute for human art direction.

## Command

```bash
python scripts/classic_adventure_vga_qa.py \
  --project /workspace/project \
  --contract /workspace/project/.evavo/classic-adventure-vga.json \
  --output /artifacts/classic-adventure-vga-report.json
```

The command is read-only for the project. It writes only the optional caller-selected report.

## Linux sandbox integration

A caller workflow should pin one exact Godot Game Test Lab commit, run this checker as a source gate, and then invoke `reusable-godot-linux-sandbox.yml` with the same lab SHA. The reusable sandbox remains responsible for Godot import, startup, Linux export, deterministic input journeys, recorded gameplay, checkpoint screenshots, contact sheets, runtime logs and the final agent-readable evidence summary.

## Quality boundary

Passing proves bounded source bytes, dimensions, colour count and alpha mechanics. It does not claim that the scene is attractive, historically authentic, legally cleared, identical to a commercial title or creatively approved. Those decisions remain with Adventure Studio, Art Studio and a named reviewer.
