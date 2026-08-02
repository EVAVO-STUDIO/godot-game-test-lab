# Godot Lab Linux sandbox

This image is the isolated compatibility lane for Godot projects. The image is
built in two flavours:

- `standard` for GDScript projects;
- `mono` for projects containing C# projects.

Each image contains a checksum-verified official Godot editor, matching export
templates, .NET 8, FFmpeg/FFprobe, Xvfb, Mesa llvmpipe and Vulkan utilities. The
runtime container receives no network, has a read-only root filesystem, drops
all Linux capabilities, applies `no-new-privileges`, mounts target source
read-only, and writes only to its ephemeral work mount and external evidence
mount.

Build both local images:

```powershell
.\scripts\Build-GodotLabSandboxes.ps1 -GodotVersion 4.6.3
```

```bash
./scripts/build-godot-lab-sandboxes.sh
```

Run any external repository through the sandbox:

```powershell
.\scripts\Invoke-GodotLabSandbox.ps1 `
  -TargetRepositoryPath C:\GitRepos\MY-GAME `
  -ProfilePath .evavo\godot-lab-linux.json
```

```bash
TARGET_REPOSITORY_PATH="$HOME/GitRepos/MY-GAME" \
PROFILE_PATH=.evavo/godot-lab-linux.json \
./scripts/invoke-godot-lab-sandbox.sh
```

The wrapper chooses the `mono` image automatically when it detects a `.csproj`.
When no profile is supplied it creates a bounded baseline import, boot and
visual profile. Game-specific mouse, keyboard, semantic-action and synthetic
controller journeys belong in the target repository's tracked profile.

This lane proves Linux import, build, execution and software-rendered evidence.
It does not prove native Windows GPU behavior, physical-controller behavior or
human art/audio approval.
