"""Network-enabled collector that can write only bounded acquisition staging."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from http.client import HTTPMessage
from pathlib import Path
from typing import IO, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pyrate_limiter import Duration, Limiter, Rate  # pyright: ignore[reportMissingTypeStubs]
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from quantos.artifacts.store import (
    atomic_write_bytes,
    publish_directory,
    regular_tree_files,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.evidence_acquisition import (
    AnnouncementCandidate,
    EvidenceCollectionSpec,
    EvidenceCollectorPolicy,
    EvidenceCompletenessWitness,
    EvidenceFile,
    EvidenceHttpRequest,
    EvidenceHttpResponseMetadata,
    EvidenceStagingManifest,
    StagedAnnouncement,
)
from quantos.contracts.status import ReasonCode
from quantos.evidence.sources import source_for


class EvidenceCollectionError(RuntimeError):
    def __init__(self, reason_code: ReasonCode, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class _RetryableHttpError(RuntimeError):
    pass


@dataclass(frozen=True)
class PreparedHttpRequest:
    contract: EvidenceHttpRequest
    body: bytes | None
    headers: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: bytes
    media_type: str
    encoding: str | None
    fetched_at: datetime
    observed_at: datetime
    etag: str | None = None
    last_modified: str | None = None


class HttpClient(Protocol):
    def send(
        self,
        request: PreparedHttpRequest,
        *,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> HttpResponse: ...


class AcquisitionLimiter(Protocol):
    def try_acquire(self, name: str, weight: int = 1) -> bool: ...


class _AllowlistedRedirectHandler(HTTPRedirectHandler):
    def __init__(self, allowed_hosts: frozenset[str]) -> None:
        self._allowed_hosts = allowed_hosts
        super().__init__()

    def redirect_request(  # type: ignore[override]
        self,
        req: Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> Request | None:
        if not _is_allowed_https_url(newurl, self._allowed_hosts):
            raise URLError("redirect target is outside the evidence host allowlist")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _is_allowed_https_url(url: str, allowed_hosts: frozenset[str]) -> bool:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname in allowed_hosts
        and port in (None, 443)
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
    )


class UrllibHttpClient:
    """Small HTTP transport with bounded reads and allowlisted redirects."""

    def __init__(self, allowed_hosts: tuple[str, ...]) -> None:
        self._allowed_hosts = frozenset(allowed_hosts)
        self._opener = build_opener(_AllowlistedRedirectHandler(self._allowed_hosts))

    def send(
        self,
        request: PreparedHttpRequest,
        *,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> HttpResponse:
        if not _is_allowed_https_url(request.contract.url, self._allowed_hosts):
            raise EvidenceCollectionError(
                ReasonCode.EVIDENCE_DOMAIN_DENIED,
                "request URL is outside the evidence host allowlist",
            )
        headers = dict(request.headers)
        raw_request = Request(
            request.contract.url,
            data=request.body,
            headers=headers,
            method=request.contract.method,
        )
        fetched_at = datetime.now(UTC)
        try:
            with self._opener.open(raw_request, timeout=timeout_seconds) as response:
                body = response.read(max_response_bytes + 1)
                observed_at = datetime.now(UTC)
                if len(body) > max_response_bytes:
                    raise EvidenceCollectionError(
                        ReasonCode.EVIDENCE_RESPONSE_TOO_LARGE,
                        "evidence response exceeded the configured byte limit",
                    )
                media_type = response.headers.get_content_type()
                encoding = response.headers.get_content_charset()
                return HttpResponse(
                    status_code=response.status,
                    body=body,
                    media_type=media_type,
                    encoding=encoding,
                    fetched_at=fetched_at,
                    observed_at=observed_at,
                    etag=response.headers.get("ETag"),
                    last_modified=response.headers.get("Last-Modified"),
                )
        except EvidenceCollectionError:
            raise
        except HTTPError as error:
            if error.code == 429 or error.code >= 500:
                raise _RetryableHttpError("bounded evidence HTTP request failed") from error
            body = error.read(max_response_bytes + 1)
            observed_at = datetime.now(UTC)
            if len(body) > max_response_bytes:
                raise EvidenceCollectionError(
                    ReasonCode.EVIDENCE_RESPONSE_TOO_LARGE,
                    "evidence response exceeded the configured byte limit",
                ) from None
            return HttpResponse(
                status_code=error.code,
                body=body,
                media_type=error.headers.get_content_type(),
                encoding=error.headers.get_content_charset(),
                fetched_at=fetched_at,
                observed_at=observed_at,
                etag=error.headers.get("ETag"),
                last_modified=error.headers.get("Last-Modified"),
            )
        except (URLError, TimeoutError, OSError) as error:
            raise _RetryableHttpError("bounded evidence HTTP request failed") from error


def _media_type_for_path(path: Path) -> str:
    if path.suffix == ".json":
        return "application/json"
    if path.suffix == ".pdf":
        return "application/pdf"
    if path.suffix == ".txt":
        return "text/plain"
    if path.suffix in {".htm", ".html"}:
        return "text/html"
    return "application/octet-stream"


def _raw_suffix(media_type: str) -> str:
    normalized = media_type.casefold().split(";", 1)[0].strip()
    return {
        "application/pdf": ".pdf",
        "application/xhtml+xml": ".html",
        "text/html": ".html",
        "text/plain": ".txt",
    }.get(normalized, ".bin")


def _file_contract(path: Path, root: Path, *, media_type: str | None = None) -> EvidenceFile:
    relative = path.relative_to(root).as_posix()
    data = path.read_bytes()
    return EvidenceFile(
        logical_path=relative,
        sha256=sha256_bytes(data),
        size_bytes=len(data),
        media_type=media_type or _media_type_for_path(path),
    )


class EvidenceCollector:
    """Collect official announcement bytes without access to an authority store."""

    def __init__(
        self,
        policy: EvidenceCollectorPolicy,
        *,
        client: HttpClient | None = None,
        limiter: AcquisitionLimiter | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._policy = policy
        self._client = client or UrllibHttpClient(policy.allowed_hosts)
        self._limiter = limiter or Limiter(
            Rate(policy.requests_per_minute, Duration.MINUTE), raise_when_fail=False
        )
        self._now = now or (lambda: datetime.now(UTC))
        self._sequence = 0

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def _validate_url(self, url: str) -> None:
        if not _is_allowed_https_url(url, frozenset(self._policy.allowed_hosts)):
            raise EvidenceCollectionError(
                ReasonCode.EVIDENCE_DOMAIN_DENIED,
                "evidence URL is not an allowlisted absolute HTTPS URL",
            )

    def _fetch(
        self, request: PreparedHttpRequest
    ) -> tuple[HttpResponse, EvidenceHttpResponseMetadata]:
        self._validate_url(request.contract.url)
        if request.body is None:
            if request.contract.body_hash is not None:
                raise EvidenceCollectionError(
                    ReasonCode.EVIDENCE_RESPONSE_INVALID, "request body binding is inconsistent"
                )
        elif sha256_bytes(request.body) != request.contract.body_hash:
            raise EvidenceCollectionError(
                ReasonCode.EVIDENCE_RESPONSE_INVALID, "request body hash does not match"
            )
        attempt_count = 0

        def send() -> HttpResponse:
            nonlocal attempt_count
            attempt_count += 1
            if not self._limiter.try_acquire("exchange-evidence"):
                raise _RetryableHttpError("configured evidence rate limit was not acquired")
            response = self._client.send(
                request,
                timeout_seconds=self._policy.request_timeout_seconds,
                max_response_bytes=self._policy.max_response_bytes,
            )
            if response.status_code == 429 or response.status_code >= 500:
                raise _RetryableHttpError("evidence source returned a retryable status")
            return response

        try:
            retryer = Retrying(
                stop=stop_after_attempt(self._policy.max_attempts),
                wait=wait_exponential(
                    multiplier=self._policy.retry_min_seconds,
                    min=self._policy.retry_min_seconds,
                    max=self._policy.retry_max_seconds,
                ),
                retry=retry_if_exception_type(_RetryableHttpError),
                reraise=True,
            )
            response = retryer(send)
        except EvidenceCollectionError:
            raise
        except Exception:
            raise EvidenceCollectionError(
                ReasonCode.SOURCE_INCOMPLETE,
                "evidence request failed after "
                f"{attempt_count} attempt(s); source detail suppressed",
            ) from None
        if response.status_code != 200:
            raise EvidenceCollectionError(
                ReasonCode.SOURCE_INCOMPLETE,
                f"evidence source returned HTTP {response.status_code}",
            )
        if len(response.body) > self._policy.max_response_bytes:
            raise EvidenceCollectionError(
                ReasonCode.EVIDENCE_RESPONSE_TOO_LARGE,
                "evidence response exceeded the configured byte limit",
            )
        metadata = EvidenceHttpResponseMetadata(
            request_hash=request.contract.content_hash,
            status_code=response.status_code,
            fetched_at=response.fetched_at,
            observed_at=response.observed_at,
            media_type=response.media_type,
            encoding=response.encoding,
            content_length=len(response.body),
            body_hash=sha256_bytes(response.body),
            etag=response.etag,
            last_modified=response.last_modified,
            attempt_count=attempt_count,
        )
        return response, metadata

    @staticmethod
    def _write_exchange(
        root: Path,
        request: PreparedHttpRequest,
        response: HttpResponse,
        metadata: EvidenceHttpResponseMetadata,
    ) -> None:
        prefix = Path("exchanges") / f"{request.contract.sequence:06d}"
        atomic_write_bytes(root / f"{prefix}.request.json", request.contract.canonical_bytes())
        if request.body is not None:
            atomic_write_bytes(
                root / f"{prefix}.request-body.json",
                request.body,
                expected_sha256=request.contract.body_hash,
            )
        atomic_write_bytes(root / f"{prefix}.response.bin", response.body)
        atomic_write_bytes(root / f"{prefix}.response-metadata.json", metadata.canonical_bytes())

    def collect(
        self, spec: EvidenceCollectionSpec, staging_root: Path
    ) -> tuple[EvidenceStagingManifest, Path]:
        """Collect one bounded date range into a hash-addressed staging directory."""

        self._sequence = 0
        staging_root.mkdir(parents=True, exist_ok=True)
        if staging_root.is_symlink() or not staging_root.is_dir():
            raise EvidenceCollectionError(
                ReasonCode.PATH_BOUNDARY_VIOLATION, "staging root must be a real directory"
            )
        temporary = Path(tempfile.mkdtemp(prefix=".evidence-collection-", dir=staging_root))
        started_at = self._now()
        discovery_requests: list[EvidenceHttpRequest] = []
        discovery_responses: list[EvidenceHttpResponseMetadata] = []
        candidates_with_source: list[tuple[AnnouncementCandidate, str, str]] = []
        witnesses: list[EvidenceCompletenessWitness] = []
        source_total = 0
        try:
            atomic_write_bytes(temporary / "collection-spec.json", spec.canonical_bytes())
            atomic_write_bytes(temporary / "collector-policy.json", self._policy.canonical_bytes())
            for venue in spec.venues:
                source = source_for(venue)
                page_number = 1
                reported_total: int | None = None
                total_pages: int | None = None
                page_counts: list[int] = []
                venue_candidates: list[tuple[AnnouncementCandidate, str, str]] = []
                while True:
                    prepared_source = source.build_request(
                        spec, page=page_number, sequence=self._next_sequence()
                    )
                    prepared = PreparedHttpRequest(
                        contract=prepared_source.contract,
                        body=prepared_source.body,
                        headers=(
                            *prepared_source.headers,
                            ("User-Agent", self._policy.user_agent),
                        ),
                    )
                    response, metadata = self._fetch(prepared)
                    self._write_exchange(temporary, prepared, response, metadata)
                    try:
                        page = source.parse_page(response.body, spec, page=page_number)
                    except ValueError as error:
                        raise EvidenceCollectionError(
                            ReasonCode.EVIDENCE_RESPONSE_INVALID,
                            "official announcement response failed the frozen parser schema",
                        ) from error
                    if reported_total is None:
                        reported_total = page.reported_total
                        total_pages = page.total_pages
                        source_total += reported_total
                        if source_total > spec.max_announcements:
                            raise EvidenceCollectionError(
                                ReasonCode.RESOURCE_BUDGET_EXCEEDED,
                                "official source count exceeds the collection budget",
                            )
                    elif page.reported_total != reported_total or page.total_pages != total_pages:
                        raise EvidenceCollectionError(
                            ReasonCode.SOURCE_INCOMPLETE,
                            "source pagination totals changed during collection",
                        )
                    discovery_requests.append(prepared.contract)
                    discovery_responses.append(metadata)
                    page_counts.append(page.collected_units)
                    venue_candidates.extend(
                        (item, prepared.contract.content_hash, metadata.content_hash)
                        for item in page.candidates
                    )
                    if total_pages is None or page_number >= total_pages:
                        break
                    page_number += 1
                assert reported_total is not None
                collected_total = sum(page_counts)
                complete = reported_total == collected_total
                witness = EvidenceCompletenessWitness(
                    venue=venue,
                    query_hash=sha256_bytes(
                        canonical_json_bytes(
                            {"collection_spec_hash": spec.content_hash, "venue": venue}
                        )
                    ),
                    unit=page.unit,
                    reported_total=reported_total,
                    collected_total=collected_total,
                    page_count=len(page_counts),
                    page_item_counts=tuple(page_counts),
                    complete=complete,
                    reason=(
                        "source total equals the complete bounded page traversal"
                        if complete
                        else "source total differs from collected page units"
                    ),
                )
                if not witness.complete:
                    raise EvidenceCollectionError(
                        ReasonCode.SOURCE_INCOMPLETE,
                        "official source completeness witness failed",
                    )
                witnesses.append(witness)
                candidates_with_source.extend(venue_candidates)

            identities = [(item.venue, item.source_id) for item, _, _ in candidates_with_source]
            if len(identities) != len(set(identities)):
                raise EvidenceCollectionError(
                    ReasonCode.EVIDENCE_RESPONSE_INVALID,
                    "official source returned duplicate announcement identities",
                )
            staged: list[StagedAnnouncement] = []
            for candidate, discovery_request_hash, discovery_metadata_hash in sorted(
                candidates_with_source,
                key=lambda entry: (str(entry[0].venue), entry[0].source_id),
            ):
                self._validate_url(candidate.document_url)
                document_request = EvidenceHttpRequest(
                    sequence=self._next_sequence(),
                    venue=candidate.venue,
                    purpose="DOCUMENT",
                    method="GET",
                    url=candidate.document_url,
                )
                prepared = PreparedHttpRequest(
                    contract=document_request,
                    body=None,
                    headers=(
                        ("Accept", "application/pdf, text/html;q=0.9, text/plain;q=0.8"),
                        ("User-Agent", self._policy.user_agent),
                    ),
                )
                response, metadata = self._fetch(prepared)
                item_id = f"{candidate.venue.value.lower()}-{candidate.content_hash[:24]}"
                suffix = _raw_suffix(response.media_type)
                raw_path = temporary / "documents" / f"{item_id}{suffix}"
                atomic_write_bytes(raw_path, response.body, expected_sha256=metadata.body_hash)
                request_path = temporary / "documents" / f"{item_id}.request.json"
                metadata_path = temporary / "documents" / f"{item_id}.response-metadata.json"
                atomic_write_bytes(request_path, document_request.canonical_bytes())
                atomic_write_bytes(metadata_path, metadata.canonical_bytes())
                staged.append(
                    StagedAnnouncement(
                        candidate=candidate,
                        discovery_request_hash=discovery_request_hash,
                        discovery_response_metadata_hash=discovery_metadata_hash,
                        document_request=document_request,
                        document_response=metadata,
                        raw_file=_file_contract(
                            raw_path, temporary, media_type=response.media_type
                        ),
                    )
                )

            files = tuple(
                sorted(
                    (_file_contract(path, temporary) for path in regular_tree_files(temporary)),
                    key=lambda item: item.logical_path,
                )
            )
            manifest = EvidenceStagingManifest.create(
                collection_spec_hash=spec.content_hash,
                collector_policy_hash=self._policy.content_hash,
                collector_version=self._policy.collector_version,
                started_at=started_at,
                completed_at=self._now(),
                discovery_requests=tuple(discovery_requests),
                discovery_responses=tuple(discovery_responses),
                completeness=tuple(witnesses),
                announcements=tuple(staged),
                files=files,
            )
            atomic_write_bytes(
                temporary / "manifest.json",
                canonical_json_bytes(manifest.model_dump(mode="python")),
            )
            destination = staging_root / f"sha256-{manifest.staging_hash}"
            publish_directory(temporary, destination)
            return manifest, destination
        except Exception:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise
