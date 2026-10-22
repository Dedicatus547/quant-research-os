"""Offline synthetic material only: exact citations, permissions and persistent proposals."""

import json
from pathlib import Path

import pytest

from quantos.application.personal_evidence import PersonalEvidenceService
from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.base import sha256_bytes
from quantos.contracts.evidence import EvidenceUsePermission
from quantos.contracts.local_evidence import LocalImportPolicy
from quantos.evidence.local_store import LocalImportSource, publish_local_evidence_store


def _service(tmp_path, permission=EvidenceUsePermission.UNKNOWN):
    repo = tmp_path / "repo"
    repo.mkdir()
    root = tmp_path / "product"
    root.mkdir()
    text = "first\n\nsecond"
    raw = b"%PDF-synthetic-not-a-real-announcement"
    (repo / "raw.pdf").write_bytes(raw)
    (repo / "text.txt").write_text(text)
    (repo / "pages.json").write_text(
        json.dumps(
            {
                "text_sha256": sha256_bytes(text.encode()),
                "physical_page_map_available": True,
                "pages": [
                    {"pdf_page": 1, "char_start": 0, "char_end": 5},
                    {"pdf_page": 2, "char_start": 7, "char_end": 13},
                ],
            }
        )
    )
    path = publish_local_evidence_store(
        repo,
        repo / "stores",
        [
            LocalImportSource(
                sample_id="synthetic",
                raw_path="raw.pdf",
                raw_sha256=sha256_bytes(raw),
                text_path="text.txt",
                text_sha256=sha256_bytes(text.encode()),
                page_map_path="pages.json",
                source_declaration={
                    "source_locator": "https://example.invalid/synthetic",
                    "publisher": "test",
                },
                parser_origin={"parser_name": "synthetic", "parser_version": "1"},
                company_group="000001",
                use_permission=permission,
            )
        ],
        LocalImportPolicy(
            policy_id="synthetic",
            code_commit_hash="a" * 40,
            importer_source_hash="b" * 64,
            adoption_record_hashes=(),
        ),
    )
    (root / "evidence-catalog.json").write_text(
        json.dumps(
            {
                "schema_version": "personal-evidence-catalog/v1",
                "stores": [
                    {
                        "store_hash": path.name.removeprefix("sha256-"),
                        "path": path.relative_to(repo).as_posix(),
                    }
                ],
            }
        )
    )
    service = PersonalEvidenceService(root, repo)
    return service, service.list_evidence()["items"][0]["evidence_hash"], path


def test_auxiliary_read_cite_persist_review_and_time(tmp_path):
    service, digest, _ = _service(tmp_path)
    view = service.read(digest, 7, 6)
    assert view["text"] == "second" and view["research_admission"] == "NOT_GRANTED"
    assert service.cite(digest, 7, 13, "second")["page"] == 2
    with pytest.raises(ValueError, match="match frozen"):
        service.cite(digest, 7, 13, "fake!!")
    with pytest.raises(ValueError, match="availability"):
        service.read(digest, as_of="2026-01-01T00:00:00+00:00")
    with pytest.raises(ValueError, match="timezone"):
        service.read(digest, as_of="2026-01-01")
    args = (
        digest,
        "A host-session interpretation, not validated evidence.",
        [{"start": 7, "end": 13, "expected_text": "second"}],
    )
    proposal = service.propose(*args)
    assert service.propose(*args)["proposal_id"] == proposal["proposal_id"]
    restarted = PersonalEvidenceService(service.root, service.repo_root)
    review = restarted.review(proposal["proposal_id"])
    assert review["citation_integrity"] == "VERIFIED"
    assert review["semantic_validation"] == "NOT_EVALUATED"
    assert review["research_admission"] == "NOT_GRANTED"


def test_restricted_source_and_corrupt_store_are_rejected(tmp_path):
    service, digest, store = _service(tmp_path, EvidenceUsePermission.RESTRICTED)
    with pytest.raises(PermissionError, match="RESTRICTED"):
        service.read(digest)
    (store / "items/synthetic/text.txt").write_text("changed")
    with pytest.raises(ValueError, match="identity"):
        service.list_evidence()


