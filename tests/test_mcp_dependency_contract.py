from __future__ import annotations

import subprocess
import sys
import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PINNED_MCP_VERSION = "1.29.1"


def test_agent_extra_pins_warning_fixed_mcp_release() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["optional-dependencies"]["agent"] == [
        f"mcp=={PINNED_MCP_VERSION}"
    ]


def test_fastmcp_settings_complete_without_lifespan_warning() -> None:
    try:
        installed_version = version("mcp")
    except PackageNotFoundError:
        pytest.skip("The optional MCP agent dependency is not installed")
    assert installed_version == PINNED_MCP_VERSION

    source = """
import warnings
from importlib.metadata import version

warnings.filterwarnings(
    "error",
    message=r"Field 'lifespan' has an incomplete definition.*",
)
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import Settings

assert version("mcp") == "1.29.1"
assert Settings.__pydantic_complete__ is True
server = FastMCP(name="EVAVO MCP settings regression")
assert server.name == "EVAVO MCP settings regression"
"""
    result = subprocess.run(
        [sys.executable, "-c", source],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
