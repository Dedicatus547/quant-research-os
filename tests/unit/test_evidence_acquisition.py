import json
from datetime import UTC, date, datetime
from email.message import Message
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest
from pypdf import PdfWriter
from typer.testing import CliRunner

from quantos.contracts import (
    EvidenceAvailabilityPolicy,
    EvidenceCollectionSpec,
    EvidenceCollectorPolicy,
    EvidenceHttpRequest,
    EvidenceParserConfig,
    EvidencePublicationSpec,
    EvidenceUsePermission,
    ExchangeVenue,
    ExtractionStatus,
)
from quantos.evidence import collector_cli, publisher_cli
from quantos.evidence.collector import (
    EvidenceCollectionError,
    EvidenceCollector,
    HttpResponse,
    PreparedHttpRequest,
    UrllibHttpClient,
)
from quantos.evidence.publisher import (
    EvidencePublicationError,
    EvidencePublisher,
    _extract_text,
    verify_evidence_store,
)
from quantos.evidence.sources import SseAnnouncementSource, SzseAnnouncementSource
from quantos.evidence.staging import verify_evidence_staging

NOW = datetime(2026, 9, 8, 12, tzinfo=UTC)


class _NoopLimiter:
    def try_acquire(self, name: str, weight: int = 1) -> bool:
        del name, weight
        return True


def _sse_payload(*, total: int = 1) -> bytes:
    groups = (
        [
            [
                {
                    "ORG_BULLETIN_ID": "8253816074790055",
                    "ORG_FILE_TYPE": 0,
                    "SECURITY_CODE": "600012",
                    "SSEDATE": "2025-01-02",
                    "TITLE": "皖通高速股份回购进展公告",
                    "URL": "/disclosure/listedinfo/announcement/c/new/2025-01-02/a.pdf",
                }
            ]
        ]
        if total
        else []
    )
    return json.dumps(
        {
            "pageHelp": {
                "pageCount": total,
                "pageNo": 1,
                "pageSize": 1,
                "total": total,
            },
            "result": groups,
        },
        ensure_ascii=False,
    ).encode()


def _szse_payload() -> bytes:
    return json.dumps(
        {
            "announceCount": 1,
            "data": [
                {
                    "id": "b5706a80-cc57-43d3-8328-2b82feffcaea",
                    "title": "本川智能股份回购进展公告",
                    "attachPath": "/disc/disk03/finalpage/2025-01-02/b.pdf",
                    "publishTime": "2025-01-02 23:59:59",
                    "secCode": ["300964"],
                }
            ],
        },
        ensure_ascii=False,
    ).encode()


