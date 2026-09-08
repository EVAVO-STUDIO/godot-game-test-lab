# Authority Peer-Exchange Acceptance

This lane verifies privacy-safe multiplayer lifecycle evidence emitted by a game-owned server-authority implementation. It is designed for authoritative games whose real room membership is owned by a server, Durable Object, relay, or equivalent service rather than by a native Godot `MultiplayerPeer` host.

It is intentionally separate from native concurrent multiplayer QA and browser-client QA.

## What a PASS proves

`EVAVO_AUTHORITY_PEER_EXCHANGE=PASS` requires one strict four-phase receipt:

1. `single` — one participant is present and observes no remote peer.
2. `reciprocal` — at least two participants report the same session and each reports the exact set of every other participant.
3. `departure` — exactly the declared departing role is removed and every remaining participant reports the exact reduced peer set.
4. `reconnect` — the original role inventory is restored and exact reciprocal observation is restored.

The verifier also requires:

- one bounded shared session identifier;
- unique positive ephemeral peer IDs inside each phase;
- bounded role inventories and observed-peer lists;
- no self-observation or duplicate observed peers;
- literal `false` privacy statements for raw player IDs, runtime-session IDs, and credentials;
- UTF-8 JSON no larger than 128 KiB;
- no unexpected receipt fields.

A server is allowed to renumber ephemeral peer slots when membership changes. The proof is about reciprocal authority-owned presence, not persistent player identity.

## What a PASS does not prove

This lane does **not** by itself prove that a browser or native Godot client traversed the production transport path. It does not certify WebSocket/WAN quality, packet loss behavior, latency, browser lifecycle recovery, rendering, gameplay correctness, or release readiness.

Use it alongside client-side multiplayer QA. For Web-only games, the stronger downstream lane must launch real Web clients through runtime admission and then capture the same reserved peer evidence from those clients.

## Receipt contract

A game-owned emitter writes one JSON object to stdout with this exact top-level shape:

```json
{
  "schemaVersion": "1.0",
  "kind": "evavo-authority-peer-exchange-lifecycle",
  "gameId": "example-game",
  "authority": "ExampleRoom",
  "protocol": "example.v1",
  "sessionId": "room-001",
  "departedRoleId": "beta",
  "phases": [
    { "id": "single", "roles": [] },
    { "id": "reciprocal", "roles": [] },
    { "id": "departure", "roles": [] },
    { "id": "reconnect", "roles": [] }
  ],
  "privacy": {
    "rawPlayerIdsTransmitted": false,
    "runtimeSessionIdsTransmitted": false,
    "credentialsTransmitted": false
  },
  "truthBoundary": "Server authority lifecycle proof only."
}
```

Each role record has exactly:

```json
{
  "id": "alpha",
  "sessionId": "room-001",
  "localPeerId": 1,
  "observedPeerIds": [2]
}
```

Do not place account IDs, email addresses, IP addresses, join tickets, reconnect tokens, authorization headers, cookies, or other credentials in this receipt.

## Direct verifier

From a Test Lab checkout:

```powershell
$env:PYTHONPATH = (Join-Path $PWD "src")
python -m godot_game_test_lab.authority_peer_exchange C:\evidence\authority-peer-exchange.json
```

Successful output ends with:

```text
EVAVO_AUTHORITY_PEER_EXCHANGE=PASS roles=2
```

## Exact-SHA local acceptance

For a clean target repository, use the PowerShell 5.1-compatible acceptance wrapper:

```powershell
$Lab = "C:\GitRepos\godot-game-test-lab"
$Target = "C:\GitRepos\godot-462-galactic-cycle-online"
$TargetSha = (git -C $Target rev-parse HEAD).Trim()

& "$Lab\scripts\Invoke-AuthorityPeerExchangeAcceptance.ps1" `
  -TargetRepoRoot $Target `
  -ExpectedTargetSha $TargetSha
```

The wrapper:

- requires the target to be clean and exactly at the requested SHA before execution;
- runs the game-owned authority emitter;
- requires `EVAVO_AUTHORITY_PEER_EXCHANGE_RECEIPT=PASS`;
- retains the emitter JSON outside the target repository as UTF-8;
- independently invokes the Test Lab verifier;
- requires `EVAVO_AUTHORITY_PEER_EXCHANGE=PASS`;
- rechecks the exact target SHA and clean state after execution;
- records the receipt SHA-256 and byte count in `acceptance.json`.

Successful wrapper output contains:

```text
EVAVO_AUTHORITY_PEER_EXCHANGE_ACCEPTANCE=PASS target_sha=<40-hex-sha>
```

## Galactic Cycle Online

`godot-462-galactic-cycle-online` owns its canonical emitter at:

```text
authority/scripts/emit_peer_exchange_evidence.mjs
```

Its normal authority validation also runs that emitter:

```powershell
Set-Location C:\GitRepos\godot-462-galactic-cycle-online\authority
npm run validate
```

The Galactic Cycle emitter exercises the real `GalacticCycleRoom` presence implementation for single membership, reciprocal membership, departure revocation, reconnect de-duplication, and restored reciprocity. The wire evidence deliberately excludes raw player IDs and runtime-session IDs.

## Evidence handling

Keep generated acceptance evidence outside both the target repository and Test Lab repository. Evidence is technical verification, not a publication approval. A later browser/native client acceptance receipt should be linked to the same exact target SHA when making a broader multiplayer release claim.
