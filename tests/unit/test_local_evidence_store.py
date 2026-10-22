"""Small import/citation checks; no provider calls or real gold inspection."""

import json
from datetime import UTC, datetime

import pytest

from quantos.contracts.base import sha256_bytes
from quantos.contracts.local_evidence import LocalImportPolicy, LocalReadReceipt
from quantos.evidence.citation_groups import group_match
from quantos.evidence.local_store import (
    LocalImportSource,
    local_binding,
    local_citation,
    publish_local_evidence_store,
    verify_local_evidence_store,
)


def test_local_roundtrip_physical_page_and_unknown_rights(tmp_path):
    raw = b"%PDF-test"
    text = "first\n\nsecond"
    encoded = text.encode()
    (tmp_path / "raw.pdf").write_bytes(raw)
    (tmp_path / "text.txt").write_bytes(encoded)
    pages = {
        "text_sha256": sha256_bytes(encoded),
        "physical_page_map_available": True,
        "pages": [
            {"pdf_page": 1, "char_start": 0, "char_end": 5},
            {"pdf_page": 2, "char_start": 7, "char_end": 13},
        ],
    }
    (tmp_path / "pages.json").write_text(json.dumps(pages))
    policy = LocalImportPolicy(
        policy_id="test",
        code_commit_hash="a" * 40,
        importer_source_hash="b" * 64,
        adoption_record_hashes=(),
    )
    common = dict(
        raw_path="raw.pdf",
        raw_sha256=sha256_bytes(raw),
        text_path="text.txt",
        text_sha256=sha256_bytes(encoded),
        page_map_path="pages.json",
        source_declaration={"source_locator": "https://example.invalid/doc", "publisher": "test"},
        parser_origin={"parser_name": "retained-test", "parser_version": "1"},
        company_group="000001",
    )
    path = publish_local_evidence_store(
        tmp_path,
        tmp_path / "stores",
        [
            LocalImportSource(sample_id="a", **common),
            LocalImportSource(sample_id="b", predecessor_sample_id="a", **common),
        ],
        policy,
    )
    manifest = verify_local_evidence_store(path)
    a, b = manifest.items
    assert a.evidence.use_permission.value == "UNKNOWN"
    assert a.evidence.available_at is None
    assert b.evidence.predecessor_evidence_hash == a.evidence.content_hash
    cite = local_citation(local_binding(path, a), pages, 7, 13)
    assert cite.page == 2 and cite.char_start == 7 and cite.char_end == 13
    (path / "unexpected.json").write_text("{}")
    with pytest.raises(ValueError, match="exact-file"):
        verify_local_evidence_store(path)
    (path / "unexpected.json").unlink()
    (path / a.raw_ref.logical_path).write_bytes(b"changed")
    with pytest.raises(ValueError, match="identity"):
        verify_local_evidence_store(path)


def test_receipt_rejects_invented_identity_or_reversed_times():
    stamp = datetime.now(UTC)
    values = dict(
        sample_id="a",
        source_path="a.pdf",
        expected_raw_hash="a" * 64,
        observed_raw_hash="b" * 64,
        observed_size=1,
        read_started_at=stamp,
        read_completed_at=stamp,
        source_declaration_hash="c" * 64,
        parser_origin_hash="d" * 64,
    )
    with pytest.raises(ValueError, match="identity/time"):
        LocalReadReceipt(**values)


def test_group_requires_all_parts_and_rejects_duplicate_or_extra():
    a, b, c = {"span": 1}, {"span": 2}, {"span": 3}
    assert group_match([b, a], [[a, b]])
    assert not group_match([a], [[a, b]])
    assert not group_match([a, a, b], [[a, b]])
    assert not group_match([a, b, c], [[a, b]])
