"""Network-free verification for bounded collector staging."""

from __future__ import annotations

import json
from pathlib import Path

from quantos.artifacts.store import (
    ArtifactIntegrityError,
    confined_regular_file,
    regular_tree_files,
    verify_file,
)
from quantos.contracts.evidence_acquisition import (
    EvidenceCollectionSpec,
    EvidenceCollectorPolicy,
    EvidenceHttpRequest,
    EvidenceHttpResponseMetadata,
    EvidenceStagingManifest,
)
from quantos.contracts.status import ReasonCode


class EvidenceStagingError(RuntimeError):
    def __init__(self, reason_code: ReasonCode, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def verify_evidence_staging(path: Path) -> EvidenceStagingManifest:
    """Verify a frozen staging manifest and its exact regular-file set."""

    try:
        manifest_path = confined_regular_file(path, "manifest.json")
        manifest = EvidenceStagingManifest.model_validate_json(manifest_path.read_bytes())
        if path.name != f"sha256-{manifest.staging_hash}":
            raise ValueError("staging directory name does not bind manifest hash")
        actual = {
            item.relative_to(path).as_posix()
            for item in regular_tree_files(path)
            if item.name != "manifest.json"
        }
        manifested = {item.logical_path for item in manifest.files}
        conceptual = {"collection-spec.json", "collector-policy.json"}
        for request in manifest.discovery_requests:
            prefix = f"exchanges/{request.sequence:06d}"
            conceptual.update(
                {
                    f"{prefix}.request.json",
                    f"{prefix}.response.bin",
                    f"{prefix}.response-metadata.json",
                }
            )
            if request.body_hash is not None:
                conceptual.add(f"{prefix}.request-body.json")
        for item in manifest.announcements:
            item_id = f"{item.candidate.venue.value.lower()}-{item.candidate.content_hash[:24]}"
            conceptual.update(
                {
                    item.raw_file.logical_path,
                    f"documents/{item_id}.request.json",
                    f"documents/{item_id}.response-metadata.json",
                }
            )
        if actual != manifested or manifested != conceptual:
            raise ValueError("staging exact-file set does not match manifest")
        for item in manifest.files:
            target = confined_regular_file(path, item.logical_path)
            verify_file(target, item.sha256)
            if target.stat().st_size != item.size_bytes:
                raise ValueError("staging file size does not match manifest")
        collection = EvidenceCollectionSpec.model_validate_json(
            confined_regular_file(path, "collection-spec.json").read_bytes()
        )
        policy = EvidenceCollectorPolicy.model_validate_json(
            confined_regular_file(path, "collector-policy.json").read_bytes()
        )
        if (
            collection.content_hash != manifest.collection_spec_hash
            or policy.content_hash != manifest.collector_policy_hash
            or policy.collector_version != manifest.collector_version
        ):
            raise ValueError("staging policy or collection binding is invalid")
        request_hashes = {item.content_hash for item in manifest.discovery_requests}
        response_hashes = {item.content_hash for item in manifest.discovery_responses}
        files_by_path = {item.logical_path: item for item in manifest.files}
        for request, response in zip(
            manifest.discovery_requests, manifest.discovery_responses, strict=True
        ):
            prefix = f"exchanges/{request.sequence:06d}"
            stored_request = EvidenceHttpRequest.model_validate_json(
                confined_regular_file(path, f"{prefix}.request.json").read_bytes()
            )
            stored_response = EvidenceHttpResponseMetadata.model_validate_json(
                confined_regular_file(path, f"{prefix}.response-metadata.json").read_bytes()
            )
            if stored_request != request or stored_response != response:
                raise ValueError("stored discovery metadata does not match manifest")
            verify_file(confined_regular_file(path, f"{prefix}.response.bin"), response.body_hash)
            if request.body_hash is not None:
                verify_file(
                    confined_regular_file(path, f"{prefix}.request-body.json"),
                    request.body_hash,
                )
        for item in manifest.announcements:
            if item.discovery_request_hash not in request_hashes:
                raise ValueError("announcement references an unknown discovery request")
            if item.discovery_response_metadata_hash not in response_hashes:
                raise ValueError("announcement references an unknown discovery response")
            raw_path = confined_regular_file(path, item.raw_file.logical_path)
            verify_file(raw_path, item.document_response.body_hash)
            if files_by_path[item.raw_file.logical_path] != item.raw_file:
                raise ValueError("announcement raw file metadata does not match file manifest")
            item_id = f"{item.candidate.venue.value.lower()}-{item.candidate.content_hash[:24]}"
            stored_request = EvidenceHttpRequest.model_validate_json(
                confined_regular_file(path, f"documents/{item_id}.request.json").read_bytes()
            )
            stored_response = EvidenceHttpResponseMetadata.model_validate_json(
                confined_regular_file(
                    path, f"documents/{item_id}.response-metadata.json"
                ).read_bytes()
            )
            if stored_request != item.document_request or stored_response != item.document_response:
                raise ValueError("stored document metadata does not match manifest")
    except (OSError, ValueError, ArtifactIntegrityError, json.JSONDecodeError):
        raise EvidenceStagingError(
            ReasonCode.ARTIFACT_CORRUPTED,
            "evidence staging failed exact-file or hash verification",
        ) from None
    return manifest
