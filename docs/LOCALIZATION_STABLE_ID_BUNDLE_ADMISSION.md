# Stable-ID application-bundle admission

Godot Game Test Lab independently admits the exact bytes in a Localization Manager stable-ID application bundle before any product-owned worker is allowed to apply them.

The capability consumes:

```text
localization-godot-stable-id-application-bundle-v1
```

and emits to standard output:

```text
evavo_godot_stable_id_bundle_admission_report_v1
```

It is intentionally read-only. It does not execute Godot, apply the proposed scene bytes, create the source-locale CSV, register translations, commit, push, release or publish anything.

## Canonical command

```powershell
godot-lab-localization-stable-id-bundle `
  C:\GitRepos\TargetGodotGame `
  --bundle C:\EVAVO-Evidence\stable-id-application-bundle.json `
  --pretty
```

The bundle JSON is read through the repository's bounded strict-JSON loader. Duplicate properties, UTF-8 BOMs, symlinked evidence paths, non-finite numbers and unstable reads are rejected.

## Admission checks

The validator fails closed unless all of these conditions are satisfied:

1. the bundle has the exact reviewed field surface and an intact canonical SHA-256;
2. every authority field in the bundle remains false;
3. the selected path is the exact Git repository root;
4. the target origin matches the requested `EVAVO-STUDIO/<repository>` identity;
5. target `HEAD` equals the bundle's exact lowercase 40-character head;
6. the target is clean, including untracked files;
7. every replacement path is safe, tracked, non-symlinked and an existing `.tscn` file;
8. current target bytes match the bundle's before byte count, SHA-256, Git blob and exact-head Git object;
9. every proposed base64 payload is canonical, bounded UTF-8 and matches its after byte count, SHA-256 and Git blob;
10. each proposed scene assigns every declared stable ID exactly once;
11. the source-locale CSV path is safe, non-symlinked and does not already exist;
12. CSV bytes, row order, source texts and source-text fingerprints exactly match the retained message provenance;
13. the source-catalog stable IDs exactly equal the proposed scene replacement IDs;
14. the retained byte total is exact;
15. target Git state and current source bytes remain unchanged after admission;
16. the source-locale CSV path remains absent.

## Report boundary

A passed report may assert exact bundle, target-head, current-byte, proposed-byte, source-catalog and non-mutation checks.

It always leaves these false:

```text
targetRepositoryMutationAuthority
sourceMutationAuthority
runtimeRegistrationAuthority
commitAuthority
pushAuthority
releaseAuthority
publicationAuthority
```

Admission means the proposed bytes are internally consistent with the exact clean target head. It does not mean those bytes have been applied or that Godot can import and render them.

## Later gates

After an independent bundle admission, a separate product-owned application authority must still:

1. stage the exact bytes outside the target repository;
2. verify every staged hash;
3. apply replacements atomically with rollback evidence;
4. prove the exact changed-path set and run product source checks;
5. invoke Godot Game Test Lab runtime import and stable-key lookup validation;
6. retain native pseudolocalized layout evidence;
7. obtain separate linguistic, release and publication approval.

A pending Brass & Brine stable-ID review remains pending until a named human records the complete decision. This capability cannot infer or manufacture that decision.