class _FixtureHttpClient:
    def send(
        self,
        request: PreparedHttpRequest,
        *,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> HttpResponse:
        del timeout_seconds, max_response_bytes
        if request.contract.purpose == "DOCUMENT":
            body = "股份回购公告\n本文件是冻结的测试原文。\n".encode()
            media_type = "text/plain"
            encoding = "utf-8"
        elif request.contract.venue is ExchangeVenue.SSE:
            query = parse_qs(urlsplit(request.contract.url).query)
            assert query["pageHelp.pageNo"] == ["1"]
            body = _sse_payload()
            media_type = "application/json"
            encoding = "utf-8"
        else:
            assert request.body is not None
            payload = json.loads(request.body)
            assert payload["channelCode"] == ["listedNotice_disc"]
            body = _szse_payload()
            media_type = "application/json"
            encoding = "utf-8"
        return HttpResponse(
            status_code=200,
            body=body,
            media_type=media_type,
            encoding=encoding,
            fetched_at=NOW,
            observed_at=NOW,
        )


def _collection() -> EvidenceCollectionSpec:
    return EvidenceCollectionSpec(
        collection_id="p12-fixture",
        venues=(ExchangeVenue.SSE, ExchangeVenue.SZSE),
        start_date=date(2025, 1, 2),
        end_date=date(2025, 1, 2),
        page_size=1,
        max_announcements=10,
    )


def _collector_policy() -> EvidenceCollectorPolicy:
    return EvidenceCollectorPolicy(
        policy_id="exchange-announcements/v1",
        user_agent="quant-research-os-evidence-collector/0.1 (+offline-research)",
        requests_per_minute=30,
        retry_min_seconds=0,
        retry_max_seconds=0,
        allowed_hosts=(
            "big5.sse.com.cn",
            "disc.static.szse.cn",
            "query.sse.com.cn",
            "www.szse.cn",
        ),
        collector_version="quantos-evidence-collector/0.1",
    )


def _publication() -> EvidencePublicationSpec:
    return EvidencePublicationSpec(
        availability_policy=EvidenceAvailabilityPolicy(
            policy_id="exchange-announcement-availability/v1",
            venue_permissions={
                ExchangeVenue.SSE: EvidenceUsePermission.RESEARCH_ALLOWED,
                ExchangeVenue.SZSE: EvidenceUsePermission.UNKNOWN,
            },
            venue_license_ids={
                ExchangeVenue.SSE: "sse-legal-statement/noncommercial/2026-09-08",
                ExchangeVenue.SZSE: "szse-copyright-disclaimer/unknown/2026-09-08",
            },
            limitations=("SOURCE_CONTENT_NOT_INDEPENDENTLY_VERIFIED",),
        ),
        parser_config=EvidenceParserConfig(config_id="deterministic-text/v1"),
        code_commit_hash="a" * 40,
        runtime_fingerprint_hash="b" * 64,
    )


def test_official_source_parsers_bind_counts_and_publication_precision() -> None:
    spec = _collection()
    sse = SseAnnouncementSource().parse_page(_sse_payload(), spec, page=1)
    szse = SzseAnnouncementSource().parse_page(_szse_payload(), spec, page=1)

    assert sse.reported_total == sse.collected_units == 1
    assert sse.candidates[0].entity_refs == ("600012.SH",)
    assert sse.candidates[0].publication_precision == "DATE"
    assert sse.candidates[0].document_url == (
        "https://big5.sse.com.cn/site/cht/www.sse.com.cn/disclosure/listedinfo/"
        "announcement/c/new/2025-01-02/a.pdf"
    )
    assert szse.reported_total == szse.collected_units == 1
    assert szse.candidates[0].entity_refs == ("300964.SZ",)
    assert szse.candidates[0].publication_precision == "SECOND"


def test_locked_pdf_parser_retains_empty_text_limitation_deterministically() -> None:
    stream = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(stream)

    first = _extract_text(stream.getvalue(), "application/pdf", None)
    second = _extract_text(stream.getvalue(), "application/pdf", None)

    assert first == second
    assert first.page_count == 1
    assert first.text == ""
    assert first.limitations == ("NO_MACHINE_READABLE_TEXT",)


def test_html_parser_removes_active_content_and_normalizes_text() -> None:
    parsed = _extract_text(
        b"<html><style>hidden</style><p>A<br>B</p><script>secret</script></html>",
        "text/html",
        "utf-8",
    )

    assert parsed.text == "A\nB\n"
    assert "hidden" not in parsed.text
    assert "secret" not in parsed.text


def test_collector_and_offline_publisher_are_rebuildable_and_fail_on_tamper(
    tmp_path: Path,
) -> None:
    collector = EvidenceCollector(
        _collector_policy(),
        client=_FixtureHttpClient(),
        limiter=_NoopLimiter(),
        now=lambda: NOW,
    )
    staging_manifest, staging_path = collector.collect(_collection(), tmp_path / "staging")

    assert verify_evidence_staging(staging_path) == staging_manifest
    assert [item.reported_total for item in staging_manifest.completeness] == [1, 1]
    assert len(staging_manifest.announcements) == 2

    publisher = EvidencePublisher()
    first = publisher.publish(staging_path, tmp_path / "store-a", _publication())
    second = publisher.publish(staging_path, tmp_path / "store-b", _publication())
    repeated = publisher.publish(staging_path, tmp_path / "store-a", _publication())

    assert first.manifest.store_hash == second.manifest.store_hash
    assert repeated.manifest == first.manifest
    assert first.manifest.canonical_bytes() == second.manifest.canonical_bytes()
    assert [item.extraction_status for item in first.manifest.items] == [
        ExtractionStatus.SUCCEEDED,
        ExtractionStatus.SUCCEEDED,
    ]
    assert first.manifest.items[0].evidence.available_at is not None
    assert first.manifest.items[0].evidence.availability_kind == "CONSERVATIVE"
    assert first.manifest.items[1].evidence.use_permission == EvidenceUsePermission.UNKNOWN
    assert verify_evidence_store(first.path) == first.manifest

    text_path = first.path / first.manifest.items[0].text_ref.logical_path  # type: ignore[union-attr]
    text_path.write_bytes(b"tampered")
    with pytest.raises(EvidencePublicationError, match="failed exact-file"):
        verify_evidence_store(first.path)


def test_zero_result_requires_and_accepts_explicit_source_total(tmp_path: Path) -> None:
    class ZeroClient(_FixtureHttpClient):
        def send(
            self,
            request: PreparedHttpRequest,
            *,
            timeout_seconds: float,
            max_response_bytes: int,
        ) -> HttpResponse:
            response = super().send(
                request,
                timeout_seconds=timeout_seconds,
                max_response_bytes=max_response_bytes,
            )
            if request.contract.purpose == "DISCOVERY":
                return HttpResponse(
                    status_code=200,
                    body=_sse_payload(total=0),
                    media_type="application/json",
                    encoding="utf-8",
                    fetched_at=NOW,
                    observed_at=NOW,
                )
            return response

    spec = _collection().model_copy(update={"venues": (ExchangeVenue.SSE,)})
    manifest, _ = EvidenceCollector(
        _collector_policy(), client=ZeroClient(), limiter=_NoopLimiter(), now=lambda: NOW
    ).collect(spec, tmp_path / "zero")

    assert manifest.completeness[0].reported_total == 0
    assert manifest.completeness[0].page_item_counts == (0,)
    assert manifest.announcements == ()


def test_retryable_status_is_bounded_and_audited(tmp_path: Path) -> None:
    class RetryClient(_FixtureHttpClient):
        calls = 0

        def send(
            self,
            request: PreparedHttpRequest,
            *,
            timeout_seconds: float,
            max_response_bytes: int,
        ) -> HttpResponse:
            self.calls += 1
            if self.calls == 1:
                return HttpResponse(
                    status_code=500,
                    body=b"retry",
                    media_type="text/plain",
                    encoding="utf-8",
                    fetched_at=NOW,
                    observed_at=NOW,
                )
            return HttpResponse(
                status_code=200,
                body=_sse_payload(total=0),
                media_type="application/json",
                encoding="utf-8",
                fetched_at=NOW,
                observed_at=NOW,
            )

    client = RetryClient()
    spec = _collection().model_copy(update={"venues": (ExchangeVenue.SSE,)})
    manifest, _ = EvidenceCollector(
        _collector_policy(), client=client, limiter=_NoopLimiter(), now=lambda: NOW
    ).collect(spec, tmp_path / "retry")

    assert client.calls == 2
    assert manifest.discovery_responses[0].attempt_count == 2


def test_collector_fails_closed_on_schema_budget_status_and_body_mismatch(
    tmp_path: Path,
) -> None:
    class BadClient(_FixtureHttpClient):
        def __init__(self, response: HttpResponse) -> None:
            self.response = response

        def send(
            self,
            request: PreparedHttpRequest,
            *,
            timeout_seconds: float,
            max_response_bytes: int,
        ) -> HttpResponse:
            del request, timeout_seconds, max_response_bytes
            return self.response

    spec = _collection().model_copy(update={"venues": (ExchangeVenue.SSE,)})
    invalid_json = HttpResponse(
        status_code=200,
        body=b"not-json",
        media_type="application/json",
        encoding="utf-8",
        fetched_at=NOW,
        observed_at=NOW,
    )
    with pytest.raises(EvidenceCollectionError, match="parser schema"):
        EvidenceCollector(
            _collector_policy(),
            client=BadClient(invalid_json),
            limiter=_NoopLimiter(),
            now=lambda: NOW,
        ).collect(spec, tmp_path / "bad-schema")

    bad_status = invalid_json.__class__(
        status_code=404,
        body=b"missing",
        media_type="text/plain",
        encoding="utf-8",
        fetched_at=NOW,
        observed_at=NOW,
    )
    with pytest.raises(EvidenceCollectionError, match="HTTP 404"):
        EvidenceCollector(
            _collector_policy(),
            client=BadClient(bad_status),
            limiter=_NoopLimiter(),
            now=lambda: NOW,
        ).collect(spec, tmp_path / "bad-status")

    oversized = invalid_json.__class__(
        status_code=200,
        body=b"123",
        media_type="application/json",
        encoding="utf-8",
        fetched_at=NOW,
        observed_at=NOW,
    )
    tiny_policy = _collector_policy().model_copy(update={"max_response_bytes": 2})
    with pytest.raises(EvidenceCollectionError, match="byte limit"):
        EvidenceCollector(
            tiny_policy,
            client=BadClient(oversized),
            limiter=_NoopLimiter(),
            now=lambda: NOW,
        ).collect(spec, tmp_path / "too-large")

    budget_body = json.dumps(
        {
            "pageHelp": {"pageCount": 11, "pageNo": 1, "pageSize": 1, "total": 11},
            "result": json.loads(_sse_payload())["result"],
        }
    ).encode()
    over_budget = invalid_json.__class__(
        status_code=200,
        body=budget_body,
        media_type="application/json",
        encoding="utf-8",
        fetched_at=NOW,
        observed_at=NOW,
    )
    with pytest.raises(EvidenceCollectionError, match="collection budget"):
        EvidenceCollector(
            _collector_policy(),
            client=BadClient(over_budget),
            limiter=_NoopLimiter(),
            now=lambda: NOW,
        ).collect(spec, tmp_path / "over-budget")

    collector = EvidenceCollector(
        _collector_policy(), client=BadClient(invalid_json), limiter=_NoopLimiter()
    )
    body = b"{}"
    mismatched = PreparedHttpRequest(
        contract=EvidenceHttpRequest(
            sequence=1,
            venue=ExchangeVenue.SZSE,
            purpose="DISCOVERY",
            method="POST",
            url="https://www.szse.cn/api/disc/announcement/annList",
            body_hash="a" * 64,
            content_type="application/json",
        ),
        body=body,
        headers=(),
    )
    with pytest.raises(EvidenceCollectionError, match="body hash"):
        collector._fetch(mismatched)  # type: ignore[reportPrivateUsage]


def test_source_parsers_reject_malformed_or_inconsistent_pages() -> None:
    spec = _collection()
    with pytest.raises(ValueError, match="valid JSON"):
        SseAnnouncementSource().parse_page(b"invalid", spec, page=1)
    with pytest.raises(ValueError, match="page number"):
        payload = json.loads(_sse_payload())
        payload["pageHelp"]["pageNo"] = 2
        SseAnnouncementSource().parse_page(json.dumps(payload).encode(), spec, page=1)
    with pytest.raises(ValueError, match="one primary"):
        payload = json.loads(_sse_payload())
        payload["result"][0][0]["ORG_FILE_TYPE"] = 1
        SseAnnouncementSource().parse_page(json.dumps(payload).encode(), spec, page=1)
    with pytest.raises(ValueError, match="announceCount"):
        SzseAnnouncementSource().parse_page(b'{"data":[]}', spec, page=1)


def test_collector_rejects_non_allowlisted_document_host(tmp_path: Path) -> None:
    class EscapeClient(_FixtureHttpClient):
        pass

    bad = _sse_payload().replace(b"big5.sse.com.cn", b"evil.example")
    assert bad == _sse_payload()  # source URLs are root-relative and fixed by the adapter

    policy = _collector_policy().model_copy(
        update={"allowed_hosts": ("query.sse.com.cn", "www.szse.cn")}
    )
    spec = _collection().model_copy(update={"venues": (ExchangeVenue.SSE,)})
    with pytest.raises(EvidenceCollectionError, match="allowlisted"):
        EvidenceCollector(
            policy, client=EscapeClient(), limiter=_NoopLimiter(), now=lambda: NOW
        ).collect(spec, tmp_path / "escape")


def test_parser_failure_retains_raw_evidence_without_inventing_text(tmp_path: Path) -> None:
    class UnsupportedDocumentClient(_FixtureHttpClient):
        def send(
            self,
            request: PreparedHttpRequest,
            *,
            timeout_seconds: float,
            max_response_bytes: int,
        ) -> HttpResponse:
            if request.contract.purpose == "DOCUMENT":
                return HttpResponse(
                    status_code=200,
                    body=b"unsupported-source-bytes",
                    media_type="application/octet-stream",
                    encoding=None,
                    fetched_at=NOW,
                    observed_at=NOW,
                )
            return super().send(
                request,
                timeout_seconds=timeout_seconds,
                max_response_bytes=max_response_bytes,
            )

    spec = _collection().model_copy(update={"venues": (ExchangeVenue.SSE,)})
    _, staging_path = EvidenceCollector(
        _collector_policy(),
        client=UnsupportedDocumentClient(),
        limiter=_NoopLimiter(),
        now=lambda: NOW,
    ).collect(spec, tmp_path / "failed-text-staging")
    result = EvidencePublisher().publish(
        staging_path, tmp_path / "failed-text-store", _publication()
    )

    item = result.manifest.items[0]
    assert item.extraction_status is ExtractionStatus.FAILED
    assert item.extracted_text is None
    assert item.text_ref is None
    assert (result.path / item.raw_ref.logical_path).read_bytes() == b"unsupported-source-bytes"
    assert "TEXT_EXTRACTION_FAILED" in result.manifest.limitations


def test_urllib_transport_enforces_host_and_response_byte_limit() -> None:
    class Response:
        status = 200

        def __init__(self, body: bytes) -> None:
            self._body = body
            self.headers = Message()
            self.headers["Content-Type"] = "text/plain; charset=utf-8"
            self.headers["ETag"] = '"fixture"'

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def read(self, size: int) -> bytes:
            return self._body[:size]

    class Opener:
        def __init__(self, body: bytes) -> None:
            self.body = body

        def open(self, request: object, timeout: float) -> Response:
            del request, timeout
            return Response(self.body)

    class ErrorOpener:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code
            self.calls = 0

        def open(self, request: object, timeout: float) -> Response:
            del request, timeout
            self.calls += 1
            headers = Message()
            headers["Content-Type"] = "text/plain; charset=utf-8"
            raise HTTPError(
                "https://allowed.example/document.txt",
                self.status_code,
                "fixture error",
                headers,
                BytesIO(b"fixture error body"),
            )

    contract = EvidenceHttpRequest(
        sequence=1,
        venue=ExchangeVenue.SSE,
        purpose="DOCUMENT",
        method="GET",
        url="https://allowed.example/document.txt",
    )
    prepared = PreparedHttpRequest(
        contract=contract,
        body=None,
        headers=(("User-Agent", "test-agent"),),
    )
    client = UrllibHttpClient(("allowed.example",))
    client._opener = Opener(b"hello")  # type: ignore[reportPrivateUsage]

    response = client.send(prepared, timeout_seconds=1, max_response_bytes=10)
    assert response.body == b"hello"
    assert response.media_type == "text/plain"
    assert response.encoding == "utf-8"
    assert response.etag == '"fixture"'

    client._opener = Opener(b"too-large")  # type: ignore[reportPrivateUsage]
    with pytest.raises(EvidenceCollectionError, match="byte limit"):
        client.send(prepared, timeout_seconds=1, max_response_bytes=2)

    escaped = PreparedHttpRequest(
        contract=contract.model_copy(update={"url": "https://evil.example/document.txt"}),
        body=None,
        headers=(),
    )
    with pytest.raises(EvidenceCollectionError, match="host allowlist"):
        client.send(escaped, timeout_seconds=1, max_response_bytes=10)

    nondefault_port = PreparedHttpRequest(
        contract=contract.model_copy(update={"url": "https://allowed.example:444/document.txt"}),
        body=None,
        headers=(),
    )
    with pytest.raises(EvidenceCollectionError, match="host allowlist"):
        client.send(nondefault_port, timeout_seconds=1, max_response_bytes=100)

    nonretryable = ErrorOpener(404)
    client._opener = nonretryable  # type: ignore[reportPrivateUsage]
    policy = _collector_policy().model_copy(
        update={
            "allowed_hosts": ("allowed.example",),
            "max_attempts": 3,
        }
    )
    collector = EvidenceCollector(policy, client=client, limiter=_NoopLimiter())
    with pytest.raises(EvidenceCollectionError, match="HTTP 404"):
        collector._fetch(prepared)  # type: ignore[reportPrivateUsage]
    assert nonretryable.calls == 1

    retryable = ErrorOpener(503)
    client._opener = retryable  # type: ignore[reportPrivateUsage]
    with pytest.raises(EvidenceCollectionError, match="3 attempt"):
        collector._fetch(prepared)  # type: ignore[reportPrivateUsage]
    assert retryable.calls == 3


def test_dedicated_collector_cli_covers_success_failure_and_secret_removal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = CliRunner()

    class StubCollector:
        def __init__(self, policy: object) -> None:
            del policy

        def collect(self, spec: object, staging_root: Path) -> tuple[object, Path]:
            del spec
            return SimpleNamespace(staging_hash="a" * 64, announcements=()), staging_root

    monkeypatch.setattr(collector_cli, "EvidenceCollector", StubCollector)
    monkeypatch.setenv("TUSHARE_TOKEN", "must-not-survive")
    collected = runner.invoke(
        collector_cli.app,
        [
            "configs/evidence/collection_example.yaml",
            "configs/evidence/collector_v1.yaml",
            "--staging-root",
            str(tmp_path / "cli-staging"),
        ],
    )
    assert collected.exit_code == 0
    assert json.loads(collected.stdout)["status"] == "SUCCEEDED"
    assert "TUSHARE_TOKEN" not in collector_cli.os.environ

    invalid = tmp_path / "invalid.yaml"
    invalid.write_text("schema_version: wrong\n", encoding="utf-8")
    failed = runner.invoke(
        collector_cli.app,
        [str(invalid), "configs/evidence/collector_v1.yaml"],
    )
    assert failed.exit_code == 5
    assert json.loads(failed.stdout)["reason_code"] == "SCHEMA_INVALID"


def test_publisher_cli_publishes_verifies_and_rejects_extra_file(tmp_path: Path) -> None:
    _, staging_path = EvidenceCollector(
        _collector_policy(),
        client=_FixtureHttpClient(),
        limiter=_NoopLimiter(),
        now=lambda: NOW,
    ).collect(_collection(), tmp_path / "publisher-cli-staging")
    output_root = tmp_path / "publisher-cli-store"
    runner = CliRunner()
    failed = runner.invoke(
        publisher_cli.app,
        [
            "publish",
            str(staging_path),
            "configs/evidence/availability_v1.yaml",
            "configs/evidence/parser_v1.yaml",
            "--code-commit-hash",
            "not-a-commit-hash",
            "--runtime-fingerprint-hash",
            "b" * 64,
            "--output-root",
            str(tmp_path / "invalid-publication"),
        ],
    )
    assert failed.exit_code == 5
    assert json.loads(failed.stdout)["reason_code"] == "SCHEMA_INVALID"

    published = runner.invoke(
        publisher_cli.app,
        [
            "publish",
            str(staging_path),
            "configs/evidence/availability_v1.yaml",
            "configs/evidence/parser_v1.yaml",
            "--code-commit-hash",
            "a" * 40,
            "--runtime-fingerprint-hash",
            "b" * 64,
            "--output-root",
            str(output_root),
        ],
    )
    assert published.exit_code == 0
    payload = json.loads(published.stdout)
    assert payload["status"] == "SUCCEEDED"
    store_path = output_root / payload["store"]["logical_path"]

    verified = runner.invoke(publisher_cli.app, ["verify", str(store_path)])
    assert verified.exit_code == 0
    assert json.loads(verified.stdout)["status"] == "SUCCEEDED"

    (store_path / "unexpected.txt").write_text("extra", encoding="utf-8")
    rejected = runner.invoke(publisher_cli.app, ["verify", str(store_path)])
    assert rejected.exit_code == 5
    assert json.loads(rejected.stdout)["reason_code"] == "ARTIFACT_CORRUPTED"


def test_publisher_rejects_symlink_output_root(tmp_path: Path) -> None:
    _, staging_path = EvidenceCollector(
        _collector_policy(),
        client=_FixtureHttpClient(),
        limiter=_NoopLimiter(),
        now=lambda: NOW,
    ).collect(_collection(), tmp_path / "symlink-staging")
    real_output = tmp_path / "real-output"
    real_output.mkdir()
    symlink_output = tmp_path / "symlink-output"
    symlink_output.symlink_to(real_output, target_is_directory=True)

    with pytest.raises(EvidencePublicationError, match="real directory"):
        EvidencePublisher().publish(staging_path, symlink_output, _publication())


def test_publisher_rejects_corrupted_staging_before_publication(tmp_path: Path) -> None:
    _, staging_path = EvidenceCollector(
        _collector_policy(),
        client=_FixtureHttpClient(),
        limiter=_NoopLimiter(),
        now=lambda: NOW,
    ).collect(_collection(), tmp_path / "corrupted-staging")
    (staging_path / "unexpected.txt").write_text("extra", encoding="utf-8")

    with pytest.raises(EvidencePublicationError, match="exact-file"):
        EvidencePublisher().publish(staging_path, tmp_path / "unused-store", _publication())
