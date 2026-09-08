# P12 Real-world Evidence Acquisition progress

Status date: 2026-09-09

Status: **complete; clean-commit freeze passed**.

P12 has the intended architecture, passed a bounded real-source collector probe, and published the
same verified Evidence Store byte-for-byte into two independent output roots from clean
implementation commit `60b8c811eba175af9914d55668f341a7b332d6f7`. The committed report contains
hashes and counts only; exchange PDFs and extracted text remain workspace-local.

## Implemented boundary

- harness-independent acquisition/publication contracts for collection spec, collector policy,
  availability/license policy, parser config, HTTP request/response metadata, completeness witness,
  staging manifest, published item, and Evidence Store manifest;
- separate `quantos-evidence-collector` and `quantos-evidence-publisher` entry points;
- SSE GET and SZSE JSON POST adapters using only the official announcement protocols frozen in
  [ADR-0002](adr/0002-exchange-evidence-acquisition.md);
- HTTPS/domain/redirect allowlist, bounded 32-day queries, at most 25,000 announcements, configured
  rate/retry/timeout/response-byte budgets, payload hashes, and secret-free audit metadata;
- official total/count-based pagination witnesses, including a retained explicit source response
  for legitimate zero-result queries;
- content-addressed staging and Evidence Store publication with semantic exact-file-set,
  symlink/special-file, size, hash, request/response, policy, raw/text, and manifest verification;
- deterministic PDF/plain-text/HTML extraction with parser/config/code/runtime lineage;
- conservative SSE date-only time handling, exact separation of published/fetched/observed/available,
  and fail-closed unknown/invalid time;
- immutable retention of raw evidence when text extraction fails, without inventing text or labels;
- frozen `RESEARCH_ALLOWED` local non-commercial SSE policy and conservative `UNKNOWN` SZSE policy.

The network-free publisher import path was checked independently: importing
`quantos.evidence.publisher_cli` does not load `quantos.evidence.collector`.

## Bounded official-source probe

The probe used collection spec `exchange-announcements-2025-01-02`, security code `300777`, one
calendar day, both venues, page size 25, and a combined hard ceiling of 50 announcements. Output was
written only below `/tmp`; it is non-authoritative smoke evidence and may be removed by the host.

```text
staging hash  e63ecc4b73c166eb202676d9776ff9d24aeb04eab8aaf9216810585bddf6d301
SSE witness  reported=0 collected=0 pages=1 complete=true
SZSE witness reported=3 collected=3 pages=1 complete=true
documents    3 PDFs, 507,505 raw bytes
file set     18/18 files verified
```

All three frozen PDFs passed the locked parser smoke without retaining or printing source text:

```text
pages             11 / 6 / 2
normalized chars  7,264 / 2,895 / 495
empty-text flags  none
```

The zero SSE result is accepted only because the official response explicitly reported total zero.
No claim is made that SZSE content is licensed for downstream research or that any announcement is
factually true.

## Verification

```text
ruff                       PASS
pyright                    PASS (0 errors)
new P12 tests              PASS (17/17)
full repository regression PASS (279/279)
branch coverage gate       PASS (85.04% >= 85%)
```

The tests cover bounded/hashable contracts, malformed request and count semantics, both official
response shapes, explicit zero results, retry audit counts, deterministic PDF/text/HTML behavior,
two independent Evidence Store output roots with identical hashes, raw retention on extraction
failure, CLI success/failure behavior, byte/domain/path boundaries, staging/store tamper rejection,
and document host denial.

## Clean-commit freeze evidence

The network-restricted publisher ran twice against the retained hash-addressed staging directory.
Both output roots contained the same 17 files byte-for-byte and verified independently.

```text
implementation commit  60b8c811eba175af9914d55668f341a7b332d6f7
lockfile hash           6aacea0cae766141f46c9b28ad1ef419182291b77e6556e6336e9a2e934ec917
runtime fingerprint     66d954a1ff034d6ecb555885e12926e585543a4d71c92ea35bb5720465730321
staging manifest        e63ecc4b73c166eb202676d9776ff9d24aeb04eab8aaf9216810585bddf6d301
Evidence Store          c55e9ba41c60c8443c979396277cfad5ed5d4f7c2344a4348a91b1b63b566a7f
freeze report           9a97dc04ba74de26bbd3cd02932db9f90c911fac001cc773651d68643db374f4
independent roots       byte-exact PASS
extraction              3/3 SUCCEEDED
permission              3/3 UNKNOWN (SZSE)
```

The compact, non-licensed report is
[`artifacts/feasibility/evidence-p12/report.json`](../artifacts/feasibility/evidence-p12/report.json).
It explicitly records that no EventFeature was admitted and no Data-qualified market conclusion was
made.

P13 event labels, admission benchmark, EventFeatureArtifact, trading-session alignment, research
metrics, production MCP transport, and Agent-generated extraction remain outside P12.
