# Multiplayer Conformance with EVAVO Game Services

`EVAVO-STUDIO/evavo-game-services` is the canonical multiplayer/service contract source. Godot Game Test Lab remains the execution and evidence system.

## Responsibility boundary

Game Services owns:

- topology and transport requirements
- lobby/matchmaking/service contracts
- realtime room semantics
- reconnect/checkpoint rules
- provider capability selection
- authority/security policy
- multiplayer conformance campaign schema

Game Test Lab owns:

- launching isolated client processes
- launching optional local authority/control-plane processes
- native Windows and browser execution lanes
- per-client isolated user data
- bounded process/network impairment
- deterministic action execution
- screenshots, logs, traces and media evidence
- assertion evidence and exact source SHAs

The Lab must not silently mutate Windows network adapters, router state or firewall policy to simulate latency/loss. Impairment must be scoped to child processes, a local proxy, container/network namespace or another bounded reversible harness.

## Canonical campaign contract

Campaigns should validate against:

```text
C:\GitRepos\evavo-game-services\schemas\multiplayer-conformance-campaign.schema.json
```

A campaign declares at least two clients, an optional authority, scripted actions and assertions such as:

- roster convergence
- ready-state convergence
- same room/authority
- replicated-state convergence
- exactly-once chat presentation
- reconnect restoration
- host migration
- malformed/replayed input rejection
- server lease expiry
- no crash/hang

## Planned Lab operation

The intended governed surface is:

```text
godot-lab multiplayer run <game> --campaign <campaign.json>
```

with retained evidence similar to:

```text
multiplayer-summary.json
campaign.normalized.json
client-a/
client-b/
authority/
network-impairment.json
assertions.json
state-convergence.json
screenshots/
logs/
```

A source-only implementation or schema pass must never be reported as a successful physical multi-client campaign. Native or browser clients must actually launch and exchange traffic for runtime assertions to pass.

## Initial qualification sequence

1. Start EVAVO Game Services local control plane on loopback.
2. Launch two isolated Godot clients from the exact target SHA.
3. Create/join one lobby and converge ready state.
4. Launch selected topology.
5. Exchange monotonic input and authoritative/state messages.
6. Disconnect one client and verify bounded resume behavior.
7. When peer-hosted, remove the host and verify deterministic host migration where allowed.
8. Repeat under bounded latency/jitter/loss where the selected lane supports scoped impairment.
9. Retain exact Lab, game and Game Services SHAs with all evidence.

This document defines the integration contract; it does not claim the multiplayer runner itself has executed until a real campaign receipt exists.
