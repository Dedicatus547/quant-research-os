"""Explicit local entry for preparing or operating a bounded HS300 task.

This command cannot issue an execution grant. An operator-owned server config
must separately bind the exact task, approval original and finite budget.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from quantos.application.personal_server_config import load_server_config, make_trusted_service
from quantos.contracts.base import canonical_json_bytes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("describe", "prepare", "status", "results", "cancel", "execute")
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--task")
    args = parser.parse_args()
    config = load_server_config(args.config.absolute())
    service = make_trusted_service(
        config.product_root, config.repo_root, config_path=args.config.absolute()
    )
    if args.action == "describe":
        result = service.capabilities()
    elif args.action == "prepare":
        if args.request is None:
            parser.error("prepare requires an explicit request file")
        result = service.prepare(json.loads(args.request.read_bytes()))
    else:
        if args.task is None:
            parser.error("an explicit task hash is required")
        result = getattr(service, args.action)(args.task)
    print(canonical_json_bytes(result).decode())


if __name__ == "__main__":
    main()
