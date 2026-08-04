# Art Studio asset-audit gate

Godot Game Test Lab validates an EVAVO Art Studio repository audit against the
stable current bytes of one exact Godot project. The two repositories remain
separate: Art Studio describes media demand and policy; Test Lab independently
proves what the target checkout currently contains before Godot import and
runtime acceptance.

## Produce the governed Art Studio audit

Use the current EVAVO Art Studio repository inspector:

```powershell
Set-Location C:\GitRepos\evavo-art-studio
pnpm art -- inspect `
  --repo C:\GitRepos\Brass_Brine `
  --output C:\GodotLabEvidence\Brass_Brine\art-audit.json
```

The supported producer contract is Art Studio schema `1.0`, analysis `1.0`. It
contains exact SHA-256 identities, role and transparency policy, bounded image
evidence, source/resource demand, missing references, exact duplicate groups,
animation families, cleanup candidates, summary counts and explicit audit rules.

## Validate current target bytes

Run from the installed Test Lab package or source checkout:

```powershell
python -m godot_game_test_lab.asset_audit `
  C:\GitRepos\Brass_Brine `
  C:\GodotLabEvidence\Brass_Brine\art-audit.json `
  --expected-target-sha (git -C C:\GitRepos\Brass_Brine rev-parse HEAD) `
  --require-clean-target `
  --evidence-root C:\GodotLabEvidence `
  --output Brass_Brine\art-audit-validation.json
```

The release-oriented default is fail-closed. It rejects:

- duplicate JSON properties, invalid UTF-8, BOMs, unstable files, unknown schema
  properties and wrong JSON authority types;
- absolute, traversing, Windows-ambiguous, device-name, case-colliding,
  Unicode-colliding, linked or reparse-point paths;
- a non-Godot or truncated producer audit;
- incomplete duplicate, cleanup, missing-reference, animation or summary
  authority;
- absent audited files and current art/resource files omitted from the audit;
- size or SHA-256 drift;
- malformed PNG structure, CRC errors, invalid chunk ordering, invalid filters,
  truncated scanlines and trailing bytes;
- audited dimensions, colour model, bit depth, alpha or probe-completeness that
  disagree with independent current-byte evidence;
- opaque or blank media in roles that require meaningful alpha;
- missing animation indices or independently inconsistent frame canvases;
- dirty or wrong-SHA target source when the corresponding authority is requested;
- source, inventory or file identity changes during the decision;
- evidence output outside the configured external evidence root;
- silent overwrite of an arbitrary or unrelated existing file.

Every admitted asset is read through a stable bounded descriptor and hashed. The
same asset is read and hashed again before the decision is returned. The project
inventory and Git state are also checked before and after validation.

The result uses schema `1.1`. Exit code `0` means the effective policy passed;
exit code `2` means it failed or the command could not establish its authority.

## Diagnostic allowances

Migration review can enable narrowly scoped allowances:

```powershell
python -m godot_game_test_lab.asset_audit `
  C:\GitRepos\Brass_Brine `
  C:\GodotLabEvidence\Brass_Brine\art-audit.json `
  --allow-unrecorded-assets `
  --allow-missing-references `
  --allow-animation-gaps `
  --allow-unverified-alpha
```

The result records every allowance. They convert only the corresponding finding
to a warning. They do not accept a known opaque or fully transparent image for an
alpha-required role, bypass exact bytes, permit target writes, or create release
approval.

`--allow-unverified-alpha` is intended for AVIF, TIFF, EXR, HDR, compressed WebP,
SVG and other media whose final alpha requires a decoded runtime or media-tool
proof. Supported non-interlaced 8-bit and 16-bit PNG greyscale-alpha and RGBA
files are decoded independently and do not use this allowance.

## Output policy

Without `--output`, the command writes JSON only to stdout. With `--output`, the
result must remain strictly beneath `--evidence-root`. Relative output paths are
resolved beneath that root.

Output is create-only by default. `--replace-output` may refresh only a strict
existing Godot Lab `art-studio-asset-audit` report. A client configuration,
combined JSON file, directory, link or unrelated evidence file is preserved and
rejected. Writes use a same-directory temporary file, UTF-8 without a BOM and an
exclusive create or checked atomic replacement.

## MCP access

Install the pinned optional agent dependency and start the dedicated bridge:

```powershell
python -m pip install --disable-pip-version-check -e ".[agent]"

python -m godot_game_test_lab.asset_audit_mcp `
  --lab-root C:\GitRepos\godot-game-test-lab `
  --allowed-root C:\GitRepos `
  --evidence-root C:\GodotLabEvidence
```

The bridge exposes:

```text
godot_asset_audit_capabilities
godot_validate_art_audit
```

It resolves the exact target Git root, requires an explicit `project_subpath`
when a repository contains multiple Godot projects, can bind an expected target
SHA and defaults to a clean target checkout. An audit may be inside the selected
target repository or the configured evidence root. Optional retained results are
confined to the evidence root.

The bridge owns no managed-engine cache because this stage does not launch Godot.
It does not import private agent-bridge helpers and grants no arbitrary shell,
target write, file deletion, Git mutation, commit, push, release or deployment
authority. Streamable HTTP is loopback-only; stdio remains the default.

## Transparency policy

The gate preserves Art Studio's asymmetric role contract:

- dialogue close-ups ordinarily retain an authored opaque or black presentation
  stage;
- standing characters, crew cut-outs, UI icons, ship profiles, weather overlays
  and animation frames require meaningful transparency;
- port maps, backgrounds and document plates ordinarily remain opaque authored
  plates;
- unknown or editable-source roles remain review-required rather than receiving
  an invented transparency policy.

A present alpha channel is not proof of transparency. Independent evidence
separates `none`, `opaque-channel`, `meaningful`, `fully-transparent` and
`unknown`.

## Truth boundaries

A passing result proves current file identity and the declared source-level audit
contract. It does not prove artistic quality, style consistency, historical
accuracy, animation feel, Godot import, runtime rendering, GPU behaviour,
physical controller behaviour, accessibility, deletion safety, final mix or
release readiness.

Continue with the matching Standard or .NET editor, C# compilation when needed,
Godot import, bounded boot, native or no-network sandbox journeys, retained image
and audio evidence, and final human review.
