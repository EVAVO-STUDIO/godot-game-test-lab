# Game-asset delivery admission

Godot Game Test Lab independently reopens the exact Art Studio delivery bundle, EVAVO Storage admission, target game checkout, installed files and optional native Godot evidence.

The admission states are deliberately separate:

- `review-required`: Art Studio delivery or Storage admission still requires named review.
- `source-passed-native-pending`: every installed byte and source contract passed, but no native Godot evidence was supplied.
- `passed`: source admission passed and exact Godot 4.6.2-or-later native evidence covered every required visual role without import or console errors.

A technical native pass sets `nativeEvidencePassed=true`. It does not create creative, historical, native-composition, provenance, repository mutation, Git, publication or force-push approval.

```powershell
python -m godot_game_test_lab.game_asset_delivery_admission `
  --game-root C:\GitRepos\Brass_Brine `
  --game-head <exact-40-character-sha> `
  --delivery D:\EVAVO-Evidence\delivery.json `
  --storage-admission D:\EVAVO-Evidence\storage-admission.json `
  --native-evidence D:\EVAVO-Evidence\native-evidence.json `
  --output D:\EVAVO-Evidence\test-lab-admission.json
```

The output is create-only and self-hashed. Evidence files remain outside the target repository.
