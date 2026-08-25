# Sprite Animation Runtime Admission

Godot Game Test Lab provides a generic runtime-admission contract for sprite animations produced outside the Lab. The target game owns the actual fixture or journey. The Lab verifies the resulting telemetry without becoming the animation-production authority.

The admission module is:

```text
src/godot_game_test_lab/sprite_animation_runtime_admission.py
```

It compares two self-hashed documents:

```text
evavo.godot-sprite-animation-runtime-expectation.v1
evavo.godot-sprite-animation-runtime-evidence.v1
```

and emits:

```text
evavo.godot-sprite-animation-runtime-admission.v1
```

## Expected chain

```text
Art Studio Animation Director plan
-> reviewed/generated frame artifacts
-> atlas and Godot SpriteFrames descriptor
-> target-owned Godot fixture/journey
-> target-owned runtime telemetry
-> Test Lab runtime admission
```

The expectation binds the exact Animation Director plan SHA-256 and Godot descriptor SHA-256 plus:

- clip ID;
- ordered frame IDs;
- frames per second;
- loop mode;
- maximum per-frame timing error;
- maximum pivot drift;
- an all-false authority record.

The runtime evidence records:

- Godot version and renderer;
- successful SpriteFrames load;
- animation start;
- exact loop mode;
- number of complete cycles observed;
- ordered rendered frame IDs;
- observed duration and pivot for every frame;
- import and console errors;
- an all-false authority record.

Both inputs are canonical self-hashed documents with `runId` derived from the first 20 characters of their SHA-256. Editing either document after evidence capture invalidates admission.

## What a pass proves

A passing report proves, for the exact supplied expectation and runtime evidence:

- the expected clip was observed;
- Godot 4.6.2 or a later compatible 4.x version was reported;
- SpriteFrames loaded and playback started;
- the runtime frame sequence matches the exact expected order;
- every expected frame was rendered;
- timing remains within the declared tolerance;
- pivots remain stable within tolerance;
- looping clips completed at least one observed cycle;
- import and console error arrays are clear.

## Truth boundary

A pass does not prove:

- human visual quality;
- animation craft or game feel;
- identity/style correctness beyond separately retained Art Studio evidence;
- physical controller behaviour;
- native Windows GPU evidence unless the telemetry came from that lane;
- approval, promotion, repository mutation, publication or deployment authority.

Those boundaries remain separate by design.

## Target-owned fixture rule

The Lab must not ship one universal walk-cycle scene and claim that it validates every game. A target repository should provide the scene/journey or stable telemetry hook needed to exercise its actual imported resource, renderer settings and gameplay presentation.

A useful target fixture should expose stable observations for:

```text
clipId
frameId
frame change timestamps
pivot / effective sprite offset
animation start
completed cycles
renderer
import / console errors
```

The same fixture can later add screenshots, movie evidence, actual-scale presentation and game-specific assertions, but those are independent from this structural runtime admission.
