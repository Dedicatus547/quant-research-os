#!/usr/bin/env python3
"""Execute the frozen P10 GPT + Codex harness capability spike."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from quantos.application.harness_runner import (
    execute_codex_spike,
    safe_result_summary,
    verify_codex_spike_artifact,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixture-root",
        type=Path,
        default=Path("tests/fixtures/p10_codex_workspace_v3"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/feasibility/codex-p10"),
    )
    parser.add_argument(
        "--verify-run",
        type=Path,
        help="Offline-verify one retained Code Mode-aware P10 run instead of executing live.",
    )
    args = parser.parse_args()
    result = (
        verify_codex_spike_artifact(args.verify_run, args.fixture_root)
        if args.verify_run is not None
        else execute_codex_spike(args.fixture_root, args.output_root)
    )
    print(json.dumps(safe_result_summary(result), indent=2, sort_keys=True))
    if result.report.decision != "GO":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
