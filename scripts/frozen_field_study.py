#!/usr/bin/env python3
"""Pinned fixed V/P preparation, read-only status, explicit run and original-source comparison."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from quantos.application.field_study import (
    compare,
    compare_retained,
    load_configuration,
    load_preparation,
    load_recovery_origin,
    prepare,
    read_pinned,
    run,
    status,
    supersede,
)
from quantos.contracts.discovery_prediction import PredictionImportSource


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("prepare")
    command.add_argument("--config", type=Path, required=True)
    command.add_argument("--config-sha256", required=True)
    command.add_argument("--output-root", type=Path, required=True)
    command.add_argument("--execution-root", type=Path, required=True)
    command.add_argument("--origin", type=Path)
    command.add_argument("--origin-sha256")
    for name in ("status", "supersede", "run", "compare"):
        command = sub.add_parser(name)
        command.add_argument("--preparation", type=Path, required=True)
        command.add_argument("--preparation-sha256", required=True)
        if name == "run":
            command.add_argument("--candidate", choices=("V", "P"), required=True)
            command.add_argument("--request-sha256", required=True)
            command.add_argument("--max-compute-units", type=int, required=True)
            command.add_argument("--expected-new-bytes", type=int, required=True)
            command.add_argument("--resume", action="store_true")
        if name == "compare":
            command.add_argument("--sources", type=Path, required=True)
            command.add_argument("--sources-sha256", required=True)
            command.add_argument("--output-root", type=Path, required=True)
    command = sub.add_parser("compare-retained")
    command.add_argument("--binding", type=Path, required=True)
    command.add_argument("--binding-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "compare-retained":
            output = compare_retained(args.binding, args.binding_sha256)
        elif args.command == "prepare":
            config = load_configuration(args.config, args.config_sha256)
            if (args.origin is None) != (args.origin_sha256 is None):
                raise ValueError("origin path and hash must be supplied together")
            origin = load_recovery_origin(args.origin, args.origin_sha256) if args.origin else None
            result = prepare(config, args.output_root, args.execution_root, origin=origin)
            output = {
                "configuration_hash": config.content_hash,
                "preparation_hash": result.content_hash,
                "tasks": [
                    {
                        "candidate": t.label,
                        "request_hash": t.request.content_hash,
                        "compute_units": t.compute_units,
                    }
                    for t in result.tasks
                ],
            }
        else:
            prepared = load_preparation(args.preparation, args.preparation_sha256)
            if args.command == "status":
                output = status(prepared)
            elif args.command == "supersede":
                supersede(prepared)
                output = {"preparation_hash": prepared.content_hash, "supersession": "ACTIVATED"}
            elif args.command == "run":
                result = run(
                    prepared,
                    args.candidate,
                    request_hash=args.request_sha256,
                    max_compute_units=args.max_compute_units,
                    expected_new_bytes=args.expected_new_bytes,
                    resume=args.resume,
                )
                output = {
                    "request_hash": result.request_hash,
                    "outcome_hash": result.content_hash,
                    "outcome": str(result.outcome),
                }
            else:
                raw = read_pinned(args.sources, args.sources_sha256)
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    raise ValueError("sources must map V/P to explicit source descriptors")
                sources = {
                    key: PredictionImportSource.model_validate(value)
                    for key, value in cast(dict[str, object], payload).items()
                }
                output = compare(prepared, sources, args.output_root)
        print(json.dumps(output, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(
            json.dumps({"status": "FAILED", "error_class": type(error).__name__}), file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
