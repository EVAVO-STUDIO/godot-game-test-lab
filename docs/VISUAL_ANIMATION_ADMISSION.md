# Brass visual and animation Test Lab admission

This independent gate consumes Art Studio static and animation evaluations plus
engine-owned import evidence. It reopens current candidate and frame bytes,
checks every evidence hash, verifies the intended SpriteFrames resource refers
to every frame, and requires exact Godot version, renderer, game head and
zero-error import evidence.

```powershell
py -3 -m godot_game_test_lab.visual_animation_admission `
  --game-root C:\GitRepos\Brass_Brine `
  --candidate-root C:\EVAVO-Evidence\Brass_Brine\staging\candidates `
  --frame-root C:\EVAVO-Evidence\Brass_Brine\staging\frames `
  --static-evaluation C:\EVAVO-Evidence\Brass_Brine\creative\candidate.json `
  --animation-evaluation C:\EVAVO-Evidence\Brass_Brine\animation\evaluation.json `
  --engine-evidence C:\EVAVO-Evidence\Brass_Brine\runtime\godot-import.json `
  --game-head <exact-40-character-head> `
  --output C:\EVAVO-Evidence\Brass_Brine\runtime\visual-animation-admission.json
```

The engine evidence schema is `evavo.godot-visual-animation-import-evidence.v1`.
It records the exact game head, Godot version, renderer, candidate/frame hashes,
SpriteFrames load, first-frame render, final or loop-end render, import errors and
console errors.

The resulting report is
`evavo.brass-visual-animation-test-lab-report.v1`. It is technical runtime
evidence, not creative, historical or publication approval. The validator never
changes candidates, resources or the game repository and does not itself launch
Godot.
