from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from .localization_stable_id_bundle import (
    StableIdBundleAdmissionError,
    admit_stable_id_application_bundle,
)
from .strict_json import StrictJsonError, load_strict_json_object

_MAX_BUNDLE_BYTES = 128 * 1024 * 1024


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="godot-lab-localization-stable-id-bundle",
        description=(
            "Independently admit exact stable-ID application-bundle bytes against one "
            "clean target Git head without applying, committing or publishing them."
        ),
    )
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        bundle, _ = load_strict_json_object(
            args.bundle,
            maximum_bytes=_MAX_BUNDLE_BYTES,
        )
        report = admit_stable_id_application_bundle(args.project_root, bundle)
    except (
        StableIdBundleAdmissionError,
        StrictJsonError,
        OSError,
        ValueError,
        subprocess.SubprocessError,
    ) as error:
        print(
            json.dumps(
                {
                    "version": "evavo_godot_stable_id_bundle_admission_report_v1",
                    "status": "blocked",
                    "error": str(error),
                    "authority": {
                        "targetRepositoryMutationAuthority": False,
                        "sourceMutationAuthority": False,
                        "runtimeRegistrationAuthority": False,
                        "commitAuthority": False,
                        "pushAuthority": False,
                        "releaseAuthority": False,
                        "publicationAuthority": False,
                    },
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2 if args.pretty else None,
            separators=None if args.pretty else (",", ":"),
            sort_keys=args.pretty,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
