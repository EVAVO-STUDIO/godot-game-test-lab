"""Godot Game Test Lab."""

from .command_guard import install as _install_command_guard

__all__ = ["__version__"]
__version__ = "0.8.0"

_install_command_guard()
del _install_command_guard
