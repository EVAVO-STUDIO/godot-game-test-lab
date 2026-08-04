# Foundation Kit exact-state media release report

The clean mode remains the **Foundation Kit exact-head media release report** boundary.

`foundation_media_release_report` converts one strict Foundation Kit media-plan validation into explicit Development Studio release evidence.

It does not approve creative work or import Godot. It binds the Art Studio audit and media plan to the current target bytes, exact Git `HEAD`, and one unchanged working-tree state. The command supports two deliberately separate modes:

```text
clean acceptance
  targetClean=true
  publicationCandidateBound=false

publication candidate
  targetClean=false
  publicationCandidateBound=true
  exact dirty working-tree state retained before and after validation
```

## Clean acceptance command

```powershell
python -m godot_game_test_lab.foundation_media_release_report `
  C:\GitRepos\GodotGameFoundationKit `
  C:\GitRepos\GodotGameFoundationKit\examples\playable_foundation_hub\data\foundation_kit_media_production_contract_v1.json `
  C:\EVAVO-Evidence\GodotGameFoundationKit\art-audit.json `
  C:\EVAVO-Evidence\GodotGameFoundationKit\art-production-plan.json `
  --strict `
  --output C:\EVAVO-Evidence\GodotGameFoundationKit\test-lab-clean-report.json
```

Clean mode retains the established boundary:

```json
{
  "schemaVersion": "1.1",
  "targetSha": "<clean current 40-character HEAD>",
  "targetClean": true,
  "exactHeadBound": true,
  "exactWorkingTreeBound": true,
  "publicationCandidateBound": false,
  "currentSourceBound": true,
  "releaseEvidenceEligible": true,
  "targetMutationPerformed": false,
  "publicationAuthority": false
}
```

## Publication-candidate command

Use candidate mode only after the intended media batch exists as exact working-tree changes on local `main` and before Development Studio stages or publishes it:

```powershell
python -m godot_game_test_lab.foundation_media_release_report `
  C:\GitRepos\GodotGameFoundationKit `
  C:\GitRepos\GodotGameFoundationKit\examples\playable_foundation_hub\data\foundation_kit_media_production_contract_v1.json `
  C:\EVAVO-Evidence\GodotGameFoundationKit\art-audit.json `
  C:\EVAVO-Evidence\GodotGameFoundationKit\art-production-plan.json `
  --strict `
  --publication-candidate `
  --output C:\EVAVO-Evidence\GodotGameFoundationKit\test-lab-publication-candidate.json
```

A passing publication-candidate report includes:

```json
{
  "schemaVersion": "1.1",
  "targetSha": "<current base HEAD>",
  "targetClean": false,
  "exactHeadBound": true,
  "exactWorkingTreeBound": true,
  "publicationCandidateBound": true,
  "currentSourceBound": true,
  "releaseEvidenceEligible": true,
  "targetMutationPerformed": false,
  "publicationAuthority": false,
  "sourceState": {
    "before": { "dirty": true, "statusCount": 1 },
    "after": { "dirty": true, "statusCount": 1 },
    "unchanged": true
  },
  "policy": {
    "publicationCandidate": true,
    "requireCleanTarget": false,
    "exactWorkingTreeStateRequired": true
  }
}
```

Candidate mode fails when the target is clean. Clean mode fails when the target is dirty. This prevents an ambiguous report from being reused for the wrong publication model.

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

The role-owned canvas and alpha policy are evaluated again. Any independently required blocker absent from the plan is a release error. Duplicate runtime targets must declare `runtime-target-collision` on every affected work item.

The report retains:

```json
{
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

## Failure boundary

The wrapper reads the complete target Git state before validation and again afterward. It fails when:

- Git state is unavailable;
- the target HEAD is not exact;
- the selected clean/candidate mode does not match the worktree;
- HEAD, status count, status sample, project subpath, or dirty state changes during validation;
- the strict media plan retains blockers or review items;
- the Art Studio audit root differs from the current project;
- the plan audit root differs from the current project or audit;
- a current source path is missing, escaped, unreadable or oversized;
- current source bytes, SHA-256, byte length or extension differ from the plan or audit;
- current PNG structure, dimensions or alpha evidence differ from the audit;
- a current PNG is structurally invalid or cannot be independently probed; or
- the plan omits an exact-canvas, alpha or runtime-target collision blocker required by current target bytes.

The current-file check is independent of plan/audit coherence. A stale audit and stale plan may agree with each other and still fail against current source.

## Development Studio handoff

Development Studio consumes this report as:

```text
testLabArtPlanReport
```

For a real media publication batch, use `--publication-candidate`. Development Studio must separately admit a strict Test Lab asset-audit schema `1.1` report as `testLabAssetAuditReport`, compare both reports to the same base HEAD and exact current working-tree state, and then rerun canonical game-media preflight before sealed publication.

A clean report remains useful for read-only release acceptance, archival review, and downstream evidence that does not need to create a new media commit.

## Output and authority

The output is create-only beneath the configured evidence root. The tool does not write target source, stage files, create commits, push, publish, delete, or approve creative work.

## Truth boundary

A passing exact-state report proves only that:

- the contract, Art Studio audit and work order are exact and coherent;
- the audit root and plan root name the current target project;
- selected current source bytes match the plan and audit;
- independently probed PNG evidence remains valid;
- current role-owned blocker requirements are represented;
- the exact selected Git state remained unchanged; and
- strict plan blockers and review items were absent.

It does not prove final art quality, historical authenticity, Godot import, native rendering, animation feel, audio mix quality, campaign completion, human approval, publication, or provider confirmation.
