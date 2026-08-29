# Semantic UI layout evidence

Native visual QA records rendered pixels and a same-state semantic description of visible Godot `Control` nodes. The geometry lane is deterministic evidence for layout defects; it is not a substitute for inspection of screenshots, motion, game feel, content, or accessibility.

## Evidence captured

Each retained state can contain:

- viewport dimensions;
- visible and interactive control counts;
- global control rectangles;
- control paths, parent paths, and ancestor paths;
- focus, mouse-filter, disabled, and editable state;
- clipping by the viewport or a clipping ancestor;
- canvas layer, local and effective z-index, and paint order;
- centre-point occlusion by a higher rendered control;
- overlap area and coverage ratios;
- spacing between adjacent interactive controls;
- explicit truncation flags when a bounded capture limit is reached.

Editable `LineEdit` and `TextEdit` values are never copied into semantic evidence. Their geometry and interaction state are retained, while their text is emitted as an empty string with `inputTextRedacted: true`.

## Checkpoint model

A `checkpoint` journey step writes both a PNG and, unless disabled, the UI telemetry for that exact settled state. The final PNG is paired with the final UI telemetry in the journey report. The postprocessor analyses every checkpoint and the final state, then writes `ui-layout-analysis.json` beside the journey evidence.

Use `captureUiAtCheckpoints: false` only where checkpoint geometry would exceed an explicitly reviewed evidence budget. Final-state UI telemetry is still retained.

## Governed admission

Findings and admission are separate:

1. Every detected issue is retained in the analysis, including issues allowed by a profile.
2. A journey fails only when a state exceeds its normalized budget, lacks required focus or visible controls, or reaches a capture bound while `failOnTruncatedLayoutAnalysis` is enabled.
3. A configured allowance does not make a defect disappear. It records that the state remains inside the project’s declared tolerance.

The governed fields are:

| Field | Default | Meaning |
|---|---:|---|
| `minimumVisibleControls` | `0` | Minimum visible controls per retained state. |
| `requireFocusOwner` | `false` | Require a GUI focus owner at every retained state. |
| `minimumInteractiveWidth` | `24` | Width below which a target is undersized. |
| `minimumInteractiveHeight` | `24` | Height below which a target is undersized. |
| `minimumInteractiveGap` | `8` | Minimum axis gap between adjacent interactive controls. |
| `maximumOutOfBoundsInteractive` | `0` | Allowed viewport-clipped controls. |
| `maximumAncestorClippedInteractive` | `0` | Allowed controls clipped by ancestors. |
| `maximumOccludedInteractive` | `0` | Allowed centre-occluded controls. |
| `maximumOverlappingInteractivePairs` | `0` | Allowed overlapping interactive pairs. |
| `maximumCloseInteractivePairs` | `32` | Allowed adjacent pairs below the gap target. |
| `maximumSmallInteractiveTargets` | `8` | Allowed undersized interactive targets. |
| `maximumPairChecks` | `50000` | Bound on pairwise geometry work. |
| `failOnTruncatedLayoutAnalysis` | `false` | Fail when capture or pair analysis reaches a bound. |

For strict release journeys, set all defect allowances to zero, require focus where keyboard or gamepad navigation is expected, retain checkpoint telemetry, and enable truncation failure.

## Truth boundary

A passing geometry receipt proves only that the retained semantic states remained within the normalized limits. It does not prove that colours, typography, animation timing, visual hierarchy, imagery, game feel, language, or unseen states are acceptable. Those require their corresponding rendered and human or model-review evidence.
