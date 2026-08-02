from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AMBIGUOUS_VARIABLE_COLON = re.compile(r"(?<!\{)\$([A-Za-z_][A-Za-z0-9_]*):")
POWERSHELL_SCOPES = {
    "alias",
    "env",
    "function",
    "global",
    "local",
    "private",
    "script",
    "using",
    "variable",
}


def test_powershell_strings_do_not_use_ambiguous_variable_colons() -> None:
    findings: list[str] = []
    for path in sorted((ROOT / "scripts").glob("*.ps1")):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in AMBIGUOUS_VARIABLE_COLON.finditer(line):
                if match.group(1).casefold() in POWERSHELL_SCOPES:
                    continue
                findings.append(f"{path.name}:{line_number}: ${match.group(1)}:")
    assert findings == []
