# Attended multiplayer receipt

`python -m godot_game_test_lab.attended_multiplayer` turns one completed exact-SHA multiplayer Test Lab run into a separately verifiable attendance receipt. It does not rerun the game, edit the target repository, approve the experience, publish a build or deploy a release.

## Why this is separate

`godot-lab-multiplayer-qa` owns the guarded runtime execution. It launches two to eight role journeys beneath one guarded Windows desktop lease, retains per-role media and logs, and rechecks the exact target checkout after execution. The launcher emits `EVAVO_MULTIPLAYER_AGENT_QA=PASS` only for an interactive native run whose process summary and retained `multiplayer-agent-summary.json` agree on the exact run ID, Lab SHA, target SHA and session label. `-AllowNonInteractive` is contract testing only and emits `EVAVO_MULTIPLAYER_AGENT_QA=CONTRACT_ONLY`; it cannot emit the native PASS marker.

The attended route starts only after an interactive run has completed. It:

1. reopens `multiplayer-agent-summary.json`;
2. requires a passed exact Lab SHA and target SHA;
3. rebuilds the complete retained-artifact inventory;
4. rehashes every retained evidence file;
5. independently reopens and cross-checks `run-context.json`, `hardware.json`, `source-archive.json`, `validation/report.json` and `profile.normalized.json`;
6. requires the interactive Windows session and guarded desktop lease recorded by the run;
7. requires every role process, harness and visual result to have passed;
8. binds the same-session operator attendance attestation to the exact summary SHA-256, artifact-inventory SHA-256, artifact count and artifact byte total;
9. creates a source-bound receipt outside the original artifact root.

The operator identity comes from the current Windows principal. This is attribution evidence, not cryptographic identity proof.

## Attendance

Attendance is created from a real terminal in the same nonzero Windows session as the completed run. Explorer must be running in that session. The operator must type:

```text
ATTEND <run-id>
```

The attestation must be created within 30 minutes of the run timestamp and is valid for four hours and fifteen minutes. It records `automated: false`, but attendance is not human visual or game-feel approval. Because the attestation is bound to the exact retained summary and rehashed artifact inventory, it cannot be reused for altered evidence that merely retains the same run ID and source SHAs.

## Commands

The canonical dependency-free source-checkout entrypoint is the Python module. First create a unique output path outside the retained multiplayer artifact directory:

```powershell
python -m godot_game_test_lab.attended_multiplayer attest `
  --summary C:\GodotLabEvidence\run-001\multiplayer-agent-summary.json `
  --artifacts C:\GodotLabEvidence\run-001 `
  --campaign-id game-multiplayer-campaign-001 `
  --output C:\GodotLabEvidence\attestations\run-001.json
```

Then compile a create-only receipt:

```powershell
python -m godot_game_test_lab.attended_multiplayer compile `
  --summary C:\GodotLabEvidence\run-001\multiplayer-agent-summary.json `
  --artifacts C:\GodotLabEvidence\run-001 `
  --attestation C:\GodotLabEvidence\attestations\run-001.json `
  --output C:\GodotLabEvidence\receipts\run-001.json
```

Reverify the receipt against the original exact bytes:

```powershell
python -m godot_game_test_lab.attended_multiplayer verify `
  --summary C:\GodotLabEvidence\run-001\multiplayer-agent-summary.json `
  --artifacts C:\GodotLabEvidence\run-001 `
  --attestation C:\GodotLabEvidence\attestations\run-001.json `
  --receipt C:\GodotLabEvidence\receipts\run-001.json
```

Installed console aliases may be introduced only through the repository-owned package and toolchain authorities. Callers must not assume an alias that is absent from the exact installed package.

## Fail-closed boundaries

The route rejects changed bytes, changed file sizes, missing files, symlinks, path traversal, duplicate inventory paths, stale or wrong-session attestations, evidence-digest substitution, run-context/summary disagreement, retained hardware disagreement, failed retained validation reports, malformed source-archive receipts, noninteractive execution, target mutation, failed roles, failed visual evidence and existing output files.

The receipt deliberately keeps all of these claims false:

- deterministic release-verdict authority;
- human visual approval;
- human game-feel approval;
- physical-controller certification;
- real-network-condition certification;
- complete gameplay coverage;
- release approval;
- source-mutation authority;
- deployment authority;
- publication authority.

A passing receipt proves that the exact synthetic role journeys and retained evidence were attended. It does **not** by itself prove that every peer exchanged authoritative gameplay state, that packet-loss/reconnect behavior is correct, or that the game is ready to ship. Those conclusions require explicit game-specific assertions and/or broader runtime acceptance evidence.
