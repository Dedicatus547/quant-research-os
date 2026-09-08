"""Dedicated network-free process entry point for Evidence Store publication."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from quantos.config import load_yaml_contract
from quantos.contracts import (
    EvidenceAvailabilityPolicy,
    EvidenceParserConfig,
    EvidencePublicationSpec,
)
from quantos.evidence.publisher import (
    EvidencePublicationError,
    EvidencePublisher,
    verify_evidence_store,
)

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)


@app.command("publish")
def publish(
    staging_path: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
    availability_policy_path: Annotated[
        Path, typer.Argument(exists=True, dir_okay=False, readable=True)
    ],
    parser_config_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    code_commit_hash: Annotated[str, typer.Option("--code-commit-hash")],
    runtime_fingerprint_hash: Annotated[str, typer.Option("--runtime-fingerprint-hash")],
    output_root: Annotated[
        Path,
        typer.Option(
            "--output-root",
            file_okay=False,
            help="Parent for immutable content-addressed Evidence Stores.",
        ),
    ] = Path("artifacts/evidence/stores"),
) -> None:
    """Verify staging and publish raw plus deterministic text without network access."""

    try:
        availability = load_yaml_contract(availability_policy_path, EvidenceAvailabilityPolicy)
        parser = load_yaml_contract(parser_config_path, EvidenceParserConfig)
        spec = EvidencePublicationSpec(
            availability_policy=availability,
            parser_config=parser,
            code_commit_hash=code_commit_hash,
            runtime_fingerprint_hash=runtime_fingerprint_hash,
        )
        result = EvidencePublisher().publish(staging_path, output_root, spec)
    except (OSError, ValueError, EvidencePublicationError) as error:
        reason_code = getattr(error, "reason_code", "SCHEMA_INVALID")
        typer.echo(
            json.dumps(
                {
                    "schema_version": "evidence-publication-result/v1",
                    "status": "FAILED",
                    "reason_code": str(reason_code),
                    "detail": "offline evidence publication failed",
                },
                sort_keys=True,
            )
        )
        raise typer.Exit(code=5) from None
    typer.echo(
        json.dumps(
            {
                "schema_version": "evidence-publication-result/v1",
                "status": "SUCCEEDED",
                "store": result.reference.model_dump(mode="json"),
                "item_count": len(result.manifest.items),
            },
            sort_keys=True,
        )
    )


@app.command("verify")
def verify(
    store_path: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
) -> None:
    """Verify an immutable Evidence Store and its exact file set."""

    try:
        manifest = verify_evidence_store(store_path)
    except EvidencePublicationError as error:
        typer.echo(
            json.dumps(
                {
                    "schema_version": "evidence-verification-result/v1",
                    "status": "FAILED",
                    "reason_code": error.reason_code,
                },
                sort_keys=True,
            )
        )
        raise typer.Exit(code=5) from None
    typer.echo(
        json.dumps(
            {
                "schema_version": "evidence-verification-result/v1",
                "status": "SUCCEEDED",
                "store_hash": manifest.store_hash,
                "item_count": len(manifest.items),
            },
            sort_keys=True,
        )
    )
