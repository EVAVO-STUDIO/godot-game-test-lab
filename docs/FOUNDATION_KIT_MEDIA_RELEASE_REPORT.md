# Foundation Kit exact-head media release report

`foundation_media_release_report` converts one strict Foundation Kit media-plan validation into explicit Development Studio release evidence.

It does not approve creative work or import Godot. It adds a clean current Git HEAD boundary and independently binds the audit and plan to the current target bytes.

## Command

```powershell
python -m godot_game_test_lab.foundation_media_release_report `
  C:\GitRepos\GodotGameFoundationKit `
  C:\GitRepos\GodotGameFoundationKit\examples\playable_foundation_hub\data\foundation_kit_media_production_contract_v1.json `
  C:\EVAVO-Evidence\GodotGameFoundationKit\art-audit.json `
  C:\EVAVO-Evidence\GodotGameFoundationKit\art-production-plan.json `
  --strict `
  --output C:\EVAVO-Evidence\GodotGameFoundationKit\test-lab-art-plan-report.json
```

The output is create-only beneath the configured evidence root.

## Additional release fields

A passing report includes:

```json
{
  "targetSha": "<clean current 40-character HEAD>",
  "targetClean": true,
  "exactHeadBound": true,
  "currentSourceBound": true,
  "releaseEvidenceEligible": true,
  "targetMutationPerformed": false,
  "publicationAuthority": false,
  "currentSourceAuthority": {
    "validatedItems": 1,
    "probedPngItems": 1,
    "requiredBlockers": {},
    "auditRootBound": true,
    "planAuditRootBound": true,
    "currentBytesRechecked": true,
    "currentPngEvidenceRechecked": true
  }
}
```

The wrapper reads the target Git state before validation and again afterward. It fails when:

- Git state is unavailable;
- the target HEAD is not exact;
- the worktree is dirty;
- HEAD changes during validation;
- the worktree becomes dirty during validation;
- the strict media plan retains blockers or review items;
- the Art Studio audit root differs from the current project;
- the plan audit root differs from the current project or audit;
- a current source path is missing, escaped, unreadable or oversized;
- current source bytes, SHA-256, byte length or extension differ from the plan or audit;
- current PNG structure, dimensions or alpha evidence differ from the audit;
- a current PNG is structurally invalid or cannot be independently probed;
- the plan omits an exact-canvas, alpha or runtime-target collision blocker required by current target bytes.

The current file check is independent of plan/audit coherence. A stale audit and a stale plan may agree with each other and still fail because the clean current target files no longer match them.

A strict plan or current-source failure still records the exact `targetSha` and `targetClean` state, but sets `currentSourceBound` and `releaseEvidenceEligible` to false as applicable.

## Current source authority

For every work item the release wrapper reopens the current project file under the selected project root and compares:

```text
current target path
current byte length
current SHA-256
current extension
plan source identity
audit source identity
```

PNG work items receive an independent bounded CRC, structure, dimensions and alpha probe. Non-PNG image roles retain their audit image evidence only after the exact current source bytes match the audit SHA-256 and byte length.

The role-owned canvas and alpha policy are then evaluated again. Any independently required blocker absent from the plan is a release error. Duplicate runtime targets must declare `runtime-target-collision` on every affected work item.

## Development Studio handoff

Development Studio's Foundation Kit production bundle recognises top-level `targetSha` as exact target identity and separately requires `currentSourceBound=true`. Use this release report for:

```text
testLabArtPlanReport
```

The report must bind the same target SHA as native Godot evidence, campaign playtests, web evidence when required, human creative approval, human listening approval and the publication selection.

## Truth boundary

A passing exact-head report proves only that:

- the contract, Art Studio audit and work order are exact and coherent;
- the audit root and plan root name the current target project;
- the selected current source bytes match the plan and audit;
- independently probed PNG evidence remains valid;
- current role-owned blocker requirements are represented;
- the selected target repository was clean;
- the target HEAD remained unchanged;
- strict plan blockers and review items were absent.

It does not prove:

- final art quality;
- historical authenticity;
- Godot import;
- native rendering or animation feel;
- audio mix quality;
- full campaign completion;
- human approval;
- publication or provider confirmation.
