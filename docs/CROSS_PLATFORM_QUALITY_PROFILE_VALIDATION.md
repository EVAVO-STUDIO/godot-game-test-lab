# Cross-platform quality profile validation

Godot Game Test Lab validates native execution truth for platform-specific quality profiles without allowing one platform profile to weaken another.

## Contract source

The canonical additive profile contract is owned by `EVAVO-STUDIO/godot-web-runtime`:

```text
schemas/game-quality-profile.schema.json
```

A target game may remain native-only. Presence of a profile file is not proof that a web build is supported.

## Required validation model

For every declared profile, evidence must bind:

- exact target repository SHA;
- exact Lab SHA;
- exact Godot editor/export-template identity;
- platform and renderer identity;
- export preset identity;
- profile file SHA-256;
- relevant shader/material/resource identities;
- startup, gameplay and media evidence.

## Native lanes

The Lab owns native Godot evidence for Windows and Linux and can contribute Android/iOS source/export validation where an external device/simulator worker owns final platform execution.

Native profile tests must verify the intended renderer rather than accepting an unintended renderer fallback as success.

Examples:

```text
steam-high        -> Forward+
steam-compat      -> Compatibility
android-balanced  -> Mobile
ios-balanced      -> Mobile
```

The profile matrix is game-specific; undeclared profiles must not be invented by the Lab.

## Web lane separation

Browser-hosted gameplay is executed by EVAVO Godot Web Runtime/Automated Testing, not by pretending native Lab execution is a browser pass.

The Lab may validate the web source/export inputs and compare shared gameplay contracts, but `web-balanced` becomes supported only after the generated export is mounted and exercised in the real browser runtime.

## Parity checks

Quality profiles may differ in presentation only. The Lab should compare profile-bound evidence for accidental changes to:

- collision and navigation authority;
- deterministic rules/data;
- save schema;
- multiplayer protocol/version;
- gameplay-affecting entity IDs;
- objective/progression semantics;
- InputMap action identities where the platform supports them.

Renderer-specific resources may differ while these shared identities remain stable.

## Visual checks

For each executable profile retain representative screenshots/video and detect:

- black or frozen output;
- missing/error materials;
- unexpectedly unlit geometry;
- shadow loss where shadows are required by that profile;
- unreadable UI or clipping;
- gross exposure/tonemapping changes;
- missing required particles/effects;
- profile-specific shader parse/compiler failures.

Machine checks do not replace art-direction review.

## Performance checks

A profile pass should retain bounded frame/performance evidence appropriate to its declared target. Performance failure in a web/low profile does not authorize automatic reduction of the Steam/native high profile.

## Web eligibility truth

The supported lifecycle is:

```text
native-only -> candidate -> supported -> preferred
```

Only retained exact-build evidence may advance `candidate` to `supported`. `preferred` additionally requires maintained regression coverage.

## Release rule

A change intended to improve web compatibility must trigger both:

1. web-profile/browser qualification; and
2. affected native-profile qualification.

This prevents renderer/material/export changes made for the browser from silently degrading the Steam, Android or iOS build.
