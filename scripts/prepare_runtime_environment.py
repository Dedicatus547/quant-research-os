#!/usr/bin/env python3
"""Describe, prepare or verify bounded-local-01621/v1 without provider/science calls."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quantos.infrastructure.runtime_environment import (  # noqa: E402
    describe_environment,
    prepare_environment,
    verify_environment,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("describe", "prepare", "verify"))
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--artifact-source", type=Path, action="append", default=[])
    parser.add_argument("--base-python", type=Path)
    parser.add_argument("--uv", type=Path)
    parser.add_argument("--qlib-source", type=Path)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    if args.operation != "describe" and args.output is None:
        parser.error("--output is required")
    if args.operation == "prepare" and any(
        getattr(args, name) is None for name in ("base_python", "uv", "qlib_source")
    ):
        parser.error("prepare requires --base-python, --uv and --qlib-source")
    try:
        if args.operation == "describe":
            result = describe_environment(args.profile, tuple(args.artifact_source))
        elif args.operation == "verify":
            result = verify_environment(args.output, args.profile)
        else:
            result = prepare_environment(
                args.profile,
                args.output,
                base_python=args.base_python,
                uv=args.uv,
                source=ROOT,
                qlib_source=args.qlib_source,
                artifact_sources=tuple(args.artifact_source),
                download=args.download,
            )
    except Exception as error:
        # Never print third-party exception messages, causes or configuration contents.
        print(
            json.dumps(
                {
                    "execution": "FAILED",
                    "error_type": type(error).__name__,
                    "validation": "NOT_EVALUATED",
                    "qualification": "NOT_QUALIFIED",
                }
            )
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
