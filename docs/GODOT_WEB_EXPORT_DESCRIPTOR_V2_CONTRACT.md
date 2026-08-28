# Godot web export descriptor v2 contract

Godot Game Test Lab independently audits schemaVersion 2 web export bundles produced by `EVAVO-STUDIO/godot-web-runtime`.

## Canonical fixture

The retained Test Lab fixture is:

```text
tests/fixtures/generated-descriptor.v2.json
```

Its Web Runtime counterpart is:

```text
packages/godot-loader/fixtures/generated-descriptor.v2.json
```

Development Studio can compare these files byte for byte during local estate validation. `tests/test_web_export_contract_fixture.py` materializes the declared JS, WASM and PCK assets, proves the canonical fixture passes the independent audit and proves tampered bytes fail both size and SHA-256 checks.

## Audit command

```powershell
godot-lab-web-export-audit C:\path\to\web-export
```

The export root must contain `export.json` and the exact local assets it declares. A threaded descriptor must declare isolation intent or be accompanied by retained COOP/COEP header evidence accepted by the audit command.

## Authority boundary

The Test Lab may prove bounded descriptor structure, safe local references, exact sizes, SHA-256 identities, required JS/WASM/PCK coverage and threaded-isolation evidence. It does not:

- execute a browser;
- prove HTTPS delivery, service workers, GPU behavior or visual quality;
- cryptographically verify a release signature merely because an envelope is present;
- edit, repair, deploy or publish the target game;
- replace Web Runtime browser evidence;
- replace native Godot import, boot or desktop evidence.

Any target repair or publication remains a separate Development Studio action bound to the exact target repository head.
