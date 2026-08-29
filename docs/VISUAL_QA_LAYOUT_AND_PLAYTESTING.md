# Godot visual QA, layout analysis and playtesting

The Godot Game Test Lab combines a rendered frame with same-state `Control` geometry so an agent can reason about what is visible and which semantic node produced it.

## Captured evidence

Each governed checkpoint can retain:

- a real PNG from the running Godot viewport;
- the visible `Control` tree;
- global rectangles and viewport inclusion;
- ancestor paths and ancestor clipping;
- focus mode, mouse filter and editable/disabled state;
- canvas layer, effective z-index and paint order;
- centre-point occlusion;
- interactive overlap and spacing pairs;
- target-size findings;
- the input-map and exact synthetic action history;
- performance samples and runtime logs.

Editable `LineEdit` and `TextEdit` values are never written to the telemetry record.

## Deliberate defect self-test

The repository includes `fixtures/visual-qa-overlap`, which intentionally contains:

- two overlapping buttons;
- two touching buttons;
- a button clipped by a parent container;
- a button blocked at its centre by a higher-z overlay.

The self-test is successful only when Godot actually launches the fixture, writes a non-uniform 640×360 PNG, retains checkpoint UI telemetry and detects every deliberate defect. Because the journey is deliberately invalid, its Godot process may exit non-zero; the self-test judges the retained evidence rather than mistaking that expected exit for an infrastructure failure.

```powershell
Set-Location C:\GitRepos\godot-game-test-lab
$Evidence = 'C:\EVAVO\visual-qa\godot-lab-self-test'
python -m godot_game_test_lab.visual_qa_self_test_runner `
  --lab-root $PWD `
  --artifacts $Evidence `
  --godot 'C:\Tools\Godot\Godot_v4.6.2-stable_mono_win64.exe'
```

For an offscreen renderer, add `--headless`. The receipt records whether the render used an interactive window or headless offscreen mode.

## Readiness doctor

```powershell
python -m godot_game_test_lab.visual_qa_doctor `
  --lab-root $PWD `
  --artifacts 'C:\EVAVO\visual-qa\godot-lab-self-test'
```

The doctor returns `locally-verified` only when the receipt is fresh, its exact source identity still matches, every evidence path remains confined to the admitted root, every hash and byte count matches, the screenshot still decodes as a visible non-uniform PNG, and all deliberate layout findings remain present.

A missing Godot runtime or missing receipt is reported as `source-present`, never as a physical pass.

## Real game campaigns

The fixture receipt validates the test-lab capability only. It does not validate an unrelated game. Each game campaign must run its own scenes, journey steps, viewports and input modes and retain new pixels, geometry, video and findings.

For menus and HUDs, use explicit checkpoints after settling. For gameplay and animation, retain video or ordered frames as well as checkpoints. A still frame cannot certify timing, flicker, transition quality, game feel or intermittent overlays.

## Recommended UX profile

```json
{
  "captureControlTree": true,
  "captureUiAtCheckpoints": true,
  "minimumInteractiveWidth": 24,
  "minimumInteractiveHeight": 24,
  "minimumInteractiveGap": 8,
  "maximumPairChecks": 50000,
  "maximumOutOfBoundsInteractive": 0,
  "maximumAncestorClippedInteractive": 0,
  "maximumOccludedInteractive": 0,
  "maximumOverlappingInteractivePairs": 0,
  "maximumCloseInteractivePairs": 0,
  "maximumSmallInteractiveTargets": 0,
  "failOnTruncatedLayoutAnalysis": true
}
```

Projects with deliberately dense controls can govern exceptions explicitly. Do not increase limits merely to make a failing run green; retain an audit note explaining the intended design.
