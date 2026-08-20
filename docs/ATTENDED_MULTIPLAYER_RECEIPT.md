# Attended multiplayer receipt

`godot-lab-attended-multiplayer` turns one completed exact-SHA multiplayer Test Lab run into a separately verifiable attendance receipt. It does not rerun the game, edit the target repository, approve the experience, publish a build or deploy a release.

## Why this is separate

`godot-lab-multiplayer-qa` already owns deterministic runtime execution. It launches two to eight role journeys concurrently beneath one guarded Windows desktop lease, retains per-role media and logs, and rechecks the exact target checkout after execution.

The attended route starts only after that run has completed. It:

1. reopens `multiplayer-agent-summary.json`;
2. requires a passed exact Lab SHA and target SHA;
3. rebuilds the complete retained-artifact inventory;
4. rehashes every retained evidence file;
5. requires the interactive Windows session and guarded desktop lease recorded by the run;
6. requires every role process, harness and visual result to have passed;
7. binds a same-session operator attendance attestation;
8. creates a source-bound receipt outside the original artifact root.

The operator identity comes from the current Windows principal. This is attribution evidence, not cryptographic identity proof.

## Attendance

Attendance is created from a real terminal in the same nonzero Windows session as the completed run. Explorer must be running in that session. The operator must type:

```text
ATTEND <run-id>
```

The attestation must be created within 30 minutes of the run timestamp and is valid for four hours and fifteen minutes. It records `automated: false`, but attendance is not human visual or game-feel approval. It also does not certify physical controllers, Steam Input, rumble, latency, packet loss, disconnect recovery or complete multiplayer correctness.

## Commands

First create a unique output path outside the retained multiplayer artifact directory:

```powershell
godot-lab-attended-multiplayer attest `
  --summary C:\GodotLabEvidence\run-001\multiplayer-agent-summary.json `
  --artifacts C:\GodotLabEvidence\run-001 `
  --campaign-id game-multiplayer-campaign-001 `
  --output C:\GodotLabEvidence\attestations\run-001.json
```

Then compile a create-only receipt:

```powershell
godot-lab-attended-multiplayer compile `
  --summary C:\GodotLabEvidence\run-001\multiplayer-agent-summary.json `
  --artifacts C:\GodotLabEvidence\run-001 `
  --attestation C:\GodotLabEvidence\attestations\run-001.json `
  --output C:\GodotLabEvidence\receipts\run-001.json
```

Reverify the receipt against the original exact bytes:

```powershell
godot-lab-attended-multiplayer verify `
  --summary C:\GodotLabEvidence\run-001\multiplayer-agent-summary.json `
  --artifacts C:\GodotLabEvidence\run-001 `
  --attestation C:\GodotLabEvidence\attestations\run-001.json `
  --receipt C:\GodotLabEvidence\receipts\run-001.json
```

## Fail-closed boundaries

The route rejects changed bytes, changed file sizes, missing files, symlinks, path traversal, duplicate inventory paths, stale or wrong-session attestations, noninteractive execution, target mutation, failed roles, failed visual evidence and existing output files.

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

A passing receipt can be admitted into the broader EVAVO evidence chain. It cannot become a release decision by itself and does not publish or deploy anything.
