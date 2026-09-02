# EVAVO Game Runtime HTTP Range Hardening

This external Test Lab lane verifies that the Runtime does not mark a multi-range HTTPS source as production-ready without a strong validator. It requires a strong quoted ETag, exact `If-Range` behavior, weak-validator rejection, duplicate-header rejection and strict source-host validation.

The runner records exact Runtime and Test Lab Git SHAs, clean repository state and the exact Godot 4.6.2 version before executing the dependency-free validator, headless import and hardening behavior test.

The suite does not grant content availability, scene activation or simulation authority. Those remain later independent Runtime gates.
