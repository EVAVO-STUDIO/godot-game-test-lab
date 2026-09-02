# EVAVO Game Runtime HTTP Range Content Transfer

This Test Lab suite independently verifies the concrete HTTP range provider in
EVAVO Game Runtime 0.10 against an exact runtime checkout and exact Godot 4.6.2
binary.

The suite is intentionally external to the runtime repository. It records both
Git SHAs, both branch names, repository cleanliness, the reported Godot version,
per-scenario logs and the runtime's complete range-server receipt.

## What it executes

The Test Lab runner performs four required scenarios:

```text
integration_validator
exact_godot_4_6_2_import
http_range_behavior
range_server_evidence
```

The runtime behavior lane starts a real local HTTP server and drives real
`HTTPClient` requests. It is not a mocked byte-source test.

The server records evidence for:

- four successful HTTP 206 byte ranges;
- exact `Content-Range` response values;
- a transient HTTP 503 followed by bounded retry and recovery;
- a server that ignores `Range` and returns HTTP 200;
- a malformed `Content-Range` total;
- corrupt range bytes retried to the configured attempt limit;
- terminal cancellation;
- protected restart and replay of process-local provider state.

The expected package ranges are:

```text
bytes=0-11
bytes=12-23
bytes=24-35
bytes=36-47
```

The suite also confirms that the final cache payload matches the reference
package and that the full package digest is verified before cache readiness.

## Running on Windows

```powershell
Set-Location C:\GitRepos\godot-game-test-lab

git pull --ff-only origin main

.\scripts\run-evavo-game-runtime-http-range-content-transfer.ps1 `
    -RuntimeRepo C:\GitRepos\evavo-game-runtime `
    -GodotPath $env:GODOT_BIN
```

Run only the dependency-free integration validator:

```powershell
python .\scripts\validate-evavo-game-runtime-http-range-content-transfer.py `
    --runtime-repo C:\GitRepos\evavo-game-runtime
```

## Exact identity requirements

Before running network behavior, the runner requires:

- a clean Runtime repository;
- a clean Test Lab repository;
- exact 40-character Git SHAs;
- a Godot executable that reports version 4.6.2;
- the runtime's versioned HTTP source contract;
- the runtime plugin version declared as 0.10.0.

The receipt is written even when a later scenario fails, preserving the exact
observed state rather than fabricating a success result.

## Receipt evidence

The version 1 receipt contains:

- runtime and Test Lab repositories, branches and SHAs;
- repository cleanliness flags;
- exact Godot version;
- integration-validator result and log;
- exact import/parse result and log;
- runtime behavior result and log;
- range-server evidence and report path;
- the path to the nested runtime receipt;
- explicit truth-boundary claims.

The range-server evidence must show all expected ranges, at least one transient
503, at least one ignored-range 200 response, malformed `Content-Range`
coverage, at least three corrupt-range attempts, and no unexpected range.

## Scope and limitations

This proves real loopback HTTP range behavior through Godot 4.6.2. It does not
prove production CDN behavior, public internet routing, TLS certificate
rotation, authenticated edge delivery, mobile operating-system background
transfer, storefront installation, or production browser CORS.

A browser export still requires exported-browser validation of:

- CORS request and exposed-response headers;
- service-worker cache behavior;
- range semantics through the selected CDN;
- hosting response compression rules;
- browser storage quotas and eviction;
- offline restart behavior.

The suite therefore keeps all of these claims false:

```text
HTTP dispatch is transfer completion
range response is cache verification
provider completion is cache verification
cancel request is terminal cancellation
runtime readiness grants content availability
runtime readiness grants scene activation
runtime readiness grants simulation authority
Web CORS configuration is verified
process-local handles are portable
```

Content availability, scene activation and simulation authority remain governed
by later EVAVO trust and activation layers.

## No paid CI dependency

The suite is designed for direct local or agent-driven execution. It does not
require GitHub Actions, a hosted test service or a paid CI plan.
