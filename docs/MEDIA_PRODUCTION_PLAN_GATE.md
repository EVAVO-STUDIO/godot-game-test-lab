# Media production plan gate

Godot Game Test Lab can validate a Brass & Brine media production plan against the exact game-owned contract and EVAVO Art Studio audit bytes used to compile it.

This is the bridge between deterministic planning and native acceptance. It does not master images, change a target repository, approve art, publish files or claim that Godot has rendered the media.

## Inputs

```text
Godot project
Brass & Brine media production contract
EVAVO Art Studio repository audit
compiled media production plan
```

The canonical game contract is retained in Brass & Brine:

```text
data/identity/brass_brine_media_production_contract_2026_08_04.json
```

The contract must remain inside the selected project. The audit and plan may be inside the project or the configured external evidence root when accessed through MCP.

## Direct command

Planning validation allows explicit repair and review blockers:

```powershell
python -m godot_game_test_lab.media_production_plan `
  C:\GitRepos\Brass_Brine `
  C:\GitRepos\Brass_Brine\data\identity\brass_brine_media_production_contract_2026_08_04.json `
  C:\EVAVO-Evidence\Brass_Brine\art-audit.json `
  C:\EVAVO-Evidence\Brass_Brine\media-production-plan.json
```

Strict readiness requires no remaining blockers or review items:

```powershell
python -m godot_game_test_lab.media_production_plan `
  C:\GitRepos\Brass_Brine `
  C:\GitRepos\Brass_Brine\data\identity\brass_brine_media_production_contract_2026_08_04.json `
  C:\EVAVO-Evidence\Brass_Brine\art-audit.json `
  C:\EVAVO-Evidence\Brass_Brine\media-production-plan.json `
  --strict `
  --output C:\EVAVO-Evidence\Brass_Brine\media-plan-validation.json
```

The direct command uses the same stable descriptor, strict duplicate-key JSON and final identity recheck boundaries as the asset-audit gate. Reports are create-only when `--output` is supplied.

## Exact checks

The gate verifies:

- project and `project.godot` identity;
- game contract schema, repository, Godot version and batch safety boundaries;
- game contract SHA-256 recorded by the plan;
- Art Studio audit SHA-256 recorded by the plan;
- complete strict Art Studio audit authority;
- portable, unique and deterministic source paths;
- source SHA-256 and byte length for every work item;
- exact audit findings retained from every audited row;
- role existence in the game contract;
- exact runtime root, runtime format, canvas, alpha, fit, Godot import and stage contracts;
- optional runtime target containment beneath the role-owned root;
- unique action, blocker and audit-finding arrays;
- review state derived from actual blockers and findings;
- recomputed work-item, role, blocker, review and blocked counts;
- stable target Git state before and after validation;
- final byte rechecks for contract, audit and plan;
- all-false deletion and publication authority;
- retained human creative approval boundary.

Strict mode adds:

```text
blocked work items = 0
review-required work items = 0
```

Planning mode remains useful earlier in the pipeline. It can return `passed` with a warning while clearly retaining the work that still needs repair or review.

## MCP tools

The root-restricted asset-audit server exposes:

```text
godot_validate_art_audit
godot_validate_media_production_plan
```

Example plan call:

```text
target: C:\GitRepos\Brass_Brine
audit: C:\EVAVO-Evidence\Brass_Brine\art-audit.json
plan: C:\EVAVO-Evidence\Brass_Brine\media-production-plan.json
contract: data/identity/brass_brine_media_production_contract_2026_08_04.json
strict: false
```

The server confines target projects to configured roots. The contract must stay in the selected Git root. Audit and plan files must stay in that Git root or the configured evidence root. Links, reparse points and path escapes fail closed.

## Acceptance routes

The result derives one route for every planned role. Image roles include the native capture matrix:

```text
1280×720  native gameplay surface
1920×1080 desktop scale review
1366×768  compact desktop review
```

Routes also declare whether the role needs:

- hostile light and dark alpha-edge review;
- motion capture and sequence review;
- audio analysis;
- human listening;
- role-specific native acceptance stages.

These are requirements, not completed evidence.

## Truth boundary

A passing planning report proves that the plan is coherent with the exact contract and audit. It does not prove:

- image or audio mastering quality;
- Godot import success;
- native Windows rendering;
- animation feel;
- browser rendering;
- audio mix quality;
- human creative approval;
- publication or release readiness.

Continue with strict asset-audit validation, matching-editor Godot import, native journeys, retained captures, browser review where applicable, audio listening and the signed Development Studio publication transaction.
