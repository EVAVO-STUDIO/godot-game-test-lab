# Godot Game Test Lab capability manifest

`evavo.capabilities.json` is the bounded portfolio-discovery declaration for `EVAVO-STUDIO/godot-game-test-lab`. The Brain, Council, Development Studio and GitHub MCP can use it to discover what the current repository proves without turning repository names, historical documentation or planned features into authority.

The declaration is deliberately narrower than the repository's complete implementation inventory. It describes ten current capability groups and their effects, entrypoints and external requirements.

## Authority model

Test Lab is an **independent validation and evidence authority**, not a target-repository repair or publication authority.

It can:

- provision governed official Godot engines into managed storage outside target repositories;
- inspect and audit external Godot projects read-only;
- execute bounded validation, native journeys, deterministic bot QA and isolated Linux sandbox QA;
- retain bounded evidence and media-analysis outputs outside the target checkout;
- admit exact installed asset deliveries, visual-animation evidence and rig-motion evidence; and
- report explicit truth boundaries where machine evidence is not equivalent to human review.

It does not declare `publish` or `financial` effects. A passing Test Lab receipt is evidence for a downstream decision; it is not permission to edit, repair, deploy or publish a consumer repository.

## Declared capabilities

### `testlab.engine.provision`

Uses the governed engine lock and official `godotengine/godot-builds` release source, verifies managed engine identity and writes installation material/receipts outside target repositories. This is the only declared capability that requires `network` because online engine acquisition is optional and can be replaced by an approved offline source.

### `testlab.project.inspect-audit`

Runs bounded project inspection and integrity checks without executing or modifying the target project. It declares only `read` and `compute`.

### `testlab.project.validate-runtime`

Runs authoritative Godot validation and bounded runtime/import/build/record/export-evidence operations. Its `write` effect is for governed reports, artifacts and isolated runtime outputs; target repair and publication remain downstream.

### `testlab.qa.native-authored`

Runs target-authored journeys against exact Lab and target SHAs. The implementation requires clean exact checkouts, records target Git status before and after the run, fails on mutation, and marks non-interactive execution as contract testing rather than authoritative native desktop evidence.

### `testlab.qa.bot`

Runs deterministic fresh-process exploration through mapped mouse, keyboard, action and gamepad events. Required campaigns must prove a changed state and retain a passing non-baseline replay. The runner also verifies exact SHAs and fails if the target checkout changes. It explicitly does not claim complete gameplay coverage, physical-controller proof, accessibility, game feel or human visual approval.

### `testlab.sandbox.linux`

Runs the governed Docker sandbox with `--network none`, read-only container root, dropped capabilities, `no-new-privileges`, bounded resources and a read-only target-repository bind mount. Lab and target must be separate clean exact checkouts and retained evidence must remain outside both repositories. Linux software-rendered evidence is not native Windows GPU-performance evidence.

### `testlab.media.analyze`

Uses governed FFmpeg/FFprobe processing to analyse retained gameplay movies and synchronized audio under bounded policy. It can retain analysis artifacts but human mix and visual-quality judgment remain separate.

### `testlab.asset-delivery.admit`

Binds an exact game head, delivery bundle, storage admission and installed bytes into an independent report. The report keeps native composition approval and publication authority false and uses a create-only output path.

### `testlab.visual-animation.admit`

Verifies exact Art Studio candidate/frame bytes, SpriteFrames references and Godot import/render evidence. Its report keeps creative approval, historical approval and publication authority false. This is technical Test Lab admission, not an art-direction decision.

### `testlab.rig-motion.accept-v4.1`

Runs a hash-bound, isolated, headless Godot probe for supported rig families and requires measurable motion. The create-only receipt keeps runtime admission, target-repository mutation, Git mutation, deployment and publication false and requires named human review.

## Shared schema

The repository carries the shared EVAVO declaration contract at:

```text
schemas/evavo.repository-capabilities.schema.json
```

The manifest uses `evavo_repository_capabilities_v1` and the common effect vocabulary:

```text
read
compute
network
write
execute
publish
financial
```

The current Test Lab declaration contains no `publish` or `financial` effect.

## Source-bound validation

Run:

```powershell
python scripts/check_evavo_capability_manifest.py
```

The checker is dependency-free on Python 3.11+ and validates both declaration shape and live implementation evidence. It fails when:

- repository identity, schema, Brain consultation metadata or capability fields drift;
- the manifest contains anything other than the ten current capability IDs;
- effect boundaries change unexpectedly;
- a declared path entrypoint disappears or becomes a symlink;
- installed CLI bindings in `pyproject.toml` drift;
- the engine provisioner stops enforcing the governed official Godot source;
- the MCP bridge stops stating its no-target-edit/no-target-publication boundary;
- native or bot QA loses exact-SHA, clean-checkout or target-mutation detection;
- the Docker sandbox loses no-network/read-only/capability-drop/root-isolation controls;
- the media surface drifts away from bounded FFmpeg/FFprobe analysis;
- asset or visual admission begins claiming publication/native-composition/creative authority;
- rig-motion evidence loses exact hash binding, isolated headless execution, create-only output or its all-false mutation/deployment/publication boundary; or
- any Test Lab capability begins claiming publication or financial authority.

## Maintenance rule

Update `evavo.capabilities.json`, `scripts/check_evavo_capability_manifest.py`, this document and `.github/workflows/capability-manifest.yml` together when a live capability, effect, entrypoint or authority boundary changes.

Planned features do not belong in the manifest until current source and tests prove them. Conversely, removing a capability from implementation requires removing or narrowing its declaration in the same change.
