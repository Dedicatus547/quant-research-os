# P14 progress

Status date: 2026-09-29

Current P14 status: P14a, P14b, P14c, P14d-A, P14d-B, and P14-DQ are complete within their distinct
engineering authority scopes. The current P14d-B qualification is report
`41a27c6fd2b5f0f522a1fcae13424b924b9cdc2fa4e8aa0df24ff12d79fadc71`; the current P14-DQ
engineering qualification is report
`f912cb0b376c981c94dae267cb0b16a4d2f1e0a52edcd36d08f938f92964d38a`. Both bind production commit
`e318dc450e5c02f1120da7644250767bf682b6f9`. The P14-DQ natural research outcome remains
`FAILED / NOT_EVALUATED / SOURCE_INCOMPLETE`, with 0 eligible candidates and no selection.
P14d-C remains `BLOCKED_UNIMPLEMENTED` by FR-03 `NO_GO`. The final RC authority matrix and freeze
evidence are in the [P14 RC v1 final freeze record](releases/p14-rc-v1-final.md); earlier blocked
attempts and their point-in-time verification remain preserved in the
[historical freeze](releases/p14-rc-v1.md) and its
[append-only verification supplement](releases/p14-rc-v1-verification.md).

## P14d-A deterministic orchestration and production execution

The v1 contract is frozen in `docs/p14d-autonomous-loop-contract.md`. The runtime-neutral
`AutonomousAgentDriver` accepts one bounded, hash-bound ContextPack request and returns exact
proposal bytes with an existing `AgentRunManifest`. `ScriptedAgentDriver` and `ReplayAgentDriver`
run without a model or network. Exchanges, campaign events, and loop reports use immutable
content-addressed publication; campaign budget and state remain projected from the existing
governor event chain.

The orchestrator resolves every admitted proposal from the verified P14b manifest and passes a
hash-bound execution request to `QuantosResearchExecutionAdapter`. The adapter composes the
existing snapshot/PIT evidence, Qlib-backed signal/backtest, Validation, ResearchResult, and P14c
services; Qlib owns model fitting, native records, and simulation. The integration test uses frozen
synthetic offline market data and real PIT/Qlib/Validation/ResearchResult services. It verifies
trial/result linkage, restart recovery across both event and Ledger boundaries, exact-retry reuse,
a refreshed ContextPack, Replay reuse, and the real `CampaignSelectionService` handoff. No
`OOSAccessed` or sealed confirmation execution is implemented, and FR-03 remains `NO_GO`.

Current P14d-A status:

- deterministic orchestration and production execution adapter: present;
- full P14d-A Definition of Done: **satisfied**;
- current full-suite gates: 514 passed, coverage 85.01%, Ruff PASS, Pyright 0 errors / 0 warnings;
- deterministic compute authority: adapter/policy-derived workload charge; wall-clock runtime is
  not part of any authority hash, budget projection, trial, or stopping decision;
- unknown execution exceptions fail closed through `AutonomousOrchestrationError`;
- P14d-B clean-commit double-root autonomous E2E: **QUALIFIED**;
- P14d-C live Agent runtime: blocked by FR-03 `NO_GO`.

## P14d-B qualified double-root autonomous campaign

The formal runner is `scripts/p14d_qualification.py`. It requires the exact clean Git root,
binds the implementation commit, `uv.lock`, runtime fingerprint, frozen
`docs/p14d-qualification-contract.md`, Qlib 0.9.7 source/version binding, committed synthetic
snapshot/view fixtures, autonomous policy hashes, execution bindings, and P14c selection plan
hashes. It runs `root-A` and `root-B` as independent output trees sharing only frozen fixtures,
source tree, and lockfile.

