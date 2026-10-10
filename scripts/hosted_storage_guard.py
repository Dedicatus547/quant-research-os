#!/usr/bin/env python3
"""Supervise one explicitly budgeted HM job; never performs Windows maintenance."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from quantos.infrastructure.hosted_storage import (
    HASH_ENV,
    POLICY_ENV,
    StorageRejected,
    configured_guard,
    require_bounded_bwrap,
    supervise_storage_job,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--policy-sha256", required=True)
    parser.add_argument(
        "--stage", choices=("deployment", "ci", "matrix", "export", "replay"), required=True
    )
    parser.add_argument("--expected-new-bytes", type=int, required=True)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    os.environ[POLICY_ENV] = str(args.policy)
    os.environ[HASH_ENV] = args.policy_sha256
    try:
        guard = configured_guard()
        if args.check_only:
            guard.check(args.expected_new_bytes)
            require_bounded_bwrap()
        else:
            command = tuple(args.command[1:] if args.command[:1] == ["--"] else args.command)
            if not command:
                parser.error("an explicit command is required")
            supervise_storage_job(
                guard, command, stage=args.stage, expected_new_bytes=args.expected_new_bytes
            )
    except StorageRejected as error:
        print(str(error))
        raise SystemExit(1) from None
    except (OSError, ValueError, KeyError, TypeError):
        print("STORAGE_OBSERVATION_UNAVAILABLE")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
