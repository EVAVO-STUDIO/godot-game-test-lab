from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from .movie_source_identity import movie_source_identities
from .native_qa_common import NativeQaError

_ADAPTER_ALIASES = {
    "capture": "godot-game-test-lab.video-evidence",
    "temporal": "godot-game-test-lab.movie-temporal",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="godot-lab-movie-source-identity",
        description=(
            "Print clone-stable exact source identities for the fixed Godot movie capture and "
            "temporal-analysis providers."
        ),
    )
    parser.add_argument(
        "--adapter",
        choices=("all", "capture", "temporal"),
        default="all",
    )
    return parser


def source_identity_result(adapter: str = "all") -> dict[str, object]:
    identities = movie_source_identities()
    if adapter == "all":
        selected = identities
    else:
        adapter_id = _ADAPTER_ALIASES.get(adapter)
        if adapter_id is None:
            raise NativeQaError("adapter must be all, capture or temporal")
        selected = {adapter_id: identities[adapter_id]}
    return {
        "schema": "evavo.godot-movie-source-identities.v1",
        "status": "source-present",
        "ready": True,
        "workerAdmitted": False,
        "identities": selected,
        "truthBoundary": (
            "These hashes identify the current fixed movie capture and temporal-analysis source. "
            "They do not prove that either provider ran, produced evidence or was admitted as a worker."
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        result = source_identity_result(args.adapter)
    except (NativeQaError, FileNotFoundError, OSError, TypeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "schema": "evavo.godot-movie-source-identities.v1",
                    "status": "source-present",
                    "ready": False,
                    "workerAdmitted": False,
                    "error": str(error),
                },
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