- implementation commit: `13d2b7acc44fe33c4f0c45d240fd5fd26e993845`
- qualification report: `13355dcb0c623c604ff5d0e4a5cd92d9aba59673d62bd76ffa9c839ee0754825`
- bundle path: `artifacts/qualification/p14d/sha256-13355dcb0c623c604ff5d0e4a5cd92d9aba59673d62bd76ffa9c839ee0754825`
- principal-hash summary: `baf7eedbb154d49ffba5f7a0d178f0eefe3379e89f5b0f50cafce27a2760a500`
- root principal summary: `0adf3fb227ff8b8eb4607d4c5442903ae868757e669eb1c32d7e70223ad204be`
- lockfile SHA-256: `0f5cd349fb32eed64a0cb907242f0ddd333f69efdc77461bdff90602e5bed7ca`
- runtime fingerprint: `66d954a1ff034d6ecb555885e12926e585543a4d71c92ea35bb5720465730321`
- frozen qualification contract: `7d57a7cc6ec78332956c7ea307772917ef20fb85d4d827c7280e1834c66c45f1`
- Qlib binding hash: `64097ae9c8404ccc79d43a40519e7177ff0ae226faf591a0a263a137d3ea67d3`
- fixture-set hash: `6f3f53d6d9586d52c529900f44231160c6d1400c57e8bb755a93af33af9991eb`
- negative cases: 27 per root, 54 total; restart cases: 3 per root, 6 total; Replay qualification:
  one per root with zero second Qlib executions and no authority promotion.

Both roots executed the real PIT/Qlib/Validation/ResearchResult path. The canonical cases were
`SELECTED` (P14c report `ee6caee9700bf764dd34bb8a397faf130b827ad28c7619256318832b18b98de5`,
`SelectionFrozen` hash `1e1e0bd4091feb5e0f68e90be9e550378685659eac484bb89b9a853ce4d920b9`,
AutonomousLoopReport `f04bbe053a44b775dbe3b1c79c7f7b050ea1b8645c9a73f4cf95a45295556687`),
`NO_SELECTION` (P14c report `fab2f859ae24075be9aa0041eff184061bcdddc25238e9ed365bf26cc55e4b46`),
and `FAILED_NOT_EVALUATED` (P14c report
`48a6bfe12e383798996cbf0763c8ece12a47089c9dc43ed2170658f29064254e`). Both roots produced
byte-identical principal hashes for candidate manifest, initial ContextPack, Agent requests and
proposals, execution identities, ResearchResult, ValidationReport, CampaignTrial, campaign event
chains, final Ledger snapshots, P14c reports, `SelectionFrozen` where present, and AutonomousLoop
reports. No `OOSAccessed` or sealed-confirmation research was executed.

The qualified bundle was independently re-verified with the runner's `--verify` command on the
same clean implementation commit. The qualification is `SYNTHETIC_OFFLINE_ENGINEERING_EVIDENCE`:
it establishes bounded deterministic autonomous control-plane reconstruction, not real market
alpha, profitability, live Agent qualification, vendor-vintage PIT, or sealed confirmation. P14d-C
remains unimplemented and blocked by FR-03.

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
P14c. The immutable report grants engineering selection authority within its stated limits. P14d's
bounded deterministic autonomous loop and its clean-commit double-root qualification are implemented
and qualified; P14d-C remains blocked by FR-03 `NO_GO`. No mutation, crossover, dynamic grammar or
family expansion has been implemented.

## P14-DQ v3 Data-qualified engineering qualification (accepted)

P14-DQ v3 completed a clean-commit independent double-root qualification from commit
`6573112a7ae46c2c6a5c29f85ff38a2450ca41ba`:

- qualification report: `f75455152dbd90827d8d1a015ecf1b0fa5ad749f53b67a06226b9d7039f2cb53`
  (`p14dq-qualification-report/v5`), status/verdict `SUCCEEDED / PASS`
- approved v3 engineering acceptance contract:
  `563b1c44ff8e3b87822902c1f70183de2ddd97b007550f2028990bb37f858e17`
- approved reproducibility environment amendment:
  `a63058df2df0a89c054965fb33046d99dc0851624bd231b45a2446709539dbce`
- frozen runtime environment: `PYTHONHASHSEED=0` with hash randomization disabled
- natural research outcome, recorded verbatim: P14c `FAILED / NOT_EVALUATED / SOURCE_INCOMPLETE`
  with `eligible_candidate_count = 0` and `selection_performed = false`
- independent roots: identical principal evidence, byte-exact across `root-A` and `root-B`;
  54 P14d negative cases, 24 P14-DQ negative cases and 6 restart cases all passed
- full bottom-up verifier (`verify`, not the bundle-only mode): `SUCCEEDED / PASS`
- independent final acceptance: Codex / GPT-6 Sol, High, fresh context — `APPROVE`

