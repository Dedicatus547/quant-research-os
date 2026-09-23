# P14 progress

Status date: 2026-09-22

P14a is complete. P14b is implemented as frozen-family enumeration and duplicate evidence. P14c
and P14d have not started, and this record grants no campaign-selection or autonomous-research
authority.

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
- Verification recomputes UUIDv5 event identities, rejects every duplicate node ID, prevents an
  existing object hash from being relabeled to a different access/campaign binding anywhere in the
  same ledger root, rejects unknown ledgers and snapshots predating their chain head, and
  revalidates contract instances at every public service boundary.
- `ResearchLedgerSnapshot` and the lexical index are derived entirely from the immutable object and
  event tree. Snapshot hashes exclude the caller-supplied observation timestamp while persisted
  snapshot JSON retains that timestamp.
- The frozen `unicode-word-v1` tokenizer and `term-frequency-object-hash-v1` ranking return bounded
  content plus query/request/result/index hashes. Exact duplicate objects are returned once.
- The search policy also freezes query bytes, per-hit bytes, index entries, terms per object, and
  serialized index bytes. MCP bindings cannot configure a response or hit larger than the MCP
  payload/string boundary.
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
  `9b48489eec40b545fd4941f356bbfc717d0f185ce7ed646b7eba9c99b7d69369`
- `configs/research/context_budget_v1.yaml`:
  `34e5932af37c53a8bc9e884e698b02ead34c960b255bef21f6c65a26f39c4f21`

## Current verification

- Ruff format/check: PASS
- Pyright: 0 errors / 0 warnings
- Pytest: 448 passed
- Coverage: 85.02%, above the unchanged 85% gate
- Tests cover independent-root hash equality, idempotence, chain/object tampering, stale snapshots,
  non-canonical input, query/response/context budgets, cross-campaign policy, sealed contamination,
  MCP dispatch, JSON-RPC schema exposure, and CLI reconstruction.

## Frozen P14a qualification

The hardened clean-checkout runner was executed twice from implementation commit `5032fea`; both
executions returned the same immutable result:

- qualification report: `9954649acc79c3b3aed42d2e3b9b73c9e7a8de7b8f0c7cd2577393e26d9d8640`
- ledger snapshot: `ac682f98a3ecc0b11acd50f08963565352f747a7ffc6c2aa1547abd669367517`
- lexical index: `743e24dcb350a1f5f5ed0ac07cb7bb4cef04917df20fa51934e6daad58540c08`
- ContextPack: `00db8b701710f204c3a89e014e706d57523e9f91c1afc4a66b52a44b8db89406`
- context-bound AgentRunSpec: `1803b8a60f77ef672b43ac3b26e70a60e46c3b280a7861c2b18517379ba9880d`
- status/verdict: `SUCCEEDED / PASS`
- limitation: `SYNTHETIC_OFFLINE_ENGINEERING_EVIDENCE`

The report is offline engineering qualification. It does not make an Agent proposal into evidence,
does not qualify P14b/P14c selection, and does not authorize P14d.

This report supersedes the earlier P14a reports
`e523ba71550df9d761c5272826e0260d7cf67a00f641d5b11e9430e15d29bc02` and
`b93521362f5d5bd426de0451a665c4a57674fe1cf164daa250920fde8653b47b`; those immutable artifacts are
retained as historical engineering evidence and are no longer the current P14a qualification.

## Next stage

P14b is implemented as frozen-family engineering evidence and remains unqualified research
selection. It adds:

- `ResearchFactorTemplateSpec` + `ResearchFactorTemplateNode` / `ResearchTemplateParameterSlot`
  with one explicit named slot per free window parameter.
- Deterministic finite Cartesian enumeration (`enumerate_research_family`), canonical parameter
  ordering, strict template/dimension binding, and no mutation or crossover.
- `exact_expression_hash` ignores only presentation-level `expression_id`; structural fingerprints
  normalize node IDs while preserving topology, operator parameters, field names, and windows.
- `CandidateDuplicateEvidence` exact/structural groups. Structural groups are evidence only, and
  exact groups suppress redundant structural grouping.
- Deterministic candidate identities over family/template/parameters/fingerprints; declared
  candidate counts, template operator allowlists, positive window values, and candidate references
  all fail closed.

Split candidate-versus-trial accounting and campaign-level selection bias remain P14c scope.
P14d stays blocked.
