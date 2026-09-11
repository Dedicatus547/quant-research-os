# P14 progress

Status date: 2026-09-11

P14a is in implementation. P14b, P14c, and P14d have not started, and this record grants no
campaign-selection or autonomous-research authority.

## Implemented P14a slice

- `ResearchLedgerEvent` v1 remains readable as the frozen P9 contract. New writes use
  `ResearchLedgerEventV2`, whose `ResearchLedgerObjectRef` binds the object hash, media type,
  source domain, campaign scope, access class, and contamination hashes.
- Deterministic verdict events can bind either a `ValidationReport` or the future
  `CampaignSelectionReport`; deterministic evidence has distinct experiment, campaign-trial, and
  ResearchResult node kinds.
- `ResearchLedgerService` publishes canonical content-addressed objects and deterministic UUIDv5
  events with create-if-absent semantics. Exact retries are idempotent; conflicting node IDs,
  missing/forward parents, non-canonical bytes, broken chains, unsafe paths, and tampering fail
  closed.
- `ResearchLedgerSnapshot` and the lexical index are derived entirely from the immutable object and
  event tree. Snapshot hashes exclude the caller-supplied observation timestamp while persisted
  snapshot JSON retains that timestamp.
- The frozen `unicode-word-v1` tokenizer and `term-frequency-object-hash-v1` ranking return bounded
  content plus query/request/result/index hashes. Exact duplicate objects are returned once.
- Search access binds a campaign, ledger snapshot, readable campaign allowlist, and sealed-object
  allowlist. A sealed object additionally requires all of its contamination hashes in the trusted
  access scope. Authorized historical cross-campaign retrieval is supported; unbound sealed data is
  not.
- `ResearchContextPack` binds the search request/result, access scope, search policy, and context
  budget. Both per-item bytes and complete serialized-pack bytes fail closed on overflow.
- Rebuilt indexes and ContextPacks can be published into explicit content-addressed output roots;
  verification checks canonical bytes, hash-derived filenames, and equality with a fresh rebuild.
  Index artifacts remain derived caches and never become authority.
- `research.search_ledger` is now part of the typed MCP/JSON-RPC surface. The MCP service receives
  server-side `LedgerSearchBinding` objects; the caller cannot supply paths or expand its authority.
- CLI commands `quantos ledger verify`, `quantos ledger search`, and
  `quantos ledger context-pack` accept explicit canonical, hash-bound inputs.

Frozen policy inputs:

- `configs/research/ledger_search_v1.yaml`:
  `3580b935b13c49ba4c0c6bba2f41af594fc56e61879e8dc23c54804ab12547bc`
- `configs/research/context_budget_v1.yaml`:
  `34e5932af37c53a8bc9e884e698b02ead34c960b255bef21f6c65a26f39c4f21`

## Current verification

- Ruff format/check: PASS
- Pyright: 0 errors / 0 warnings
- Pytest: 327 passed
- Coverage: 85.02%, above the unchanged 85% gate
- Tests cover independent-root hash equality, idempotence, chain/object tampering, stale snapshots,
  non-canonical input, query/response/context budgets, cross-campaign policy, sealed contamination,
  MCP dispatch, JSON-RPC schema exposure, and CLI reconstruction.

## Remaining P14a qualification work

1. Bind the selected ContextPack hash into the concrete P14 AgentRun construction path. Existing
   `AgentRunManifest.input_hashes` can carry the binding, but no P14 campaign runner exists yet.
2. Add a clean-checkout, independent-output-root P14a qualification runner and freeze its report.
3. Only after those gates pass, mark P14a complete and begin P14b template/enumeration work.
