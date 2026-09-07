# Multiplayer peer-exchange evidence

Godot Game Test Lab can distinguish **concurrent multiplayer clients** from a stronger, optional proof that the required game clients reported participation in the same multiplayer session and observed one another.

This contract is intentionally game-reported and transport-neutral. It does not require a Test Lab SDK inside the game, does not change network authority, and does not grant release or deployment authority.

## Outcomes

The Windows multiplayer agent QA launcher runs the verifier after the normal passed multiplayer run.

- `EVAVO_MULTIPLAYER_PEER_EXCHANGE=NOT_CONFIGURED` means no reserved peer-exchange assertions were configured. The run may still prove concurrent client execution, but must not be described as proof that the clients exchanged multiplayer state.
- `EVAVO_MULTIPLAYER_PEER_EXCHANGE=PASS required_roles=N` means every required configured role passed the reserved metadata assertions, reported one shared session id, reported a unique positive local Godot peer id, and reported every other required local peer id as observed.
- `EVAVO_MULTIPLAYER_PEER_EXCHANGE=FAIL required_roles=N` or a blocked verifier result fails the launcher when the reserved contract was configured but could not be proven.

## Reserved metadata assertions

Peer-exchange proof uses the existing `metadata_equals` journey assertion. A game opts in by exposing metadata on a stable node and configuring these keys for **every required multiplayer role**:

| Key | Required | Value | Meaning |
| --- | --- | --- | --- |
| `evavo_peer_session_id` | yes | bounded non-empty string | Game-owned identifier for the multiplayer session the role believes it joined. |
| `evavo_local_peer_id` | yes | positive integer | The role's current Godot multiplayer peer id. |
| `evavo_observed_peer_ids` | yes | bounded array of unique positive integers | Peer ids the role has actually observed in the joined session. |
| `evavo_authority_peer_id` | optional | positive integer | Game-reported authority/server peer id. If one required role configures it, every required role must configure and agree on it. |

A role should expose these values only after its own networking code considers the session established. Do not populate `evavo_observed_peer_ids` from the QA profile or command line merely to satisfy the test; it must come from the game's runtime multiplayer state.

Example journey assertions:

```json
{
  "assertions": [
    {
      "type": "metadata_equals",
      "path": "/root/Main/MultiplayerEvidence",
      "key": "evavo_peer_session_id",
      "value": "qa-session-001"
    },
    {
      "type": "metadata_equals",
      "path": "/root/Main/MultiplayerEvidence",
      "key": "evavo_local_peer_id",
      "value": 1
    },
    {
      "type": "metadata_equals",
      "path": "/root/Main/MultiplayerEvidence",
      "key": "evavo_observed_peer_ids",
      "value": [2]
    },
    {
      "type": "metadata_equals",
      "path": "/root/Main/MultiplayerEvidence",
      "key": "evavo_authority_peer_id",
      "value": 1
    }
  ]
}
```

The expected values are role-specific. For a two-role host/client test, the host and client should have different `evavo_local_peer_id` values and each should include the other's id in `evavo_observed_peer_ids`.

## Recommended Godot exposure pattern

Use a stable, non-secret node that reflects authoritative runtime state. For example, after the multiplayer connection is established, game code may set metadata from the real multiplayer API and its own session tracker:

```gdscript
set_meta("evavo_peer_session_id", session_id)
set_meta("evavo_local_peer_id", multiplayer.get_unique_id())
set_meta("evavo_observed_peer_ids", connected_peer_ids)
set_meta("evavo_authority_peer_id", authority_peer_id)
```

`connected_peer_ids` should be derived from actual peer-connected/session state maintained by the game. The metadata is evidence only; Test Lab does not use it to control the session.

Do not expose credentials, tokens, IP addresses, private account identifiers, raw packets, or other secrets in these metadata fields.

## Attended receipt binding

Attended multiplayer receipts produced after this contract use receipt schema v2 and retain a `peerExchange` section. The attended evidence path reopens and rehashes the multiplayer artifacts and re-runs peer-exchange verification before compiling the receipt.

If peer exchange was not configured, the v2 receipt records `configured: false` and `proven: false`. If it was configured, the attended receipt is admissible only when `proven: true`.

Receipt v1 verification remains supported for receipts issued before the peer-exchange field existed.

## Truth boundary

A peer-exchange PASS proves only what the retained, game-owned metadata assertions establish for the required roles: one reported session, unique local peer ids and reciprocal peer observation. It does **not** by itself prove:

- packet transport causality or that a specific packet crossed a specific network path;
- WAN, latency, packet-loss, NAT, relay or hostile-network resilience;
- complete server-authority or anti-cheat enforcement;
- physical controller quality;
- complete gameplay coverage;
- human visual or game-feel approval;
- release readiness, deployment authority or publication authority.

Use dedicated network-condition testing and game-owned authority/state assertions when those stronger properties need evidence.
