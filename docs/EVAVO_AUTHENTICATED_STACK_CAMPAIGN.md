# EVAVO Authenticated Stack Campaign

This campaign proves the player-identity boundary and the Battle.net-style control plane together. It uses real service processes and two isolated client workers rather than having one test process impersonate both players.

## Components launched

```text
EVAVO platform backend
EVAVO player identity platform
EVAVO authenticated platform gateway
player-one device worker
player-two device worker
```

The service binaries come from the exact `evavo-game-services` checkout specified by the campaign manifest. The runner records its Git commit SHA in final evidence.

## What the campaign proves

The reference campaign performs:

1. strict repository and compiled-entrypoint checks;
2. optional Game Services TypeScript build;
3. backend, identity and gateway process startup;
4. bounded health checks;
5. separate Ed25519 key generation for each client worker;
6. trusted account and public-device-key enrollment;
7. real one-time challenge login for both players;
8. authenticated lobby creation by player one;
9. authenticated lobby join by player two;
10. ready-state convergence for both players;
11. canonical lobby readback;
12. rotating refresh-token proof;
13. player-two process shutdown and restart with isolated credentials;
14. post-restart authenticated lobby readback;
15. spoofed player-ID rejection;
16. replay of the old refresh generation;
17. refresh-family and current-session revocation proof;
18. device-key relogin into a new family;
19. final lobby evidence;
20. reverse-order process-tree cleanup and secret-directory removal.

The campaign does not print session tokens, refresh tokens, signatures, private keys or service credentials. Client output is JSON and recursively redacts credential-shaped fields.

## Run on Windows

```powershell
Set-Location C:\GitRepos\godot-game-test-lab
git pull --ff-only origin main

.\scripts\run-evavo-authenticated-stack-campaign.ps1
```

The example manifest expects:

```text
C:\GitRepos\evavo-game-services
```

Edit a copy of `campaigns/evavo-authenticated-stack.example.json` when the Game Services checkout lives elsewhere.

To reuse an existing `dist` build:

```powershell
.\scripts\run-evavo-authenticated-stack-campaign.ps1 -NoBuild
```

Do not use `-NoBuild` when qualifying a new source revision.

## Manifest

```json
{
  "schemaVersion": 1,
  "campaignId": "evavo-authenticated-lobby-refresh-reconnect",
  "gameServicesRepo": "C:\\GitRepos\\evavo-game-services",
  "gameId": "reference-rts",
  "buildHash": "reference-build-2026-09-02",
  "protocolVersion": 1,
  "players": [
    {
      "playerId": "test_player_one",
      "displayName": "Test Player One",
      "deviceId": "testlab-device-one"
    },
    {
      "playerId": "test_player_two",
      "displayName": "Test Player Two",
      "deviceId": "testlab-device-two"
    }
  ],
  "lobby": {
    "lobbyId": "authenticated-campaign-lobby",
    "visibility": "public",
    "maxPlayers": 2,
    "region": "local",
    "mode": "conformance"
  },
  "timeouts": {
    "buildSeconds": 300,
    "startupSeconds": 30,
    "commandSeconds": 15,
    "shutdownSeconds": 5
  },
  "evidenceDirectory": "../artifacts/multiplayer/authenticated-stack",
  "buildBeforeRun": true
}
```

The parser rejects unknown keys, duplicate players/devices, invalid game/build identifiers, undersized lobbies, unsafe timeout values and oversized configuration files.

## Client isolation

Each worker gets a separate temporary directory containing:

```text
device-private.pem
device-private.pem.pub
credentials.json
```

These files exist only below the run’s `.secrets` directory. They are created with restrictive permissions where the operating system permits and are removed during campaign cleanup. They are not included in the evidence manifest or logs.

This plaintext temporary storage is a Test Lab fixture, not a production credential-storage recommendation. Browser, Godot and Unreal games should use their platform keystore adapters.

## Evidence

Successful and failed runs both write:

```text
<evidenceDirectory>/<campaignId>-<runId>/evidence.json
```

The evidence includes:

- campaign and run IDs;
- pass/fail state;
- exact start/end times and duration;
- Game Services checkout and commit SHA;
- game/build/protocol identity;
- non-secret player and device identifiers;
- dynamically allocated local ports;
- ordered step results;
- service and client log paths;
- confirmation that the secret directory was removed;
- a bounded failure message when applicable.

Service logs remain available for diagnosis but should still be handled as test artifacts. The services are designed not to print secrets.

## Cleanup

Every service and worker is started in its own process group. Cleanup runs even when a campaign assertion fails.

On Windows, the runner uses process-tree termination. On POSIX systems it terminates the process group and escalates only after a bounded graceful wait.

The launcher itself does not change network adapters, firewall rules or system-wide packet settings.

## Limits of this campaign

This campaign proves local process boundaries, player identity, device challenge signatures, credential rotation, gateway actor binding and lobby convergence.

It does not by itself prove:

- a native Godot export;
- Unreal compilation;
- browser WebCrypto keystore behavior;
- multiple physical devices;
- NAT traversal or CGNAT behavior;
- public TLS or reverse-proxy header stripping;
- Cloudflare deployment;
- Bluetooth discovery;
- sustained relay, matchmaking or dedicated-server load.

Those remain separate Test Lab lanes using the same account, session, route-policy and evidence contracts.
