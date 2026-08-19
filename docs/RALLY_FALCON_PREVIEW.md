# Rally Falcon isolated Godot preview

This contract prepares and validates the real Godot preview boundary for `falcon-rally-production-v1`. It does **not** render or launch Godot by itself.

The source authority is the independently compiled Rally intake `evavo_rally_falcon_worker_intake_v1`. The preview compiler rechecks that intake's self-hash, exact producer commit and non-operative authority, then re-hashes the actual `model.glb` bytes beneath the retained evidence root. A plan is accepted only when the model bytes still match the Rally intake.

## Compile a preview plan

```powershell
godot-lab-rally-falcon-preview compile `
  --intake <path-to-falcon-intake.json> `
  --evidence-root <retained-falcon-evidence-root> `
  --rally-head <exact-rally-sha> `
  --lab-head <exact-test-lab-sha> `
  --output <new-preview-plan.json>
```

The output is create-only and self-hashed. It binds the exact Rally intake file, its `intakeSha256`, the source worker receipt hash, producer commit, exact `model.glb` hash and byte count, exact Rally head and exact Test Lab head.

## Native repository validation

Use the existing Windows-native validator for repository and engine health:

```powershell
.\scripts\Invoke-GodotLabNativeValidation.ps1 `
  -TargetRepositoryPath C:\GitRepos\godot-462-isometric-rally `
  -ExpectedLabSha <exact-test-lab-sha> `
  -ExpectedTargetSha <exact-rally-sha> `
  -ArtifactPath <unique-external-run-directory> `
  -AllowedArtifactRoot <external-artifact-root> `
  -MinimumGodotVersion 4.6.2
```

That validator requires exact clean repository states, executes real Godot validation, records a create-once native validation receipt, and proves the target repository is unchanged. Its receipt is necessary evidence for Falcon preview admission, but it is not sufficient on its own.

## Falcon-specific preview evidence

A valid `evavo-godot-rally-falcon-preview-receipt-v1` must additionally bind the exact preview plan and candidate model and prove all of the following:

- a real Godot process was used, with an exact executable SHA-256 and Godot version at least 4.6.2;
- the candidate model import was actually attempted and passed;
- the imported resource loaded successfully;
- at least four unique rendered PNG frames are retained and each frame is hash and byte-count bound;
- the Godot preview process exited with code `0`;
- the target Rally checkout remained unchanged;
- the native validation receipt is `passed`, binds the same exact Rally/Test Lab heads, and reports `targetUnchanged=true`.

Synthetic placeholders, fixture-only renders, source-only checks, queued jobs, worker heartbeats and plans without a real Godot process are explicitly insufficient.

Validate retained evidence with:

```powershell
godot-lab-rally-falcon-preview validate-receipt `
  <preview-receipt.json> `
  --plan <preview-plan.json> `
  --evidence-root <retained-falcon-evidence-root> `
  --artifact-root <external-preview-artifact-root>
```

## Authority boundary

Passing this contract means only that exact retained preview evidence is structurally and cryptographically consistent with a real Godot run. It does not grant creative approval, runtime admission, canonical import, scene mutation, physics/collision/gameplay authority, target-repository writes, Git mutation, publication, deployment or client release.

The exact candidate still requires named-human visual review before any canonical/runtime decision. Until the Windows Worker Fabric and real Godot execution channel are available, a valid plan may be compiled but a real Falcon preview receipt cannot truthfully exist.
