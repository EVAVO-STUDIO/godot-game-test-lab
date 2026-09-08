# Multiplayer evidence ladder

EVAVO multiplayer QA uses separate proof tiers. A higher tier does not erase the lower-tier contracts, and a lower-tier PASS must never be described as proof from a higher tier.

## Tier 1 — authority lifecycle

Command:

```text
godot-lab-authority-peer-exchange <authority-receipt.json>
```

Proves the retained server-authority lifecycle receipt has one shared room/session, exact reciprocal peer observation, departure revocation, reconnect restoration, stable ephemeral peer mapping, privacy-safe identity handling, superseded-socket retirement, stale outbound rejection and stale inbound rejection.

It does **not** prove any client traversed a real transport path.

## Tier 2 — EVAVO runtime transport

Command:

```text
godot-lab-runtime-authority-peer-exchange <runtime-receipt.json>
```

Adds proof that the EVAVO runtime issued bound multiplayer admission and traversed the WebSocket authority lifecycle against an exact deployed authority source SHA.

It does **not** prove Chromium or a Godot Web player consumed the session.

## Tier 3 — browser-native transport

Command:

```text
godot-lab-browser-runtime-authority-peer-exchange <browser-receipt.json>
```

Adds Chromium browser-native same-origin session issuance and WebSocket transport, isolated participant contexts and hostile-origin rejection evidence.

It does **not** prove the mounted Godot Web export consumed the runtime handoff.

## Tier 4 — mounted Godot Web player

Command:

```text
godot-lab-godot-web-authority-peer-exchange <godot-web-receipt.json>
```

Adds proof that two isolated Chromium contexts launched the mounted Godot Web export through the ordinary EVAVO `/play` → `/embed` surfaces, the running Godot clients consumed the runtime multiplayer handoff, reached the source-bound authority, observed reciprocal room presence, observed departure revocation and restored reciprocal evidence after reconnect.

This tier observes the signed release descriptor **envelope**. The current live probe does not independently perform the descriptor's cryptographic signature verification itself, so it must not claim that stronger fact.

## Cross-bind all four tiers

Command:

```text
godot-lab-multiplayer-evidence-ladder \
  authority-receipt.json \
  runtime-receipt.json \
  browser-receipt.json \
  godot-web-receipt.json
```

The ladder reruns each strict verifier and rejects receipts that do not describe the same deployment. It cross-binds:

- game ID and protocol
- shared authority room/session
- release ID and release channel
- runtime origin and authority origin
- exact deployed authority source SHA
- required role count
- departed and surviving role identities
- reconnect identity continuity and runtime-session rotation
- privacy-safe evidence claims
- the deliberate transport-scope distinction between tiers

A ladder PASS means all four retained receipts are individually admissible and mutually consistent. It still does not certify gameplay correctness, real WAN quality under adverse latency/loss, rendering quality, performance budgets, UX quality or release readiness.

## Privacy boundary

Retained multiplayer evidence must not include:

- join tickets or reconnect credentials
- raw player/account identifiers
- runtime session identifiers
- installation identifiers
- email addresses, IP addresses or access/refresh tokens

Game-facing peer evidence is intentionally limited to the shared room/session label and bounded ephemeral peer IDs needed for reciprocal observation.
