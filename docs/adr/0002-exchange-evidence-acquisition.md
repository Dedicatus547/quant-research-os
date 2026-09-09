# ADR-0002: Exchange announcement Evidence acquisition boundary

- Status: Accepted for P12 Offline Engineering
- Date: 2026-09-08
- Scope: SSE/SZSE listed-company announcement discovery, raw-byte retention, and deterministic
  text extraction

## Decision

P12 uses two separate executable processes and an immutable freeze boundary:

```text
quantos-evidence-collector (network enabled, staging write only)
  -> hash-addressed non-authority staging
  -> quantos-evidence-publisher (network denied, Evidence Store write only)
  -> immutable raw bytes + EvidenceRecord + ExtractedTextArtifact
```

The collector is not part of market snapshot acquisition and never calls Tushare. It has no LLM,
Qlib, PIT, factor, backtest, Validation, Registry, or authority mutation capability. Its runtime
sandbox must mount only its staging root writable and must not provide `TUSHARE_TOKEN`. The
publisher must run in a network-denied process with staging read-only and one Evidence Store root
writable. Python modules express this split as `quantos.evidence.collector` and
`quantos.evidence.publisher`; the publisher imports only the network-free staging verifier.

OS sandboxing and network namespaces are the enforcement boundary. The CLI split is not itself a
claim that an unrestricted shell is isolated.

## Official source protocol frozen by P12

The official [SSE listed-company announcement page](https://www.sse.com.cn/disclosure/listedinfo/announcement/)
loads `queryCompanyBulletinNew.do`. A bounded probe on 2026-09-08 confirmed a GET response with
`pageHelp.total`, `pageHelp.pageCount`, `pageHelp.pageNo`, and grouped primary/attachment records.
P12 retains exactly one `ORG_FILE_TYPE=0` primary document per group and uses the source `total` as
an `ANNOUNCEMENT_GROUP` completeness witness. Documents are restricted to
the SSE-owned `big5.sse.com.cn` HTTPS mirror. The mirror path is constructed explicitly as
`/site/cht/www.sse.com.cn` plus the root-relative path returned by discovery; the collector never
accepts the mirror's HTTP redirect form.

The official [SZSE listed-company announcement page](https://www.szse.cn/disclosure/listed/notice/index.html)
loads its historical list through `POST /api/disc/announcement/annList` with a JSON date range. A
bounded probe on 2026-09-08 confirmed `announceCount` plus document records containing `id`,
`publishTime`, `attachPath`, and `secCode`. P12 uses `announceCount` as an `ANNOUNCEMENT`
completeness witness. Documents are restricted to `disc.static.szse.cn`.

The fixed network allowlist is:

```text
query.sse.com.cn
big5.sse.com.cn
www.szse.cn
disc.static.szse.cn
```

Only absolute HTTPS URLs on the default HTTPS port are accepted. Userinfo, fragments, non-default
ports, and redirects outside the allowlist are rejected. The collector identifies itself with a
configured User-Agent, defaults to 30 requests per minute, retries only transport/429/5xx failures
under a bounded attempt count, treats other 4xx responses as non-retryable, caps each response at 50
MiB, and records no credentials. Request bodies, raw responses, response hashes, ETag and
Last-Modified values when present, attempt counts, and timezone-aware fetch/observation times are
frozen in staging.

## Completeness and failure semantics

Every requested venue must provide a stable source total and a complete traversal of all reported
pages. Totals changing during traversal, duplicate source identities, malformed pages, a missing
primary SSE document, an over-budget total, or any missing document produces `SOURCE_INCOMPLETE`,
`EVIDENCE_RESPONSE_INVALID`, or `RESOURCE_BUDGET_EXCEEDED`; no partial Evidence Store is
published.

Zero results pass only when the official response explicitly reports total/count zero. One initial
response is retained as the completeness witness. An empty local directory is never evidence of a
complete query.

Both staging and the published store enforce a semantic exact-file set in addition to hashes. A
manifest cannot legitimize an unrelated added file merely by listing it. Symlinks, special files,
hash mismatch, path escape, and partial trees fail with `ARTIFACT_CORRUPTED`.

## Publication, time, and revision semantics

`published_at`, `fetched_at`, `observed_at`, and `available_at` remain distinct:

- SSE `SSEDATE` is date-only. P12 assigns the end of that Asia/Shanghai calendar day as a
  conservative availability bound and records `DATE_ONLY_PUBLICATION_TIME` plus
  `NEXT_TRADING_SESSION_REQUIRED`. P13 must resolve the next eligible market session; it may not
  trade on an assumed intraday release time.
- SZSE `publishTime` is retained at source-provided second precision. P12 does not infer an earlier
  time. A source time after the actual fetch is rejected.
- Missing/invalid time becomes `UNKNOWN_AVAILABILITY` and cannot enter an executable EventFeature.

The source APIs do not expose a complete historical revision ledger. P12 therefore never claims
vendor-vintage or complete revision history. Every collection and every changed byte set creates a
new hash-addressed staging/store; nothing is overwritten. Explicit revision/supersession/retraction
lineage is populated only when a future official source field or separately admitted evidence proves
it. Stores carry `SOURCE_REVISION_HISTORY_NOT_GUARANTEED` meanwhile.

## Text extraction and missing-data propagation

Raw bytes are always the source authority. Deterministic derived text uses locked `pypdf` for PDF,
the Python standard-library decoder for plain text, and `html.parser` for HTML. Output is NFC,
LF-normalized UTF-8 with fixed page separators and trailing-space removal. The artifact binds raw,
text, parser config, parser version, code commit, and runtime fingerprint hashes.

An image-only document is a successful empty extraction with `NO_MACHINE_READABLE_TEXT`; a parser
failure retains raw evidence but marks the item `FAILED / EVIDENCE_TEXT_EXTRACTION_FAILED`. Neither
case can acquire an invented label. P13 admission still requires an exact text hash and source
location.

## License and source-truth boundary

The [SSE legal statement](https://www.sse.com.cn/home/legal/) allows lawful non-commercial browsing
and downloading, while prohibiting unlicensed for-profit redistribution. The P12 SSE policy is
therefore `RESEARCH_ALLOWED` only for this local non-commercial research use; it does not authorize
artifact redistribution.

The SZSE announcement page states copyright and disclaims guaranteed accuracy/completeness, but P12
did not locate an equally explicit non-commercial reuse grant. SZSE is therefore frozen as
`UNKNOWN`, not silently promoted to research-qualified input. Its raw bytes may be retained only in
an operator-authorized workspace and P13 admission fails closed until permission is resolved.

Exchange publication is an auditable source assertion, not independent proof that the issuer's
statement is true. Every store carries `SOURCE_CONTENT_NOT_INDEPENDENTLY_VERIFIED`.

## Consequences and non-goals

- P12 does not implement event extraction, share-repurchase classification, EventFeatureArtifact,
  event-to-trading-day alignment, or event research; those remain P13.
- P12 does not expose `evidence.search/get` over a production MCP transport; P13 must first qualify
  the narrow adapter and negative permissions.
- P12 does not change market-data qualification. Announcement evidence cannot replace the immutable
  Tushare Parquet snapshot.
- Live acquisition evidence is workspace-local and license-sensitive. Fixture E2E proves Offline
  Engineering only; it is not a Data-qualified market conclusion.
