# Godot plural localization runtime validation

Godot Game Test Lab owns native proof for structured localization artifacts produced by EVAVO Localization Manager.

The specialization consumes:

```text
localization-godot-plural-testlab-request-v1
```

and emits:

```text
evavo_godot_plural_localization_test_lab_report_v1
```

It remains part of the existing `testlab.project.validate-runtime` authority. It does not create a second engine or publication authority.

## Canonical invocation

Until the package console alias is reconciled with concurrent Test Lab packaging work, use the guarded module entrypoint directly:

```powershell
python -m godot_game_test_lab.localization_plural_runtime_cli `
  C:\GitRepos\Brass_Brine `
  --request C:\EVAVO-Evidence\Brass_Brine\localization\plural-testlab-request.json `
  --artifacts C:\EVAVO-Evidence\Brass_Brine\localization\test-lab
```

Optional explicit tools:

```powershell
  --godot C:\path\to\godot.exe `
  --dotnet C:\path\to\dotnet.exe
```

Without `--godot`, the CLI delegates engine selection/provisioning to the existing Test Lab engine manager unless `--no-auto-provision-engine` is set.

## Validation chain

The validator fails closed unless all of these conditions are satisfied:

1. request JSON is bounded and its SHA-256 matches the Localization Manager canonical fingerprint;
2. target Git origin matches the requested `EVAVO-STUDIO/<repository>` identity;
3. current target `HEAD` matches the exact lowercase 40-character request SHA;
4. requested CSV path is project-relative, resolves inside the selected Godot project, is not symlinked and points to a real file;
5. CSV SHA-256 and byte count match the request and the file is UTF-8 without BOM;
6. artifacts directory resolves outside the target Git repository;
7. the existing `validate_project_pipeline()` passes static integrity, tool/version checks, required .NET build, authoritative Godot import, recovery diagnostics and bounded headless boot;
8. every requested plural runtime probe is executed through `TranslationServer.translate_plural()` after setting the requested Godot locale;
9. each returned string exactly equals the request's expected localized text;
10. CSV bytes remain unchanged after validation;
11. target Git `HEAD`, origin and full porcelain status remain identical to their pre-validation evidence;
12. the transient probe execution file is removed before acceptance.

## Global command guard boundary

Test Lab's global subprocess guard deliberately rejects external Godot path operands. The localization validator does **not** weaken that policy.

Instead:

- the evidence copy of the generated GDScript is stored outside the target repository;
- a byte-identical transient copy is placed beneath `.godot/evavo-test-lab/` only for execution;
- a pre-existing symlinked `.godot` cache is rejected;
- the transient file is removed in `finally`;
- post-run Git state must exactly match pre-run Git state;
- evidence/log/report files remain outside the repository.

The native Godot import itself may update normal ignored `.godot` cache data. That is engine cache activity, not source publication authority. Any source-controlled or visible Git-state drift makes the validation fail.

## Runtime probe semantics

Localization Manager does not invent which integer count proves each reviewed Godot positional form. The request carries a human-reviewed probe mapping, for example:

```json
{
  "locales": {
    "en": [
      { "formKey": "one", "n": 1 },
      { "formKey": "*", "n": 2 }
    ],
    "cs": [
      { "formKey": "one", "n": 1 },
      { "formKey": "few", "n": 2 },
      { "formKey": "*", "n": 5 }
    ]
  }
}
```

The Test Lab request expands that mapping into exact message/locale/count/expected-text probes. Test Lab verifies the requested runtime behavior; it does not reinterpret the linguistic profile.

A lookup that falls back to the untranslated stable key or source text fails the expected-text comparison. That means the same probe also detects missing translation-resource registration/loading for the tested locale/key pair.

## Report authority

A passing report may assert:

```text
requestFingerprintVerified = true
exactTargetHeadVerified = true
exactCsvBytesVerified = true
nativeGodotImportVerified = true
runtimePluralLookupVerified = true
targetGitStateUnchanged = true
transientProbeRemovedBeforeAcceptance = true
```

It always keeps these false:

```text
targetRepositoryMutationAuthority
repairAuthority
publicationAuthority
```

Native success is evidence for downstream Development Studio/product release decisions; it is not publication itself.

## Contracts

Schemas:

```text
schemas/localization-godot-plural-testlab-request.v1.schema.json
schemas/evavo-godot-plural-localization-test-lab-report.v1.schema.json
```

Implementation:

```text
src/godot_game_test_lab/localization_plural.py
src/godot_game_test_lab/localization_plural_safe.py
src/godot_game_test_lab/localization_plural_runtime.py
src/godot_game_test_lab/localization_plural_runtime_cli.py
```

Canonical callers should use `localization_plural_runtime.py` / `localization_plural_runtime_cli.py`. The earlier lower-level modules remain implementation history and must not be treated as the final guarded entrypoint.
