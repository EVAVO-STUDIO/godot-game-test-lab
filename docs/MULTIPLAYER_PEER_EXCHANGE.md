# Multiplayer peer-exchange evidence

Godot Game Test Lab can distinguish **concurrent multiplayer clients** from a stronger, optional proof that the required game clients reported participation in the same multiplayer session and observed one another.

This contract is intentionally game-reported and transport-neutral. It does not require a Test Lab SDK inside the game, does not change network authority, and does not grant release or deployment authority.

## Outcomes

The Windows multiplayer agent QA launcher runs the verifier after the normal passed multiplayer run.

- `EVAVO_MULTIPLAYER_PEER_EXCHANGE=NOT_CONFIGURED` means no reserved peer-exchange assertions were configured. The run may still prove concurrent client execution, but must not be described as proof that the clients exchanged multiplayer state.
- `EVAVO_MULTIPLAYER_PEER_EXCHANGE=PASS required_roles=N` means every required configured role passed the reserved metadata evidence contract, reported one shared session id, reported a unique positive local peer id, and reported every other required local peer id as observed.
- `EVAVO_MULTIPLAYER_PEER_EXCHANGE=FAIL required_roles=N` or a blocked verifier result fails the launcher when the reserved contract was configured but could not be proven.

## Dynamic capture is the default

For runtime-assigned peer ids or server-assigned ephemeral room slots, use the multiplayer-only `metadata_capture` assertion. Unlike `metadata_equals`, the profile does not contain an expected value. The capture-capable multiplayer journey harness reads the actual value from the running game, validates it against the narrow reserved contract, and retains it in the journey report as `actual`.

Only these four keys may be captured:

| Key | Required | Captured value | Meaning |
| --- | --- | --- | --- |
| `evavo_peer_session_id` | yes | bounded non-empty single-line string | Game-owned identifier for the multiplayer room/session represented by the evidence. |
| `evavo_local_peer_id` | yes | positive integer | Current runtime peer id or ephemeral server-assigned room slot for this role. |
| `evavo_observed_peer_ids` | yes | bounded array of unique positive integers | Peer ids/slots the role has actually observed in the joined session. |
| `evavo_authority_peer_id` | optional | positive integer | Participating authority peer id. If one required role configures it, every required role must configure and agree on it. |

The normalizer rejects `metadata_capture` for any other metadata key. The Godot harness independently enforces the same allow-list and bounded value shapes. It cannot be used to capture arbitrary metadata, credentials, account identifiers or tokens.

Recommended journey assertions:

```json
{
  "assertions": [
    {
      "type": "metadata_capture",
      "path": "/root/PeerExchangeEvidence",
      "key": "evavo_peer_session_id"
    },
    {
      "type": "metadata_capture",
      "path": "/root/PeerExchangeEvidence",
      "key": "evavo_local_peer_id"
    },
    {
      "type": "metadata_capture",
      "path": "/root/PeerExchangeEvidence",
      "key": "evavo_observed_peer_ids"
    }
  ]
}
```

See `examples/multiplayer-peer-exchange.profile.json` for a complete two-role profile.

A role should expose these values only after its own networking code considers the session established. Do not populate `evavo_observed_peer_ids` from the QA profile or command line merely to satisfy the test; it must come from the game's runtime multiplayer or authoritative room-presence state.

## Legacy fixed-value assertions

`metadata_equals` remains supported for deliberately fixed contracts, fixtures and deterministic local harnesses. Its value comes from the profile and therefore it is not dynamic observation evidence.

For production systems where local peer ids are allocated at runtime, prefer `metadata_capture`. Do not hard-code predicted peer ids merely to obtain a PASS.

Example fixed-value assertion:

```json
{
  "type": "metadata_equals",
  "path": "/root/PeerExchangeEvidence",
  "key": "evavo_local_peer_id",
  "value": 1
}
```

## Recommended Godot exposure pattern

Use a stable, non-secret node that reflects runtime networking state. For native Godot multiplayer, game code may set metadata from the real `MultiplayerAPI` and its own session tracker:

```gdscript
set_meta("evavo_peer_session_id", session_id)
set_meta("evavo_local_peer_id", multiplayer.get_unique_id())
set_meta("evavo_observed_peer_ids", connected_peer_ids)
set_meta("evavo_authority_peer_id", authority_peer_id)
```

For a custom authoritative transport, the numeric peer values may instead be short-lived server-assigned room slots, provided they identify participation only within the current room/session and do not encode persistent account identity.

`connected_peer_ids` must be derived from actual peer-connected/session state maintained by the game. The metadata is evidence only; Test Lab does not use it to control the session.

Never expose credentials, tokens, IP addresses, private account identifiers, raw player IDs, transport tickets, raw packets or other secrets in these metadata fields.

## Cross-role verifier rules

A configured proof fails closed when any required role is missing a required key, a capture has no retained `actual` value, peer ids are invalid or duplicated, a role lists its own local id as observed, required roles disagree on the session id, required roles do not have unique local ids, or any required role fails to observe every other required role.

If `evavo_authority_peer_id` is configured, all required roles must configure it, agree on one value, and that authority id must be one of the participating required peer ids. A custom server that is not represented as a participating client should omit this optional key rather than fabricate a client authority id.

## Attended receipt binding

Attended multiplayer receipts produced after this contract use receipt schema v2 and retain a `peerExchange` section. The attended evidence path reopens and rehashes the multiplayer artifacts and re-runs peer-exchange verification before compiling the receipt.

If peer exchange was not configured, the v2 receipt records `configured: false` and `proven: false`. If it was configured, the attended receipt is admissible only when `proven: true`.

Receipt v1 verification remains supported for receipts issued before the peer-exchange field existed.

## Native versus browser production paths

The current `godot-lab-multiplayer-qa` executor launches concurrent native Godot processes. A PASS from that lane proves the exact native journeys and their retained evidence. It does not certify a separate browser/Web launcher, browser-issued admission handoff, WebSocket gateway, relay or production Web authority path.

A game whose production multiplayer exists only through an EVAVO browser/runtime handoff needs a browser multiplayer acceptance lane before its production transport can be certified. Native peer-exchange evidence can still validate shared game-side contracts, diagnostics and adapters, but must not be presented as proof that the browser production path was exercised.

## Truth boundary

A peer-exchange PASS proves only what the retained, game-owned metadata evidence establishes for the required roles: one reported session, unique local peer ids and reciprocal peer observation. A dynamic capture additionally proves that those particular values came from the running game rather than from profile expectations. It does **not** by itself prove:

- packet transport causality or that a specific packet crossed a specific network path;
- WAN, latency, packet-loss, NAT, relay or hostile-network resilience;
- complete server-authority or anti-cheat enforcement;
- a separate browser/Web production transport when the test ran native Godot clients;
- physical controller quality;
- complete gameplay coverage;
- human visual or game-feel approval;
- release readiness, deployment authority or publication authority.

Use dedicated network-condition testing, browser production-path acceptance and game-owned authority/state assertions when those stronger properties need evidence.
