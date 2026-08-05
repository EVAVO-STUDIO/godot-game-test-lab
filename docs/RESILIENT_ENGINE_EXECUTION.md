# Resilient Engine Execution

This contract handles the case where source review is complete but exact Godot execution is blocked because the local host cannot resolve the release server, a remote-job connector is missing, GitHub Actions cannot allocate a runner, or local Git has no authenticated push transport.

A blocked acquisition or provider lane is not a source failure. Preserve the exact target SHA, classify the failure, select an independent lane, and claim only the execution evidence that actually completed.

## Acquisition order

1. Exact already-installed Godot executable, verified by version and SHA-256.
2. Godot Game Test Lab content-addressed cache.
3. Shared offline mirror containing the official release archive and `SHA512-SUMS.txt`.
4. Archive and checksum materialized through a connected file provider.
5. Named persistent Vercel Sandbox with the engine preinstalled.
6. Vercel Sandbox snapshot or governed custom image.
7. Authenticated GitHub release-asset access.
8. Direct official download.
9. Manual GitHub Actions cache artifact when runner allocation is healthy.
10. Governed self-hosted runner cache.

Development Studio provides `scripts/engine-artifact-import.mjs` to verify a connector-materialized archive and place it into the exact offline mirror structure expected by Test Lab. Test Lab then installs with:

```text
godot-lab engine ensure <project> \
  --version 4.6.2 \
  --flavor mono \
  --source-dir <offline-mirror-root> \
  --offline
```

No token may appear in a URL, argument, log, screenshot, receipt or committed file.

## Exact renderer import command

After the engine exists locally, run both governed import passes with one command:

```text
python -m godot_game_test_lab.resilient_import \
  --project <exact-clean-project> \
  --godot <exact-godot-executable> \
  --artifacts <external-evidence-root> \
  --expected-version 4.6.2
```

The default passes are:

```text
<godot> --headless --path <project> --rendering-method forward_plus --import
<godot> --headless --path <project> --rendering-method gl_compatibility --rendering-driver opengl3 --import
```

The runner:

- requires a canonical project containing `project.godot`;
- requires evidence outside target source;
- rejects a dirty tracked checkout;
- records exact Git HEAD when available;
- verifies the Godot executable version and SHA-256;
- runs `.NET build` first for C# projects and adds `--locked-mode` when the repository owns `packages.lock.json`, unless explicitly skipped;
- isolates home, application data, cache and temporary roots;
- bounds duration and output bytes;
- stores separate stdout and stderr logs for every pass;
- fails if Godot changes tracked source;
- writes a machine-readable `summary.json`.

Select a single pass only when diagnosing a renderer-specific problem:

```text
python -m godot_game_test_lab.resilient_import ... --renderer forward_plus
python -m godot_game_test_lab.resilient_import ... --renderer compatibility
```

The repository wrapper `python scripts/run_resilient_engine_import.py` exposes the same command before installation.

## Independent execution lanes

When local execution is unavailable, use one of these without changing target semantics:

- Test Lab Linux sandbox or local Docker/Podman;
- named persistent Vercel Sandbox;
- Vercel Sandbox snapshot;
- Vercel Sandbox custom image;
- Development Studio exact-SHA worker;
- manual GitHub Actions after runner allocation is proven;
- governed self-hosted runner.

Do not replace native Godot C# with a web export merely because the web lane is easier. Godot Web Runtime is appropriate only for compatible web exports and browser-hosted evidence.

## Failure classification

- DNS or egress failure: acquisition route failed; source remains unjudged.
- Connector unavailable: one remote lane failed; inspect other lanes.
- Zero-step or pre-runner Actions failure: provider precondition, not build failure.
- Nonzero import exit after the engine starts: retain renderer, command and logs; diagnose source, asset, toolchain or GPU evidence.
- Tracked source mutation: fail the run and inspect the exact changed path.
- Forward+ failure with Compatibility success: renderer-specific evidence, not universal project failure.

## Truth boundary

A passing headless import proves the recorded engine parsed and imported the project for the selected rendering method without changing tracked source. It does not prove a visible native window, physical controller behavior, every GPU, performance acceptance, exported builds, final visual quality, game feel or a complete playthrough. Those require native journey, screenshot or video, input and performance evidence from the appropriate Test Lab lane.
