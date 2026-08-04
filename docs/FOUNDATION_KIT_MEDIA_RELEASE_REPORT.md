# Foundation Kit exact-head media release report

`foundation_media_release_report` converts one strict Foundation Kit media-plan validation into explicit Development Studio release evidence.

It does not approve creative work or import Godot. It adds a clean current Git HEAD boundary around the existing exact contract/audit/plan checks.

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
  "releaseEvidenceEligible": true,
  "targetMutationPerformed": false,
  "publicationAuthority": false
}
```

The wrapper reads the target Git state before validation and again afterward. It fails when:

- Git state is unavailable;
- the target HEAD is not exact;
- the worktree is dirty;
- HEAD changes during validation;
- the worktree becomes dirty during validation;
- the strict media plan retains blockers or review items.

A strict plan failure still records the exact `targetSha` and `targetClean` state, but sets `releaseEvidenceEligible` to false.

## Development Studio handoff

Development Studio's Foundation Kit production bundle recognises top-level `targetSha` as exact target identity. Use this release report for:

```text
testLabArtPlanReport
```

The report must bind the same target SHA as native Godot evidence, campaign playtests, web evidence when required, human creative approval, human listening approval and the publication selection.

## Truth boundary

A passing exact-head report proves only that:

- the contract, Art Studio audit and work order are exact and coherent;
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
