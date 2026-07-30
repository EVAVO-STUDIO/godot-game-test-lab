# Linux Godot Sandbox Contract

## Purpose

The Linux sandbox is the reusable EVAVO worker for confirming how an exact Godot repository revision behaves on Linux without granting the worker authority to edit or publish that game repository.

It complements, rather than replaces:

- the freshly probed Windows native runner for primary desktop acceptance;
- Godot Web Runtime for browser input, screenshots, traces and semantic browser observations;
- repository-specific real multiplayer and release evidence.

## Execution boundary

A run is bound to:

- the exact `godot-game-test-lab` main SHA;
- the exact target repository SHA;
- a canonical project subpath;
- Godot 4.6.2 standard or .NET editor selection;
- an explicit Development Studio dispatch identity.

The target checkout is mounted read-only. The container copies source into an ephemeral writable working directory and excludes `.git`, `.godot`, `.qa`, `.cache` and prior `artifacts` directories. Repository-external symbolic links fail closed. Godot imports, generated metadata, .NET intermediates, export files and visual evidence can therefore never be written into the checked-out target source.

## Container boundary

The image uses the dated Ubuntu 24.04 base `ubuntu:noble-20260610`. During image construction it downloads the official Godot 4.6.2 Linux editor and matching export templates, selects standard or .NET archives, and verifies both files against the release `SHA512-SUMS.txt` manifest before extraction.

The runtime container:

- runs as UID/GID `10001`;
- has a read-only root filesystem;
- has no network;
- drops every Linux capability;
- enables `no-new-privileges`;
- has bounded CPU, memory, process count and shared memory;
- receives no GitHub token or repository credential;
- receives only the read-only target source, an ephemeral work directory and an evidence directory.

C# projects use the .NET-enabled Godot editor and .NET SDK 8. A standard editor request for a detected C# target fails before the container runs.

## Evidence stages

The agent performs:

1. source and project inventory;
2. Godot identity;
3. .NET identity and `dotnet build` when `.csproj` files exist;
4. headless Godot editor import;
5. bounded headless main-scene boot;
6. a bounded windowed run under Xvfb using Mesa `llvmpipe` software rendering;
7. deterministic Godot Movie Maker capture;
8. `ffprobe` metadata and a PNG contact sheet;
9. an optional declared Linux release export;
10. one machine-readable `sandbox-report.json` plus phase stdout and stderr logs.

The workflow uploads only bounded evidence and then removes the image and working directory.

## Visual truth boundary

The Xvfb and `llvmpipe` path proves that the project can create and render a Linux window without a physical display or GPU. It is useful for automated agents to inspect initial presentation, missing assets, shader fallback, viewport sizing, crashes and obvious visual regressions.

It does not prove:

- hardware-specific Vulkan behavior;
- performance on a player GPU;
- input correctness or game feel;
- a complete playthrough;
- multiplayer timing;
- visual approval by itself.

The AVI and contact sheet are evidence inputs for later agent or human review. They are not an automatic claim that the game looks good.

## GitHub dispatch

`.github/workflows/evavo-linux-godot-sandbox.yml` is manual-only. Private target repositories require the repository-scoped, read-only secret `EVAVO_GODOT_LAB_READ_TOKEN`. The token is used only by `actions/checkout`; `persist-credentials` is disabled and the token is never passed into Docker.

Development Studio should dispatch the workflow with the exact lab and target SHAs, retain the artifact name, inspect `sandbox-report.json`, and route any repair through the target repository's own governed mainline process.
