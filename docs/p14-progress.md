# P14 progress

Status date: 2026-09-11

P14a is complete. P14b is the next implementation stage; P14c and P14d have not started, and this
record grants no campaign-selection or autonomous-research authority.

## Completed P14a scope

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
- `ResearchContextAgentBinding` and the P14 AgentRunSpec constructor require the selected
  ContextPack hash plus its ledger snapshot, search policy, access scope, budget, request, and
  result hashes in `input_artifact_hashes`. Retained AgentRun manifests can be checked against the
  same binding without changing the frozen `AgentRunManifest` v1 schema.
- `scripts/p14a_qualification.py` requires a clean Git checkout, captures code/lockfile and runtime
  provenance, executes the frozen synthetic ledger/context case in two independent output roots,
  verifies published index and ContextPack artifacts, and publishes an immutable report.

Frozen policy inputs:

- `configs/research/ledger_search_v1.yaml`:
  `3580b935b13c49ba4c0c6bba2f41af594fc56e61879e8dc23c54804ab12547bc`
- `configs/research/context_budget_v1.yaml`:
  `34e5932af37c53a8bc9e884e698b02ead34c960b255bef21f6c65a26f39c4f21`

## Current verification

- Ruff format/check: PASS
- Pyright: 0 errors / 0 warnings
- Pytest: 329 passed
- Coverage: 85.07%, above the unchanged 85% gate
- Tests cover independent-root hash equality, idempotence, chain/object tampering, stale snapshots,
  non-canonical input, query/response/context budgets, cross-campaign policy, sealed contamination,
  MCP dispatch, JSON-RPC schema exposure, and CLI reconstruction.

## Frozen P14a qualification

The clean-checkout runner was executed twice from implementation commit `c0aae76`; both executions
returned the same immutable result:

- qualification report: `b93521362f5d5bd426de0451a665c4a57674fe1cf164daa250920fde8653b47b`
- ledger snapshot: `ac682f98a3ecc0b11acd50f08963565352f747a7ffc6c2aa1547abd669367517`
- lexical index: `a13be26356000884e78e96a74b9472c64b5be38e3dffd15163fc11c1f50c75b2`
- ContextPack: `ed7bbe379730d5ef43dcc7769435f0203dad7acfbbfa3340d944a07023276102`
- context-bound AgentRunSpec: `cb184a75280457bbecddc8e9cd6ff7222d1bf285e619b122690fa46c7e278ecb`
- status/verdict: `SUCCEEDED / PASS`
- limitation: `SYNTHETIC_OFFLINE_ENGINEERING_EVIDENCE`

The report is offline engineering qualification. It does not make an Agent proposal into evidence,
does not qualify P14b/P14c selection, and does not authorize P14d.

## Next stage

P14b starts with a frozen factor-template contract, explicit named parameter slots, deterministic
finite-family enumeration, canonical expression fingerprints, duplicate evidence, and distinct
candidate-versus-trial accounting. No mutation or crossover is in scope.
