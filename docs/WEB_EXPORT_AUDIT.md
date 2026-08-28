# Godot Web Export Audit

`godot-lab-web-export-audit` independently checks one generated Godot 4 web export before it is mounted by Godot Web Runtime. It is deliberately local, bounded and read-only, so it does not need GitHub Actions, Vercel builds or a hosted browser worker.

## What it proves

The audit verifies that:

- `export.json` is a bounded UTF-8 JSON object using descriptor schema version 2.
- The descriptor identifies a safe executable, the Compatibility renderer and a supported single-threaded or threaded web profile.
- The generated JavaScript loader, WebAssembly module and PCK use the expected executable basenames.
- Every integrity-bound file is a regular non-linked file inside the export root.
- Every declared SHA-256 digest and optional byte size matches the exact file read by the audit.
- Encoded traversal, absolute URLs, query strings, fragments, backslashes, duplicate normalized paths, symlinks and special files are rejected.
- Threaded exports retain either the Godot PWA isolation setting or explicit COOP and COEP hosting-header evidence.
- Signature envelopes have the expected shape. Cryptographic approval remains unverified unless a separate trusted-key process verifies the signature.

The audit also rechecks file identity around hashing so a bundle that changes while it is being inspected is rejected rather than receiving a stale receipt.

## Run locally

```powershell
python -m pip install -e .
godot-lab-web-export-audit C:\Path\To\WebExport `
  --descriptor C:\Path\To\WebExport\export.json `
  --output C:\Path\To\Evidence\web-export-audit.json
```

For a threaded deployment with retained hosting headers:

```powershell
godot-lab-web-export-audit C:\Path\To\WebExport `
  --headers C:\Path\To\Deployment\_headers `
  --warnings-as-errors `
  --output C:\Path\To\Evidence\web-export-audit.json
```

The command exits with `0` only when the technical audit and selected warning policy pass. It exits with `2` for rejected, blocked or warning-as-error results.

## Evidence and truth boundary

The JSON report records the scanned file count, bounded byte total, selected profile, executable, verified asset count and stable finding codes. It proves local descriptor and exact-byte consistency only. It does not prove HTTPS delivery, browser startup, WebGL 2 behavior, service-worker activation, audio unlock, input focus, GPU performance, responsive presentation or visual quality. Those require a separate real-browser run against the exact audited bundle.
