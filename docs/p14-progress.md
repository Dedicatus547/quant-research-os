# P14 progress

Status date: 2026-09-23

P14a and P14b are complete. P14c implementation commit `618498a64b8e46ab5c38f66ea08a03a2afdaea32`
passed its clean-commit, independent double-root qualification with report
`d0412a30d27c4d793fe527a28432292f1616a4ad726830d3cb1ce24a5836913a`. P14c now has qualified
engineering authority. P14d is eligible to start, but is not implemented and receives no authority
from the P14c report.

## P14c engineering implementation

- `docs/p14c-selection-contract.md` freezes one-sided mean daily Rank IC, centered circular
  five-session block bootstrap with 9,999 replicates, SHA256 counter sampling, and Holm correction
  over **all** enumerated family candidates at alpha 0.05. The method states its stationarity and
  validation-reuse limits.
- `CampaignSelectionPlan` freezes method, seed, manifest, and verified Qlib-view trading calendar
  immediately after campaign activation. The service checks that plan before any P14c trial.
- `CampaignSelectionReport` binds the event prefix, every actual trial, every candidate
  disposition, ResearchResult evidence, raw and adjusted p-values, and one optional selected
  candidate. Failed or incomplete inputs yield `FAILED / NOT_EVALUATED`; a complete evaluated run
  without a significant candidate yields `SUCCEEDED / NO_SELECTION`.
- Plan and report artifacts have exact-file, canonical-byte, content-addressed verification.
  `CampaignSelectionService.verify_report` recomputes the verdict from the frozen input artifacts;
  public governor calls cannot freeze a self-reported plan or selection result. A verified
  `SelectionFrozen` event must precede one sealed trial for the selected candidate.
- CLI commands `quantos campaign selection-report` and `selection-verify` accept explicit input
  paths and verify immutable report output. Tests cover golden bootstrap values, independent
  synthetic output roots, complete denominator and trial accounting, zero selection, malformed
  calendar/Rank IC, repeated validation, forged scores, and OOS candidate mismatch.
- Current regression gates: 476 tests passed; coverage 85.07% (minimum 85%, previous recorded
  baseline 85.02%); Ruff format/check passed; Pyright reported 0 errors and 0 warnings.

## Frozen P14c qualification

The formal runner is `scripts/p14c_qualification.py`. It requires the exact clean Git root, binds the
implementation commit, `uv.lock`, Python/runtime fingerprint, frozen P14c contract and policies,
and synthetic fixture. It independently rebuilds root-A and root-B, verifies both roots, compares
their principal hashes, and publishes a content-addressed bundle with exact-file-set verification.
The published bundle was independently re-verified with the runner's `--verify` command.

- implementation commit: `618498a64b8e46ab5c38f66ea08a03a2afdaea32`
- qualification report: `d0412a30d27c4d793fe527a28432292f1616a4ad726830d3cb1ce24a5836913a`
- bundle path: `artifacts/qualification/p14c/sha256-d0412a30d27c4d793fe527a28432292f1616a4ad726830d3cb1ce24a5836913a`
- principal-hash summary: `4ded4d1767ac1a8bc830da5d9aae025af9442b2d24cf4d1a0a74ea1105f83160`
- lockfile SHA-256: `0f5cd349fb32eed64a0cb907242f0ddd333f69efdc77461bdff90602e5bed7ca`
- runtime fingerprint: `66d954a1ff034d6ecb555885e12926e585543a4d71c92ea35bb5720465730321`
- frozen P14c contract: `07ae45cb45078b10a609ffffc8aa6c9f09150a01986e0894c9c062866819f1fa`
- qualification status: `SUCCEEDED / PASS`; all six principal hashes per canonical case are byte
  identical between root-A and root-B; 33 negative cases ran in each root and independently replayed.
- `SELECTED`: `SUCCEEDED / SELECTED`, one candidate `1e90f3d9dd7ff6302b5e621ef3efdcfa9b9e0ffe30c9e8f0c3b316db34b386ba`, raw p-value `0.0001`, Holm-adjusted p-value `0.0002`; report hash `9ec53d3eae797c1eede8748c606c044b1ebaa6db52918e2f1d750160ea8d50fe`; `SelectionFrozen` hash `356d7c07ffd4cdcf7db3bb929368c3e3ac50ed44cbed8408b432037bdf2c0f77`.
- `NO_SELECTION`: `SUCCEEDED / NO_SELECTION`; selection report hash
  `fce90bb9409230016823bef6584292c70a6ff8a3d358e18d9213c45b0e9dd338`.
- `FAILED_NOT_EVALUATED`: `FAILED / NOT_EVALUATED`, reason `ARTIFACT_CORRUPTED`; report hash
  `5f1d3dee451b6ce5c7ca669552407d770d28e70cfd56030309bc39c0f03aed0a`.

The bundle retains the full plan, candidate/trial accounting, ResearchResult, report, event-chain,
and negative-case evidence for both roots. The qualification is `SYNTHETIC_OFFLINE_ENGINEERING_EVIDENCE`:
it establishes no real-market return or profitability result, no vendor-vintage PIT qualification,
and no empirical validation of bootstrap stationarity. It does not prevent undeclared adaptive
validation reuse, authorize mutation/crossover, or authorize an autonomous P14d campaign. P14d may
begin implementation only; its own gates still apply.

## Completed P14b scope

- The factor template binds named parameter slots to window operators; field nodes cannot accept
  parameter slots. Cartesian enumeration covers every declared multi-dimensional combination.
- The authoritative manifest verifier rebuilds candidate identities, expressions, exact and
  structural fingerprints, and duplicate evidence from the frozen family and template.
- The governor accepts factor proposals only when their parameters identify one manifest candidate
  and their expression fingerprints match it. Recorded and replayed trials must reference a
  candidate hash in that manifest.
- Structural fingerprint v2 is invariant to legal topological node listing while preserving input
  order and DAG sharing. Negative tests cover self-reported field tampering and missing duplicate
  evidence.
- Verification: Ruff format/check passed, Pyright reported 0 errors, and Pytest passed 457 tests.

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

## P14b implementation detail

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

Candidate-versus-trial accounting and the frozen selection method are implemented and qualified in
P14c. The immutable report grants engineering selection authority within its stated limits. P14d is
eligible to start, but no autonomous loop or mutation/crossover implementation has begun.
