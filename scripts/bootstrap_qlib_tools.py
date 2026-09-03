#!/usr/bin/env python3
"""Cache the exact official Qlib source that supplies tools omitted from its wheel."""

from __future__ import annotations

import argparse
from pathlib import Path

from quantos.integrations.qlib import (
    QLIB_REPOSITORY,
    QLIB_TAG,
    run_checked,
    verify_official_qlib_tools,
)


def bootstrap(target: Path) -> None:
    if target.exists():
        if not (target / ".git").is_dir():
            raise RuntimeError(f"refusing to replace non-Git path: {target}")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        run_checked(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                QLIB_TAG,
                QLIB_REPOSITORY,
                str(target),
            ]
        )
    tools = verify_official_qlib_tools(target)
    print(f"Qlib tools ready: {target} @ {tools.commit}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--target",
        type=Path,
        default=Path(".tools/qlib-0.9.7"),
    )
    args = parser.parse_args()
    bootstrap(args.target)


if __name__ == "__main__":
    main()
