"""Explicit local entry for preparing or operating a bounded HS300 task.

This command cannot issue an execution grant. An operator-owned server config
must separately bind the exact task, approval original and finite budget.
Adjusted-unit request/v6 requires its explicit config/catalog/grant v4 bindings.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from quantos.application.personal_projection import PersonalResearchProjection
from quantos.application.personal_server_config import load_server_config, make_trusted_service
from quantos.contracts.base import canonical_json_bytes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=(
            "describe",
            "describe-summary",
            "prepare",
            "status",
            "results",
            "results-summary",
            "boundary-page",
            "boundary-read",
            "cancel",
            "execute",
        ),
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--task")
    parser.add_argument("--candidate")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--boundary-sha256")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--max-chars", type=int, default=8000)
    args = parser.parse_args()
    config = load_server_config(args.config.absolute())
    service = make_trusted_service(
        config.product_root, config.repo_root, config_path=args.config.absolute()
    )
    projection = PersonalResearchProjection(service)
    if args.action == "describe-summary":
        result = projection.capabilities(args.offset, args.limit)
    elif args.action == "describe":
        result = service.capabilities()
    elif args.action == "prepare":
        if args.request is None:
            parser.error("prepare requires an explicit request file")
        result = service.prepare(json.loads(args.request.read_bytes()))
    else:
        if args.task is None:
            parser.error("an explicit task hash is required")
        if args.action == "results-summary":
            result = projection.results(args.task)
        elif args.action in {"boundary-page", "boundary-read"}:
            if args.candidate is None:
                parser.error("boundary reads require --candidate")
            if args.action == "boundary-page":
                result = projection.boundary_page(
                    args.task, args.candidate, args.offset, args.limit
                )
            else:
                if args.boundary_sha256 is None:
                    parser.error("boundary-read requires --boundary-sha256")
                result = projection.boundary_read(
                    args.task, args.candidate, args.boundary_sha256, args.start, args.max_chars
                )
        else:
            result = getattr(service, args.action)(args.task)
    print(canonical_json_bytes(result).decode())


if __name__ == "__main__":
    main()
