# Foundation Kit media production-plan gate

Godot Game Test Lab validates final-art and final-audio production plans for `EVAVO-STUDIO/GodotGameFoundationKit` against the exact game-owned contract and EVAVO Art Studio audit bytes used to compile them.

The gate is read-only for the target repository. It does not create art or audio, import assets, launch Godot, approve creative work, delete files, commit or publish.

## Authorities

```text
GodotGameFoundationKit
  owns roles, authored canvases, import policy and final acceptance

EVAVO Art Studio
  owns inventory, role classification, deterministic mastering and art QA

EVAVO Audio Studio
  owns audio audit, mastering and listening evidence

Godot Game Test Lab
  owns exact-byte plan validation, Godot import and native capture

Godot Web Runtime
  owns browser export, capability, input, accessibility and performance review

EVAVO Development Studio
  owns governed orchestration and sealed non-forced Git/LFS publication
```

The canonical contract is:

```text
examples/playable_foundation_hub/data/
  foundation_kit_media_production_contract_v1.json
```

## Direct command

Planning validation may retain explicit repair or review work:

```powershell
python -m godot_game_test_lab.foundation_media_plan `
  C:\GitRepos\GodotGameFoundationKit `
  C:\GitRepos\GodotGameFoundationKit\examples\playable_foundation_hub\data\foundation_kit_media_production_contract_v1.json `
  C:\EVAVO-Evidence\GodotGameFoundationKit\art-audit.json `
  C:\EVAVO-Evidence\GodotGameFoundationKit\media-production-plan.json
```

Strict readiness requires no remaining blockers or review items:

```powershell
python -m godot_game_test_lab.foundation_media_plan `
  C:\GitRepos\GodotGameFoundationKit `
  C:\GitRepos\GodotGameFoundationKit\examples\playable_foundation_hub\data\foundation_kit_media_production_contract_v1.json `
  C:\EVAVO-Evidence\GodotGameFoundationKit\art-audit.json `
  C:\EVAVO-Evidence\GodotGameFoundationKit\media-production-plan.json `
  --strict `
  --output C:\EVAVO-Evidence\GodotGameFoundationKit\media-plan-validation.json
```

## Exact checks

The gate verifies:

- project and `project.godot` identity;
- contract schema, repository, Godot 4.6.2 identity and safety boundaries;
- the five authored surfaces: HUB 640×480 and four 640×400 games;
- contract SHA-256 and Art Studio audit SHA-256 recorded by the plan;
- stable current audit and plan bytes;
- complete Godot Art Studio audit authority;
- portable unique deterministic source paths;
- source SHA-256 and byte length for every work item;
- role-owned runtime root, format, canvas, alpha, fit and Godot import policy;
- runtime target containment beneath the role-owned root;
- exact blocker, review, role and summary counts;
- stable target Git state before and after validation;
- all-false publication and deletion authority;
- retained human creative and listening approval.

Strict mode additionally requires:

```text
blocked work items = 0
review-required work items = 0
```

## Native acceptance routes

Every image role derives all five authored review surfaces:

```text
HUB       640×480
GODZ      640×400
JONEZ     640×400
SKYFURY   640×400
PIZZA     640×400
```

The route also states whether the role requires:

- hostile light and dark alpha-edge review;
- animation and motion capture;
- audio analysis;
- human listening;
- role-specific native acceptance stages.

Audio roles do not invent image viewports. They require the audio stages from the game contract, including sample-rate, channel, duration, silence, clipping, true peak, loudness, loop, transition, Godot import, gameplay mix and listening review as appropriate.

## MCP and task boundary

Long-running repository audits, plan compilation, native captures and listening batches should be represented as cancellable MCP Tasks with progress notifications. Agents receive a task handle and evidence resources, not arbitrary shell or Git arguments.

The target and contract must remain beneath configured repository roots. Audit, plan and retained reports may remain beneath the configured evidence root. The gate grants no target write or publication authority.

## Truth boundary

A passing report proves that one plan is coherent with one exact Foundation Kit contract and one exact Art Studio audit. It does not prove:

- artistic quality or historical authenticity;
- native Godot import or rendering;
- animation feel;
- browser compatibility;
- audio mix quality;
- human creative or listening approval;
- publication or release readiness.

Continue through strict Art Studio evidence, Audio Studio analysis, matching-editor Godot import, native journeys, browser review where relevant, retained captures, human approval and Development Studio’s signed publication transaction.