The acceptance record with every exact binding, the authority corrections and the preserved
history is `docs/reviews/p14-dq-v3-qualification-acceptance.md`. The grant is limited to bounded
deterministic autonomous Data-qualified engineering qualification for that exact frozen
snapshot/view lineage, clean implementation commit and frozen runtime environment. It grants no
alpha, profitability, investment-suitability, live-Agent, FR-03 or sealed-confirmation authority,
and it does not claim that the reused Qlib engine is hash-order independent. The previously
published `sha256-10cf6e09…` bundle stays unaccepted and every failed attempt stays immutable.

At the time of this acceptance record, the next task was recorded as not started: **P14 Release
Candidate freeze**.

## Historical current-code P14d-B compatibility qualification and RC stabilization (2026-09-28)

The P14d-B runner was requalified after auditing the production changes from its historical
implementation commit to the accepted P14-DQ implementation. Shared autonomous, Qlib Workflow,
ResearchResult, and qualification-contract code had changed, so the original report did not qualify
the current implementation. The current runner commit is
`908ee826cdd88cd9a46a55d4462b99e32ec35d31`; its production source files are byte-identical to the
P14-DQ production baseline `6573112a7ae46c2c6a5c29f85ff38a2450ca41ba`.

- current-code report: `35465fcf21cea713ceba95073f3b4972dcd5a5b0a42aeee0d82442a04b118b35`
- principal-hash summary: `b8a205c9a45ac490be4c8549d6fe373832f69faed11c344cd1a985785b9b230a`
- qualification contract hash: `eaa9e35b5141bc75648945718455e7b88b8ad3c2dd34df0d1f937df99e099136`
- runtime fingerprint: `66d954a1ff034d6ecb555885e12926e585543a4d71c92ea35bb5720465730321`
- roots: `root-A` and `root-B` principal hashes byte-exact; report `SUCCEEDED / PASS`
- canonical cases: `SELECTED` → `SelectionFrozen` → `READY_FOR_SEALED_CONFIRMATION`,
  `NO_SELECTION`, and `FAILED_NOT_EVALUATED`
- fault coverage: 54 negative cases and 6 restart cases; Replay reused the stored exchange and
  execution receipt without a second Qlib execution
- bottom-up bundle verifier: `SUCCEEDED / PASS`

The runner now isolates Qlib-sensitive synthetic scenarios and runs the final self-verifier in a
fresh interpreter. This repairs process-state contamination in the qualification harness; the
P14d-B contract and semantic gates are unchanged. The original P14d-B report, failed stabilization
attempts, and the accepted P14-DQ report remain retained as separate immutable evidence. This
qualification grants bounded synthetic Offline Engineering authority only.

## P14 RC Qlib execution race resolution and current qualifications

The full-suite-order-dependent P14-DQ failure was diagnosed as a Qlib asynchronous metric logging
race. `LGBModel.fit` queued the `l2.valid` metric, then MLflow `FileStore` read its metric file while
`SignalRecord.generate()` logged an artifact. That read could observe an empty file and raise
`ValueError("Metric 'l2.valid' is malformed. No data found.")`. The exact lifecycle correction in
`src/quantos/research/qlib/workflow.py` drains the metric queue after fitting and before artifact
generation. It preserves fail-closed execution classification and all frozen research and authority
semantics. The regression test is in `tests/unit/test_qlib_workflow.py`.

Production baseline `e318dc450e5c02f1120da7644250767bf682b6f9` passed the target x10, the ordered
prefix reproducer, ordinary and `PYTHONHASHSEED=0` full suites (699 passed each), and 85.01% coverage.
Ruff format/check, Pyright, `git diff --check`, retained P14c verification, and the new P14d-B and
P14-DQ full artifact verifiers passed. The current reports are P14d-B
`41a27c6fd2b5f0f522a1fcae13424b924b9cdc2fa4e8aa0df24ff12d79fadc71` and P14-DQ
`f912cb0b376c981c94dae267cb0b16a4d2f1e0a52edcd36d08f938f92964d38a`. P14-DQ's natural research
outcome remains `FAILED / NOT_EVALUATED / SOURCE_INCOMPLETE`; its engineering qualification is
`SUCCEEDED / PASS` under the approved frozen exception. Full provenance, root equality, resource
observations, qualification binding, and the authority matrix are recorded in the
[final P14 RC freeze](releases/p14-rc-v1-final.md).
