# Automated Testing readiness contract

Godot Game Test Lab exposes one deliberately narrow, read-only readiness probe for `EVAVO-STUDIO/automated-testing`:

```text
python scripts/automated_testing_probe.py --json
```

The probe emits contract:

```text
evavo_godot_game_test_lab_probe_v1
```

It exists so Automated Testing can distinguish **repository presence**, **specialist tooling availability**, and **native Godot execution readiness** without selecting or running a game project.

## Readiness semantics

`ready=true` means at least one compatible Godot editor is already available through the normal Lab doctor surface or a previously validated managed engine installation exists.

The probe may still report static-audit, media-QA, Linux-sandbox or MCP capability while `ready=false`. Automated Testing must interpret that state as degraded rather than as executable native gameplay readiness.

The probe does not:

- select a target project;
- import, build, boot or run a Godot project;
- create a managed engine installation;
- download engine assets or use network provisioning;
- mutate this repository or any target repository;
- return Godot, .NET, project or managed-engine filesystem paths;
- claim gameplay, visual quality, game feel or human approval.

## Consumer boundary

Automated Testing registers this exact fixed probe in `config/external-worker-probes.json`. The consumer may execute only the tracked script above with `--json`, under a credential-stripped environment, `shell:false`, bounded output and timeout.

A successful probe is **readiness evidence only**. It is not a leased campaign, test pass, build pass, native runtime pass or gameplay receipt.

Actual Godot execution remains owned by Godot Game Test Lab through its reviewed native validation, authored QA, bot QA, media QA and sandbox interfaces. Automated Testing may coordinate those capabilities but must not duplicate or widen them into arbitrary Godot commands.
