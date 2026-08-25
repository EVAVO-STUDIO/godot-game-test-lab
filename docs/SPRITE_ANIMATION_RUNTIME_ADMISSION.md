# Sprite animation runtime admission

Godot Game Test Lab provides a generic runtime-admission contract for sprite animations produced outside the Lab. The target game owns the actual fixture or journey. The Lab verifies exact runtime evidence without becoming animation-production or creative-approval authority.

## Evidence chain

```text
Art Studio Animation Director plan
-> generated/repaired frame artifacts
-> atlas + Godot SpriteFrames descriptor
-> Art Studio descriptor acceptance
-> self-hashed runtime expectation
-> target-owned AnimatedSprite2D probe scene
-> raw runtime telemetry outside the target checkout
-> Test Lab evidence compilation
-> Test Lab runtime admission report
-> separate screenshot/movie/human visual review
```

The documents are:

```text
evavo.godot-sprite-animation-runtime-expectation.v1
evavo.godot-sprite-animation-runtime-evidence.v1
evavo.godot-sprite-animation-runtime-admission.v1
```

The expectation binds the exact Animation Director plan SHA-256 and persisted Godot descriptor SHA-256 plus the clip ID, ordered frame IDs, integer-microsecond per-frame durations, FPS, loop mode, observed-cadence tolerance, pivot tolerance and an all-false authority record.

## Configured timing versus observed cadence

These are deliberately separate evidence boundaries.

The target probe reads the actual loaded `SpriteFrames` resource and checks:

```text
get_animation_speed()
get_frame_duration()
get_animation_loop_mode()
get_frame_count()
```

Configured FPS and absolute per-frame durations must match the Art Studio expectation exactly. This is the authoritative runtime-configuration timing check.

The probe also measures wall-clock time between `AnimatedSprite2D.frame_changed` events. Desktop scheduling and rendering can move an event by a render tick, so this is a runtime-health measurement rather than the authored timing source of truth. Art Studio defaults the observed-cadence tolerance to 20 ms; a controlled lane may explicitly request a stricter integer tolerance.

## Target-owned reference probe

Darkworld's cinematic-platformer example owns the reusable target probe scene:

```text
res://examples/cinematic_precision_platformer/animation/sprite_animation_runtime_probe.tscn
```

The probe requires an EVAVO-generated `SpriteFrames` resource containing the importer metadata:

```text
evavo_frame_metadata
evavo_animation_metadata
```

It consumes only explicit environment variables:

```text
EVAVO_SPRITE_ANIMATION_RAW_TELEMETRY
EVAVO_SPRITE_ANIMATION_RESOURCE
EVAVO_SPRITE_ANIMATION_CLIP
EVAVO_SPRITE_ANIMATION_CYCLES
```

The raw telemetry output must be an external filesystem path. `res://`, `user://` and pre-existing outputs are rejected.

Example native invocation:

```powershell
$Evidence = "C:\GodotLabEvidence\darkworld\sprite-walk-001"
New-Item -ItemType Directory -Force $Evidence | Out-Null

$env:EVAVO_SPRITE_ANIMATION_RAW_TELEMETRY = "$Evidence\raw-telemetry.json"
$env:EVAVO_SPRITE_ANIMATION_RESOURCE = "res://art/generated/hero.sprite_frames.tres"
$env:EVAVO_SPRITE_ANIMATION_CLIP = "walk-right"
$env:EVAVO_SPRITE_ANIMATION_CYCLES = "2"

godot --path C:\GitRepos\godot-462-darkworld-cinematic-platformer `
  res://examples/cinematic_precision_platformer/animation/sprite_animation_runtime_probe.tscn
```

Authoritative Test Lab runs should use the exact managed Godot executable selected for the target instead of relying on a PATH alias.

## Compile and admit raw telemetry

The installed Test Lab exposes:

```text
godot-lab-sprite-animation
```

Run it after Art Studio has produced the runtime expectation and the target probe has written raw telemetry:

```powershell
godot-lab-sprite-animation `
  --expectation "$Evidence\runtime-expectation.json" `
  --raw-telemetry "$Evidence\raw-telemetry.json" `
  --evidence-output "$Evidence\runtime-evidence.json" `
  --report-output "$Evidence\runtime-admission.json"
```

The command normalizes raw telemetry, binds it to the exact expectation SHA-256, writes a self-hashed evidence document, runs admission, and writes the report. Outputs are create-only and cannot overwrite either input.

## Admission requirements

A pass requires:

- valid expectation self-hash and run ID;
- valid runtime-evidence self-hash and run ID;
- runtime evidence bound to the exact expectation SHA-256;
- Godot 4.6.2 or a later compatible 4.x version;
- `SpriteFrames` loaded and animation started;
- exact configured FPS;
- exact ordered frame IDs;
- exact configured per-frame duration microseconds;
- exact expected loop mode;
- every expected frame observed after a completed render frame;
- observed wall-clock cadence within the explicit tolerance;
- pivot stability inside the explicit tolerance;
- at least one complete cycle for a looping clip;
- no retained import or console errors.

## Truth boundary

A passing report proves that the exact animation package was configured and exercised consistently with its expectation in the runtime lane that produced the telemetry.

It does **not** prove:

- the animation looks good;
- animation craft, acting or game feel are approved;
- silhouettes or style match creative intent;
- atlas filtering is visually correct on every display/GPU;
- native Windows GPU evidence unless that lane actually ran;
- a physical controller was tested;
- the asset is approved, promoted, published or deployed.

Use Test Lab screenshots/movie checkpoints plus separate visual/creative review for those questions. Runtime telemetry and human visual approval must never be collapsed into one claim.
