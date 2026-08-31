# EVAVO Game Runtime native provider transfer suite

This Test Lab suite validates the boundary between native platform callbacks
and the shared verified EVAVO package cache.

The suite runs:

```text
dependency_free_validator
headless_import_parse
native_provider_transfer_behavior
```

It records exact runtime and Test Lab Git SHAs, Godot version, clean working
state, per-scenario logs and the required pass marker.

The behavior scenario checks strict callback ordering, native chunk-handle
ownership, event and manifest digest validation, terminal cancellation,
protected restart reconciliation and fail-closed delegated bridge creation.

The suite does not prove that a native SDK is installed merely because a
platform mapping exists. It does not grant content availability, does not grant
scene activation and does not grant simulation authority. Native provider
completion still has to pass the shared package cache, trusted release and
activation layers.

Run on Windows:

```powershell
.\scripts\run-evavo-game-runtime-native-provider-transfer.ps1 `
    -RuntimeRepo C:\GitRepos\evavo-game-runtime `
    -GodotPath $env:GODOT_BIN
```

Run cross-platform:

```text
python scripts/run-evavo-game-runtime-native-provider-transfer.py \
    --runtime-repo /path/to/evavo-game-runtime \
    --godot /path/to/godot \
    --artifact-root artifacts/native-provider-transfer
```
