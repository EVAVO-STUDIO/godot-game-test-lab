# Art Studio asset-audit gate

Godot Game Test Lab can independently validate an EVAVO Art Studio bulk repository audit against the exact current bytes of a Godot project.

This closes the gap between an offline art review and the repository that Godot will actually import and run.

## Produce the Art Studio audit

From EVAVO Art Studio:

```powershell
pnpm art -- inspect `
  --repo C:\GitRepos\Brass_Brine `
  --output C:\GodotLabEvidence\Brass_Brine\art-audit.json
```

The report includes file SHA-256 values, supported decoded dimensions and PNG alpha use, role-specific transparency policies, source/resource demand, missing references, duplicate groups, animation families, optimization guidance and review-only cleanup candidates.

## Validate it from Test Lab

```powershell
godot-lab-asset-audit `
  C:\GitRepos\Brass_Brine `
  C:\GodotLabEvidence\Brass_Brine\art-audit.json `
  --output C:\GodotLabEvidence\Brass_Brine\art-audit-validation.json
```

The default policy fails closed when:

- the audit schema or analysis version is unsupported;
- a path is absolute, traversing, missing, symlinked or outside the project;
- current file size or SHA-256 differs from the audited identity;
- a current art, metadata or engine-resource file is absent from the audit;
- the audit records a file no longer present in the project;
- Art Studio still reports blocking findings;
- source or resource files reference missing media;
- a numbered animation family has missing indices;
- an animation family has inconsistent canvases;
- a PNG role that requires transparency does not independently prove meaningful alpha.

The command exits with code `0` only when the effective policy passes and `2` when it fails.

## Explicit migration allowances

Incomplete migrations can be inspected without weakening the default release gate:

```powershell
godot-lab-asset-audit `
  C:\GitRepos\Brass_Brine `
  C:\GodotLabEvidence\Brass_Brine\art-audit.json `
  --allow-unrecorded-assets `
  --allow-missing-references `
  --allow-animation-gaps `
  --allow-unverified-alpha
```

Each allowance is written into the JSON result. These switches are diagnostic authority, not approval authority. A release or final-media gate should omit them.

`--allow-unverified-alpha` exists for compressed or unsupported formats that require decoded runtime or media-toolchain evidence. It does not accept known opaque or fully transparent PNGs for alpha-required roles.

## MCP access for ChatGPT and Claude

Install the optional agent dependency and start the dedicated root-restricted server:

```powershell
pip install -e ".[agent]"

godot-lab-asset-audit-mcp `
  --lab-root C:\GitRepos\godot-game-test-lab `
  --allowed-root C:\GitRepos `
  --evidence-root C:\GodotLabEvidence
```

The server exposes:

```text
godot_asset_audit_capabilities
godot_validate_art_audit
```

An audit path may be relative to the selected target Git root or absolute beneath either that Git root or the configured evidence root. Symlink traversal and every other location fail closed.

The MCP server is deliberately separate from mutation tooling. It cannot edit, delete, move, commit, push or publish a target repository.

## Independent alpha proof

For supported non-interlaced 8-bit or 16-bit PNG greyscale-alpha and RGBA files, Test Lab independently decompresses and unfilters scanlines to distinguish:

```text
none
opaque-channel
meaningful
fully-transparent
unknown
```

This means an all-opaque RGBA file cannot pass merely because an alpha channel exists. It also means a fully transparent blank image is rejected.

The gate respects Art Studio's asymmetric role policy:

- dialogue close-ups ordinarily preserve authored opaque or black presentation stages;
- standing characters, crew cut-outs, UI icons, ship profiles and weather overlays require meaningful alpha;
- maps, backgrounds and document plates ordinarily preserve opaque authored plates.

## Truth boundaries

A passing asset audit proves current file identity and the declared source-level policy. It does not prove:

- artistic quality, historical authenticity or style consistency;
- Godot import or runtime rendering;
- WebP, SVG or compressed-alpha correctness unless separately decoded;
- animation feel in motion;
- physical Windows GPU presentation;
- human visual acceptance;
- deletion safety for dynamically referenced assets;
- release readiness.

Continue with matching-editor import, C# compilation where applicable, native or sandbox execution, retained captures, audio analysis and human review.
