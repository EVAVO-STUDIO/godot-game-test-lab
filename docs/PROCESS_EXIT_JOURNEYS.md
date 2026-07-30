# Process-exit Godot journeys

## Purpose

Most interactive journeys complete inside the injected Godot harness and retain a `journey-report.json`. Some repository-owned QA scenes intentionally run their own bounded test suite and terminate the process with `SceneTree.Quit(...)`. A process-exit journey lets those scenes remain authoritative without weakening the ordinary journey-report contract.

The base runner remains unchanged. `run_agent_godot_qa_with_process_exit.py` delegates every journey to the canonical runner and applies this extension only when the profile explicitly opts in.

## Profile contract

A process-exit journey uses reserved `userArguments`:

```json
{
  "id": "compiled-regression",
  "required": true,
  "scene": "res://scenes/tools/RegressionLab.tscn",
  "userArguments": [
    "--run-regression-harness",
    "--evavo-agent-completion=process-exit",
    "--evavo-agent-require-output=[REGRESSION] PASS",
    "--evavo-agent-forbid-output=[REGRESSION] FAIL"
  ],
  "steps": [],
  "assertions": []
}
```

The reserved arguments are consumed by the test lab and are not passed to Godot:

- `--evavo-agent-completion=process-exit` enables this completion mode;
- one or more `--evavo-agent-require-output=<marker>` arguments are mandatory;
- zero or more `--evavo-agent-forbid-output=<marker>` arguments may reject explicit failure markers.

All other arguments are passed through unchanged to the target project. Markers are case-sensitive, bounded, single-line values. A marker is observed only when one complete retained stdout or stderr line equals it exactly. Prefixes, suffixes, log decorations and substring matches do not satisfy or trigger the marker contract. Blank, oversized or unsupported reserved arguments fail closed before execution.

## Pass rule

The wrapper may remove only the canonical finding:

```text
journey report was not produced
```

It does so only when all of the following are true:

1. the Godot process completed within its bounded timeout;
2. the observed exit code is exactly zero;
3. every required output marker appears as an exact retained output line;
4. no forbidden output marker appears as an exact retained output line;
5. the base journey has no other finding.

A crash, non-zero exit, timeout, error marker, missing marker, forbidden marker, black-frame finding, frozen-frame finding, screenshot failure or any other base-runner finding still fails the journey. Process-exit mode cannot turn an unrelated failure into a pass.

## Evidence

The ordinary process logs, movie, screenshots, contact sheet and visual review remain unchanged. The extension additionally writes:

```text
journeys/<journey-id>/process-exit-completion.json
```

That record includes the expected and observed exit state, required markers, observed markers, missing markers and forbidden markers. `visual-ux-review.json` and `agent-summary.json` retain the resulting status and evidence path.

## Truth boundary

A passing process-exit journey proves that one exact project revision built and imported through the canonical lane, launched the declared scene, exited successfully and emitted the declared machine markers without any other retained objective failure. It does not prove a complete playthrough, physical controller behavior, native GPU performance, final art quality, accessibility approval or human UX acceptance.
