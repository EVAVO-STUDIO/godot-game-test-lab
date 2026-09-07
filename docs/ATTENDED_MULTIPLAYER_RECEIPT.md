# Attended multiplayer receipt

`python -m godot_game_test_lab.attended_multiplayer` turns one completed exact-SHA multiplayer Test Lab run into a separately verifiable attendance receipt. It does not rerun the game, edit the target repository, approve the experience, publish a build or deploy a release.

## Why this is separate

`godot-lab-multiplayer-qa` owns the guarded runtime execution. It launches two to eight role journeys beneath one guarded Windows desktop lease, retains per-role media and logs, and rechecks the exact target checkout after execution. The launcher emits `EVAVO_MULTIPLAYER_AGENT_QA=PASS` only for an interactive native run whose process summary and retained `multiplayer-agent-summary.json` agree on the exact run ID, Lab SHA, target SHA and session label. `-AllowNonInteractive` is contract testing only and emits `EVAVO_MULTIPLAYER_AGENT_QA=CONTRACT_ONLY`; it cannot emit the native PASS marker.

The multiplayer launcher also runs the optional peer-exchange verifier. Profiles without the reserved game-owned metadata assertions emit `EVAVO_MULTIPLAYER_PEER_EXCHANGE=NOT_CONFIGURED`; configured profiles must prove reciprocal peer observation or the launcher fails. See `docs/MULTIPLAYER_PEER_EXCHANGE.md` for the integration contract and its truth boundary.

The attended route starts only after an interactive run has completed. It:

1. reopens `multiplayer-agent-summary.json`;
2. requires a passed exact Lab SHA and target SHA;
3. rebuilds the complete retained-artifact inventory;
4. rehashes every retained evidence file;
5. independently reopens and cross-checks `run-context.json`, `hardware.json`, `source-archive.json`, `validation/report.json` and `profile.normalized.json`;
6. requires the interactive Windows session and guarded desktop lease recorded by the run;
7. requires every role process, harness and visual result to have passed;
8. independently reruns the peer-exchange evidence verifier against the retained normalized profile, role harness assertions and rehashed artifact inventory;
9. rejects a configured peer-exchange contract unless it is proven, while preserving an explicit unconfigured/unproven result for profiles that did not opt in;
10. binds the same-session operator attendance attestation to the exact summary SHA-256, artifact-inventory SHA-256, artifact count and artifact byte total;
11. creates a source-bound receipt outside the original artifact root.

The operator identity comes from the current Windows principal. This is attribution evidence, not cryptographic identity proof.

## Receipt versions

New receipts use `evavo.godot-game-test-lab.attended-multiplayer-receipt.v2` with `schemaVersion: 2`. The v2 receipt contains the source-reverified `peerExchange` result and records that the peer-exchange contract was reverified before receipt compilation.

A v2 `peerExchange.proven: true` means the configured game-owned metadata assertions established one reported session, unique local peer IDs and reciprocal peer observation across every required role. A v2 receipt for a profile that did not opt in records `configured: false` and `proven: false`; concurrent windows are not upgraded into a peer-exchange claim.

Verification retains explicit support for previously issued `evavo.godot-game-test-lab.attended-multiplayer-receipt.v1` / `schemaVersion: 1` receipts. A v1 receipt is reconstructed against the original v1 body rather than silently being interpreted as a v2 peer-exchange receipt.

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

The route rejects changed bytes, changed file sizes, missing files, symlinks, path traversal, duplicate inventory paths, stale or wrong-session attestations, evidence-digest substitution, run-context/summary disagreement, retained hardware disagreement, failed retained validation reports, malformed source-archive receipts, noninteractive execution, target mutation, failed roles, failed visual evidence, configured-but-unproven peer exchange and existing output files.

The receipt deliberately keeps all of these claims false:

- deterministic release-verdict authority;
- human visual approval;
- human game-feel approval;
- physical-controller certification;
- real-network-condition certification;
- transport-path certification;
- complete gameplay coverage;
- release approval;
- source-mutation authority;
- deployment authority;
- publication authority.

A passing receipt proves that the exact synthetic role journeys and retained evidence were attended. When a v2 receipt has `peerExchange.proven: true`, it additionally binds the limited game-reported reciprocal peer-observation proof described above. It does **not** prove packet transport causality, packet-loss/reconnect behavior, hostile-network resilience, complete authority enforcement or that the game is ready to ship. Those conclusions require explicit game-specific assertions and broader runtime/network acceptance evidence.