def test_catalog_and_tool_boundaries(tmp_path):
    service, digest, store = _service(tmp_path)
    with pytest.raises(ValueError, match="absolute"):
        PersonalEvidenceService(Path("relative"), service.repo_root)
    with pytest.raises(ValueError, match="bounded"):
        service.read(digest, max_chars=100000)
    with pytest.raises(ValueError, match="SHA256"):
        service.read("../../secret")
    catalog = service.root / "evidence-catalog.json"
    data = json.loads(catalog.read_text())
    data["stores"][0]["path"] = "../outside"
    catalog.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="scope"):
        service.list_evidence()
    data["stores"][0]["path"] = "linked"
    (service.repo_root / "linked").symlink_to(store, target_is_directory=True)
    catalog.write_text(json.dumps(data))
    with pytest.raises(ArtifactIntegrityError, match="symbolic"):
        service.list_evidence()


def test_empty_catalog_does_not_search_material(tmp_path):
    assert PersonalEvidenceService(tmp_path, tmp_path).list_evidence()["items"] == []


@pytest.mark.parametrize("preexisting_catalog", [False, True])
def test_retained_import_is_bounded_idempotent_and_unadmitted(
    tmp_path, monkeypatch, preexisting_catalog
):
    import subprocess
    from types import SimpleNamespace

    service, _, _ = _service(tmp_path)
    original_catalog = (service.root / "evidence-catalog.json").read_bytes()
    # Keep product persistence within this synthetic repository for import.
    service.root = service.repo_root / "product"
    service.root.mkdir()
    if preexisting_catalog:
        (service.root / "evidence-catalog.json").write_bytes(original_catalog)
    origin = service.repo_root / "src/quantos/evidence/local_store.py"
    origin.parent.mkdir(parents=True)
    origin.write_text("synthetic importer identity for unit test")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="a" * 40))
    source = {
        "sample_id": "imported",
        "raw_path": "raw.pdf",
        "raw_sha256": sha256_bytes((service.repo_root / "raw.pdf").read_bytes()),
        "text_path": "text.txt",
        "text_sha256": sha256_bytes((service.repo_root / "text.txt").read_bytes()),
        "page_map_path": "pages.json",
        "source_declaration": {"source_locator": "local:test", "publisher": "test"},
        "parser_origin": {"parser_name": "retained-test", "parser_version": "1"},
        "company_group": "000001",
    }
    intake = service.repo_root / "intake.json"
    intake.write_text(
        json.dumps({"schema_version": "personal-evidence-intake/v1", "sources": [source]})
    )
    first = service.import_local("intake.json")
    assert first == service.import_local("intake.json")
    assert first["research_admission"] == "NOT_GRANTED"
    assert service.list_evidence()["total"] == 1 + preexisting_catalog
    revisions = service.root / "evidence-catalog-revisions"
    if preexisting_catalog:
        assert (
            revisions / (sha256_bytes(original_catalog) + ".json")
        ).read_bytes() == original_catalog
    source["sample_id"] = "second-import"
    intake.write_text(
        json.dumps({"schema_version": "personal-evidence-intake/v1", "sources": [source]})
    )
    service.import_local("intake.json")
    assert service.list_evidence()["total"] == 2 + preexisting_catalog
    source["use_permission"] = "RESEARCH_ALLOWED"
    intake.write_text(
        json.dumps({"schema_version": "personal-evidence-intake/v1", "sources": [source]})
    )
    with pytest.raises(PermissionError, match="server-bound"):
        service.import_local("intake.json")
    source.pop("use_permission")
    source["raw_path"] = "sealed/raw.pdf"
    intake.write_text(
        json.dumps({"schema_version": "personal-evidence-intake/v1", "sources": [source]})
    )
    with pytest.raises(ValueError, match="sealed"):
        service.import_local("intake.json")
