# Multiplayer QA Campaigns

Godot Game Test Lab must be able to prove multiplayer behaviour across multiple real game processes or browser sessions without granting itself authority to edit the target game.

This document defines the integration boundary with the shared EVAVO Game Services platform.

## Goals

A multiplayer campaign can:

- launch two or more isolated clients from the same exact target SHA;
- optionally launch a local authoritative server process;
- optionally launch the EVAVO local control plane and signaling services;
- create and join a lobby;
- start a match/session;
- prove roster convergence;
- drive deterministic authored actions from different players;
- verify replicated state convergence;
- test disconnect/reconnect and bounded resume;
- exercise text chat and rate limits;
- exercise achievement/stat/leaderboard events where declared;
- retain per-client and cross-client evidence;
- run with separate user-data roots so one client cannot accidentally share local save/session state with another;
- preserve the target repository as read-only during authoritative QA.

## Lanes

### Native Windows campaign

Runs real Godot windows in Greg's logged-in Windows session.

This is the authoritative lane for:

- real Windows networking behaviour;
- ENet/direct UDP tests;
- native WebRTC integrations;
- multiple visible game processes;
- desktop input/focus behaviour;
- native voice-device integration when explicitly enabled.

The native desktop lease must remain exclusive to one campaign at a time.

### Browser campaign

The Lab may delegate browser multiplayer execution to the EVAVO Godot Web Runtime evaluation surface where appropriate.

This proves:

- multiple isolated browser contexts;
- WebSocket/WebRTC browser paths;
- lobby/join-ticket flow;
- web reconnect;
- browser-origin/capability behaviour.

It does not prove native UDP/ENet behaviour.

### Linux sandbox campaign

Use for protocol/server/client headless conformance where the exact game and topology support it.

The sandbox remains no-network by default. A multiplayer campaign may only enable an explicit campaign-local isolated network namespace; it must not silently grant arbitrary internet access.

## Target-owned profile

A game opts in with a tracked profile, normally:

```text
<game>/.evavo/godot-lab-multiplayer.json
```

Suggested shape:

```json
{
  "schemaVersion": 1,
  "gameId": "example-game",
  "projectSubpath": ".",
  "clients": 2,
  "topology": "local",
  "transport": "websocket",
  "authority": {
    "mode": "local-service"
  },
  "journeys": [
    {
      "name": "two-player-join-and-reconnect",
      "steps": [
        { "client": 1, "action": "create_lobby" },
        { "client": 2, "action": "join_lobby" },
        { "all": true, "assert": "roster_converged" },
        { "client": 2, "action": "disconnect" },
        { "client": 2, "action": "reconnect" },
        { "all": true, "assert": "replicated_state_converged" }
      ]
    }
  ]
}
```

The final schema belongs to Game Test Lab and must remain strict and versioned.

## Isolation

Each client receives unique paths for:

- Godot user data;
- logs;
- screenshots;
- recordings;
- local profile/session state;
- temporary export/runtime files.

No two clients may share mutable user data unless the test explicitly declares a shared external service.

## Local service integration

The campaign runner should prefer a local provider for deterministic QA.

Expected future EVAVO Game Services commands:

```text
evavo-game-services doctor
evavo-game-services local start --ephemeral
evavo-game-services local status
evavo-game-services local stop
```

The Lab must consume a machine-readable endpoint receipt rather than scraping console text.

A service receipt should include:

- instance ID;
- protocol version;
- selected ports;
- enabled service capabilities;
- process IDs or container IDs where applicable;
- startup time;
- health state;
- shutdown token/lease known only to the campaign owner.

## Evidence

A campaign retains:

```text
multiplayer-campaign-summary.json
campaign-topology.json
service-receipt.json
client-01/
  stdout.log
  stderr.log
  engine.log
  screenshots/
  trace.json
client-02/
  ...
protocol/
  control-plane.ndjson
  gameplay-summary.ndjson
network/
  impairment-profile.json
  latency-summary.json
convergence/
  roster.json
  state-fingerprints.json
  assertion-results.json
```

Raw secrets, join tickets and voice payloads must not be retained in normal evidence.

## Assertions

Core assertions should include:

- all expected clients connected;
- no duplicate stable player identity;
- lobby roster converged;
- ready/team metadata converged;
- match transition converged;
- authoritative snapshot accepted;
- replicated state fingerprint converged within the declared tolerance/window;
- disconnect observed by remaining peers;
- reconnect restored the same logical player where the game declares reconnect support;
- stale/replayed input rejected where the protocol exposes this evidence;
- oversized/rate-abusive messages rejected;
- privileged actions rejected for unauthorized clients;
- score/achievement results originate from the declared trust path.

## Network impairment

Where supported, campaigns may apply bounded synthetic conditions:

- latency;
- jitter;
- packet loss;
- packet duplication;
- reordering;
- short outage.

Impairment must be local to the campaign namespace/processes. Do not globally reconfigure Greg's Windows network adapter to simulate a game test.

Network Studio may be used to capture host/link evidence, but multiplayer QA must not grant it permission to mutate network settings.

## Anti-cheat QA

The Lab should include adversarial protocol fixtures that attempt:

- duplicate/replayed sequence numbers;
- impossible movement deltas;
- client-authored privileged role/team state;
- forged player IDs;
- stale/expired tickets;
- unauthorized score/achievement submissions;
- message floods within bounded safe test limits;
- oversized payloads;
- cross-room ticket reuse.

These are controlled conformance tests against EVAVO-owned local services, not attacks against external systems.

## Voice/proximity QA

Voice tests are opt-in because they involve microphone/audio-device privacy and substantially larger evidence.

Default automated QA should verify only:

- voice membership authorization;
- proximity routing metadata;
- mute/deafen state;
- room transitions.

Audio capture requires an explicit profile capability and must follow existing Lab audio-evidence safeguards.

## Truth boundaries

- Two clients connecting does not prove production scale.
- A localhost latency result does not prove internet latency.
- Browser WebRTC success does not prove native ENet success.
- A peer-hosted test does not prove server-authoritative cheat resistance.
- Synthetic packet impairment is useful stress evidence, not a substitute for real WAN testing.
- A successful campaign proves only the exact target SHA, service SHA/configuration, topology and journey that were executed.

## Implementation sequence

1. Add strict multiplayer campaign profile schema.
2. Add process/user-data isolation manager.
3. Add local EVAVO Game Services lifecycle adapter.
4. Add two-client launcher and evidence ownership.
5. Add lobby/roster/reconnect assertions.
6. Add browser campaign handoff to Godot Web Runtime.
7. Add local network impairment harness.
8. Add protocol adversarial fixtures.
9. Add leaderboard/achievement conformance.
10. Add optional voice/proximity membership tests.
11. Expose governed MCP operations for campaign planning and execution.

The Lab remains a testing authority, not a game or service mutation authority.