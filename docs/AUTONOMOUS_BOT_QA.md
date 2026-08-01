# Autonomous Godot Bot QA

`godot-lab-bot-qa` is the reusable deterministic exploration layer for EVAVO Godot repositories. It validates an exact target commit, launches the real Godot project from an isolated copy, discovers the runtime UI and InputMap, replays bounded synthetic input traces in fresh processes, and retains enough visual and machine-readable evidence for another agent to review and reproduce a defect.

The Test Lab can remain at `C:\GitRepos\godot-game-test-lab` while the target game lives in any other Git repository. The target owns its bot profile. The Lab owns execution and evidence. The Lab never edits, commits, pushes, signs, deploys or publishes the target game.

## What it tests

Before exploration, the worker runs the canonical static-integrity, C# build, Godot import, recovery-mode and bounded-boot pipeline. This catches malformed `project.godot`, corrupt TSCN/TRES resources, missing dependencies, unresolved merge markers, Git LFS placeholders, C# compile failures, importer failures and startup errors before the bot is allowed to interact with the game.

A bot campaign can then combine:

- runtime discovery of visible, enabled and focusable controls;
- safe mouse clicks at control centres;
- semantic InputMap actions;
- concrete keyboard events derived from the target InputMap;
- concrete mouse-button mappings;
- synthetic joypad button and axis events derived from the target InputMap;
- deterministic state fingerprints based on scene, focus and UI structure;
- fresh-process replay of every trace;
- isolated `user://`, `%APPDATA%`, `%LOCALAPPDATA%`, home, cache and temporary paths;
- periodic screenshots and representative Movie Maker replays;
- Godot logs, stdout, stderr, process exit and timeout evidence;
- UI clipping, overlap, focus and target-size telemetry;
- FPS, frame-time, memory, object, node and draw-call summaries;
- black-video and frozen-video diagnostics;
- exact trace records for reproduction.

Godot supports feeding generated `InputEvent` objects back through the engine. The worker uses that Godot path rather than claiming that shell-level key presses are equivalent to engine input. Synthetic gamepad input verifies mappings and event handling; it does not certify a physical controller, Steam Input, USB/Bluetooth enumeration, rumble or device latency.

## Bootstrap any game repository

From the Test Lab virtual environment:

```powershell
godot-lab-init-qa C:\GitRepos\Brass_Brine `
  --output .evavo\godot-lab-bot.json `
  --report .evavo\godot-lab-bot.discovery.json
```

The bootstrap command:

1. resolves exactly one `project.godot`;
2. inventories scenes, scripts, C# projects and addons;
3. detects a likely rendering method and available input-device mappings;
4. writes a strict starter profile;
5. refuses to overwrite an existing profile unless `--force` is supplied.

Review the generated deny lists before committing the profile. Add game-specific assertions and allowlists as the game matures.

## Run on Greg's Windows machine

```powershell
$Lab = "C:\GitRepos\godot-game-test-lab"
$Game = "C:\GitRepos\Brass_Brine"
$EvidenceRoot = "C:\GodotLabEvidence"
$Run = Join-Path $EvidenceRoot "Brass_Brine\bot-$(Get-Date -Format yyyyMMdd-HHmmss)"

Set-Location $Lab

.\scripts\Invoke-GodotLabBotQA.ps1 `
  -TargetRepositoryPath $Game `
  -ProjectSubpath "." `
  -ProfilePath ".evavo\godot-lab-bot.json" `
  -ExpectedLabSha (git rev-parse HEAD) `
  -ExpectedTargetSha (git -C $Game rev-parse HEAD) `
  -ArtifactPath $Run `
  -AllowedArtifactRoot $EvidenceRoot `
  -PythonExecutable ".\.venv\Scripts\python.exe" `
  -MinimumGodotVersion "4.6.2" `
  -WindowPosition "32,32"
```

The approved worker must run in Greg's logged-in nonzero Windows session with Explorer in the same session. A conventional service-hosted runner in Session 0 is rejected for native visual evidence.

## Deterministic graph exploration

Every campaign starts with a survey run. The harness records the current scene, focus owner, viewport, visible controls and InputMap. The planner creates a bounded set of safe candidates, replays each route in a fresh Godot process, and fingerprints the resulting UI state. New states are queued until the profile reaches its state, depth, run, action or stall limit.

