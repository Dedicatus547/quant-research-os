#!/usr/bin/env python3
"""Normalize a frozen Python source under the existing storage supervisor."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from quantos.artifacts.store import atomic_write_bytes, sha256_file
from quantos.contracts.base import canonical_json_bytes
from quantos.infrastructure import hosted_python_prefix, hosted_storage_copy
from quantos.infrastructure.hosted_deployment import install_inventory
from quantos.infrastructure.hosted_python_prefix import normalize_python_prefix
from quantos.infrastructure.hosted_storage import storage_checkpoint


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    storage_checkpoint(args.output, "deployment")
    args.output.mkdir(mode=0o700)
    try:
        report = normalize_python_prefix(
            args.source,
            args.output / "python",
            before_physical_copy=lambda size: storage_checkpoint(args.output, "deployment", size),
        )
        inventory = install_inventory(args.output / "python")
        atomic_write_bytes(args.output / "inventory.json", inventory.canonical_bytes())
        result = {
            "schema_version": "hosted-python-preparation/v1",
            "source": str(args.source.absolute()),
            "normalized_prefix": str((args.output / "python").absolute()),
            "copy": asdict(report),
            "installation_inventory_hash": inventory.content_hash,
            "implementation_hashes": {
                "script": sha256_file(Path(__file__)),
                "normalizer": sha256_file(Path(hosted_python_prefix.__file__)),
                "copy": sha256_file(Path(hosted_storage_copy.__file__)),
            },
            "validation": "NOT_EVALUATED",
            "qualification": "NOT_QUALIFIED",
        }
        atomic_write_bytes(args.output / "result.json", canonical_json_bytes(result))
    except Exception as error:
        atomic_write_bytes(
            args.output / "failure.json",
            canonical_json_bytes(
                {
                    "schema_version": "hosted-python-preparation-failure/v1",
                    "error_type": type(error).__name__,
                    "execution": "FAILED",
                    "validation": "NOT_EVALUATED",
                    "qualification": "NOT_QUALIFIED",
                }
            ),
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
