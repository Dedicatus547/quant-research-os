"""Offline-only CLI input and producer checks using the bounded synthetic SDK fixture."""

from __future__ import annotations

import argparse
from pathlib import Path
from uuid import uuid4

import pytest
import test_sdk_campaign_producer
from scripts.sdk_campaign import _inputs, _read_pinned

from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.base import sha256_bytes


def test_cli_pinned_inputs_prepare_and_status(tmp_path: Path) -> None:
    service, spec, request, producer, _ = test_sdk_campaign_producer.setup.__wrapped__(tmp_path)
    del service
    request_path = producer.root / "cli-inputs" / "request.json"
    spec_path = producer.root / "cli-inputs" / "spec.json"
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_bytes, spec_bytes = request.canonical_bytes(), spec.canonical_bytes()
    request_path.write_bytes(request_bytes)
    spec_path.write_bytes(spec_bytes)

    parsed_request, parsed_spec = _inputs(
        argparse.Namespace(
            request=str(request_path),
            request_sha256=sha256_bytes(request_bytes),
            spec=str(spec_path),
            spec_sha256=sha256_bytes(spec_bytes),
        )
    )
    assert parsed_request == request
    assert parsed_spec == spec
    reservation = producer.prepare(parsed_request, parsed_spec)
    assert reservation.request_hash == request.content_hash
    assert producer.status(parsed_request, parsed_spec) == "PREPARED"


def test_cli_rejects_hash_mismatch_noncanonical_and_symlink_parent(tmp_path: Path) -> None:
    _, _spec, request, producer, _ = test_sdk_campaign_producer.setup.__wrapped__(tmp_path)
    path = producer.root / "cli-inputs" / "request.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    canonical = request.canonical_bytes()
    path.write_bytes(canonical)
    digest = sha256_bytes(canonical)

    with pytest.raises(ValueError):
        _read_pinned(str(path), "0" * 64, 1_048_576, "request")

    noncanonical = path.parent / "noncanonical.json"
    noncanonical.write_bytes(canonical + b"\n")
    with pytest.raises(ValueError):
        _read_pinned(
            str(noncanonical), sha256_bytes(noncanonical.read_bytes()), 1_048_576, "request"
        )

    alias = tmp_path / f"sdk-cli-parent-{uuid4().hex}"
    alias.symlink_to(path.parent, target_is_directory=True)
    with pytest.raises(ArtifactIntegrityError):
        _read_pinned(str(alias / path.name), digest, 1_048_576, "request")