The same seed and exact source/profile SHAs produce the same candidate ordering. Every transition retains:

- the source and target state IDs;
- the candidate label and device;
- the exact synthetic steps;
- process status and error findings;
- screenshots and report paths;
- whether the result was a new state, a known state, no change or no usable state.

Animated pixels are not used as the primary state identity because that would turn every animation frame into a false new state. Visual evidence is retained separately. A game can expose stronger game-specific state through existing assertions or metadata.

## Safety filters

Default control-text and action-name filters block terms such as `buy`, `checkout`, `delete`, `erase`, `format`, `overwrite`, `purchase`, `quit`, `reset` and `uninstall`. These are conservative defaults, not a universal safety model. Each game profile should add its own irreversible, account, network, destructive, save-wiping and release-related actions.

The worker also:

- refuses dirty or drifting Lab and target checkouts;
- requires the profile to be tracked by the exact target commit;
- runs from a bounded link-free `git archive` copy;
- rejects unresolved submodules rather than silently omitting them;
- writes evidence outside both repositories;
- gives each probe an isolated user-data root;
- holds a cross-process desktop lease;
- bounds total time, runs, states, depth, output and artifact bytes;
- kills the complete process tree on timeout or evidence overflow;
- verifies the original target checkout is unchanged on every exit path.

## Profile modes

`ui_graph` limits action discovery to UI actions and runtime controls. `action_fuzz` tests configured input actions without relying on control discovery. `mixed` combines both.

An empty `actionAllowlist` asks the worker to discover actions from the target InputMap. `actionDenylist` removes actions whose names contain a denied term. `blockedText` removes runtime controls whose path, name, class or visible text contains a blocked term.

Mouse candidates click the centre of a visible in-viewport interactive control. Keyboard and synthetic gamepad candidates use the first matching concrete InputMap event. Semantic candidates emit an `InputEventAction` as a fallback and are identified separately in the report.

## Evidence layout

```text
<run>/
  bot-agent-summary.json
  profile.normalized.json
  run-context.json
  source-archive.json
  hardware.json
  validation/
    report.json
    integrity-report.json
    engine-logs/
  campaigns/<campaign>/
    probes/<probe>/
      journey.normalized.json
      journey-report.json
      godot.log
      checkpoints/final.png
    representative-replays/<replay>/
      gameplay.avi
      ffprobe.json
      screenshots/
      contact-sheet.png
      checkpoints/
  logs/
```

`bot-agent-summary.json` contains the graph, traces, failures, representative replays, exact SHAs, profile hash, requested renderer/driver/GPU, hardware probes, validation result, execution budgets, target-mutation result and SHA-256 artifact inventory.

## How another chat uses it

A chat with local process access can run the CLI or PowerShell wrapper. Development Studio can dispatch the same exact-SHA request to the approved Windows worker. A chat with GitHub access alone can inspect source and retained evidence, but it cannot launch Greg's native game window or observe his GPU.

A useful repair loop is:

1. run canonical validation and bot QA against the exact failing target SHA;
2. inspect the first deterministic engine/build error or failed trace;
3. review the final checkpoint or representative replay;
4. grant the target repository a separate repair lease;
5. apply and validate the source fix in the target repository;
6. rerun the identical campaign seed and trace set against the repaired SHA;
7. record only the evidence boundary that actually passed.

## Truth boundaries

- Static integrity is diagnostic; matching-editor import is authoritative for Godot parsing and importing.
- A bounded boot proves startup, not complete gameplay.
- Synthetic input proves the declared Godot input path, not physical-device behaviour.
- Runtime graph exploration is bounded and cannot prove every state is reachable or safe.
- Fresh-process replay isolates most in-process state, but it does not emulate external accounts, servers or platform services.
- Screenshots and movies support visual review; they do not replace human judgment of art direction, game feel, pacing, accessibility or polish.
- Requested renderer, driver and GPU index plus retained logs are stronger than hardware inventory alone, but do not by themselves prove performance on every frame.
- CUDA is auxiliary compute capability and is not Godot's rendering backend.
