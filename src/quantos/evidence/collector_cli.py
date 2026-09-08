"""Dedicated network-enabled process entry point for evidence acquisition."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated

import typer

from quantos.config import load_yaml_contract
from quantos.contracts import EvidenceCollectionSpec, EvidenceCollectorPolicy
from quantos.evidence.collector import EvidenceCollectionError, EvidenceCollector

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)


@app.command("collect")
def collect(
    collection_spec_path: Annotated[
        Path, typer.Argument(exists=True, dir_okay=False, readable=True)
    ],
    collector_policy_path: Annotated[
        Path, typer.Argument(exists=True, dir_okay=False, readable=True)
    ],
    staging_root: Annotated[
        Path,
        typer.Option(
            "--staging-root",
            file_okay=False,
            help="Non-authority root for bounded collector output.",
        ),
    ] = Path("artifacts/acquisition/evidence"),
) -> None:
    """Collect an explicit bounded SSE/SZSE range into non-authority staging."""

    # The evidence collector never needs the market-data credential. Remove it
    # before constructing any acquisition service and never include its value in output.
    os.environ.pop("TUSHARE_TOKEN", None)
    try:
        spec = load_yaml_contract(collection_spec_path, EvidenceCollectionSpec)
        policy = load_yaml_contract(collector_policy_path, EvidenceCollectorPolicy)
        manifest, path = EvidenceCollector(policy).collect(spec, staging_root)
    except (OSError, ValueError, EvidenceCollectionError) as error:
        reason_code = getattr(error, "reason_code", "SCHEMA_INVALID")
        typer.echo(
            json.dumps(
                {
                    "schema_version": "evidence-collection-result/v1",
                    "status": "FAILED",
                    "reason_code": str(reason_code),
                    "detail": "bounded evidence collection failed",
                },
                sort_keys=True,
            )
        )
        raise typer.Exit(code=5) from None
    typer.echo(
        json.dumps(
            {
                "schema_version": "evidence-collection-result/v1",
                "status": "SUCCEEDED",
                "staging_hash": manifest.staging_hash,
                "staging_path": path.as_posix(),
                "announcement_count": len(manifest.announcements),
            },
            sort_keys=True,
        )
    )
