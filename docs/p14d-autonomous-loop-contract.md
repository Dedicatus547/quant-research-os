# P14d-A autonomous loop contract v1

Status: **frozen for P14d-A implementation**

Authority: runtime-independent deterministic orchestration only. This contract does not qualify
an Agent runtime, a live-market result, or sealed confirmation.

## Scope

P14d v1 operates only on a pre-frozen finite `ResearchFamilySpec` and its verified P14b
`CandidateEnumerationManifest`. Candidate identities and ASTs are fixed before activation.
The Agent may reference one manifest candidate per run and may attach a stop request; the
deterministic core resolves the reference and decides admission, execution, accounting, and stop.

The loop reuses the existing campaign governor and event chain, P14a Research Ledger and
`ResearchContextPack`, P14b enumeration verifier, existing deterministic execution services,
and P14c `CampaignSelectionService`. It does not create a second campaign state machine.

P14d v1 includes:

- a runtime-neutral AgentDriver port and bounded request/response contracts;
- deterministic candidate admission against the complete frozen manifest;
- campaign budget and trial accounting through existing `CampaignTrial` events;
- deterministic stopping and explicit P14c selection handoff;
- immutable Agent exchange replay and contamination-aware ledger access.

P14d v1 excludes mutation, crossover, dynamic grammar or family expansion, arbitrary code,
model search, live Agent runtime integration, live market conclusions, and sealed confirmation
execution. FR-03 remains `NO_GO`; this loop has no OpenAI SDK, network, model, CLI fallback, or
runtime-specific dependency.

## Authority boundary

```text
AgentDriver
  receives one verified immutable ContextPack binding and bounded campaign/budget metadata
  returns an AgentRun manifest plus raw proposal bytes
        ↓
deterministic admission and frozen-manifest resolution
        ↓
CampaignTrial + existing deterministic execution services
        ↓
Research Ledger update and a new snapshot/ContextPack
        ↓
existing CampaignSelectionService
```

Agent output is always a proposal. `extra=forbid` response schemas carry no verdict, campaign
state, budget mutation, artifact path/root, secret, or sealed-access field. A proposal's optional
`request_stop` is evidence of intent only. It cannot close the campaign or select a candidate.

The request exposes only the immutable ContextPack and its hashes, campaign/family/budget/manifest
hashes, the canonical JSON proposal schema and its hash, the deterministic run ordinal, and
remaining budget values. The schema hash is also included in the bound `AgentRunSpec` inputs.
It carries no path or mutable alias. It never contains the full Ledger or artifact tree.

Every returned AgentRun manifest must bind the exact request's `AgentRunSpec`, ContextPack,
Ledger snapshot, campaign, and policy hashes. The proposal bytes and their digest must match the
manifest output binding. Scripted output is fixture input, never research evidence. Replay verifies
the immutable exchange from its contents and request binding; replay neither invokes a model nor
raises authority.

## Candidate admission and duplicate rules

The accepted proposal identifies one candidate and repeats its canonical parameter tuple,
expression, exact-expression fingerprint, and structural fingerprint. The orchestrator compares
all fields with the uniquely matching manifest item. Unknown candidates, altered parameters,
altered ASTs/fingerprints, unapproved operators, manifest drift, and unbound runs fail closed.
There is no route that inserts a candidate into the active family.

Every successfully returned AgentRun is associated with exactly one candidate attempt. A stop
request therefore accompanies a candidate reference and is accounted after that candidate's
deterministic disposition. Invalid schema can be recorded as `SCHEMA_INVALID` only when a bounded
raw proposal contains a valid in-manifest candidate reference; an unresolvable/out-of-manifest
identity is an integrity rejection and is never assigned a fabricated candidate.

Once a candidate has a terminal campaign trial, another proposal for that same candidate records
`DUPLICATE_CANDIDATE`, consumes one AgentRun and one trial, and performs no research execution.
An exact-expression duplicate candidate is also suppressed after any member of its exact duplicate
group has a terminal trial. Structural duplicates remain separate P14b hypotheses, consistent
with P14c's denominator, and may each receive one actual execution. Rejected, failed, PIT-rejected,
and soft-rejected trials are terminal; there is no automatic retry loop.

## Budget and accounting

`ResearchBudgetSpec` is the authority. Before another driver invocation, the orchestrator projects
the full existing event chain and refuses any request after a relevant limit is reached. At least
`max_trials`, `max_agent_runs`, `max_distinct_candidates`, `max_executions`,
`max_validation_rounds`, and `max_compute_seconds` are enforced by the existing governor. Every
successful AgentRun returned for admission produces exactly one `CampaignTrial`; failed driver
transport/integrity does not become research evidence and aborts the loop.

`max_compute_seconds` consumes a **deterministic compute charge**, not observed wall-clock runtime.
The charge is derived from the frozen execution policy, request, candidate authoring, and validation
workload shape; the same frozen request always produces the same charge. Observed wall-clock
runtime may be retained only as outer telemetry/diagnostics and must never enter a
`CampaignTrial`, campaign event hash, budget projection, stopping decision, `AutonomousLoopReport`,
or any principal deterministic hash domain. `AutonomousExecutionResult.compute_seconds` is therefore
a policy workload unit, not a duration measurement. Unknown execution exceptions fail closed as
`AutonomousOrchestrationError`; only typed known PIT/data/execution failures become deterministic
trial outcomes.

Each candidate trial outcome remains one of the existing `TrialOutcome` values. Schema-invalid
candidate proposals, PIT rejection, execution failure, hard/soft rejection, and duplicate attempts
remain explicit trials. Only deterministic execution outcomes and verified artifact bindings may
populate result evidence. The Agent cannot supply outcome, runtime, or evidence authority.

## Stopping rules

After each fully accounted trial, evaluate these conditions in order:

1. every manifest candidate has a terminal trial → `ALL_CANDIDATES_TERMINAL`;
2. any other existing campaign budget limit is exhausted → `BUDGET_EXHAUSTED`;
3. no candidate remains eligible under the frozen family and distinct-candidate budget →
   `NO_REMAINING_ELIGIBLE_CANDIDATES`;
4. Agent requested stop and the frozen `BUDGET_EXHAUSTED_OR_MANUAL_CLOSE` policy permits it →
   `MANUAL_CLOSE_REQUEST_ACCEPTED_BY_POLICY`;
5. otherwise build the next ContextPack from the current Ledger snapshot and continue.

The stop reason is a derived deterministic view over the campaign spec, budget, manifest, and event
chain. `CampaignTrialRecorded`, `SelectionPlanFrozen`, `SelectionFrozen`, `OOSAccessed`, and
`CampaignClosed` remain the campaign authority events. Agent stop intent alone never writes an
event or ends a run.

## Context and Ledger updates

Each request is built from a freshly verified `ResearchLedgerSnapshot`, frozen search policy,
campaign-bound access scope, search request/result, and bounded `ResearchContextBudgetPolicy`.
`ResearchLedgerService.build_context_pack` must reproduce the pack. A stale or sealed-object scope
that does not authorize every contamination hash fails closed. The next request must bind the new
snapshot after the preceding trial/proposal has been appended.

The proposal is appended, where schema-valid, with `AGENT_PROPOSAL` authority and its AgentRun
hash. Campaign trials and their deterministic evidence bindings are appended as deterministic
evidence. Agent rationale remains proposal content; it can never become a `ResearchResult`,
`ValidationReport`, deterministic verdict, or `CampaignSelectionReport`.

After sealed data has been accessed, no autonomous request may use a sealed Ledger object. Any
descendant interpretation/campaign must preserve the existing governor's contamination hashes.
P14d-A expresses and tests this boundary; it does not perform confirmation research.

## P14c handoff and states

The orchestrator accepts only an activated chain with exactly one matching P14c plan frozen
immediately after activation and before trials. Once stopping is true, it does not call the
AgentDriver again. It delegates report construction, publication, verification, and any
`SelectionFrozen` event to the existing `CampaignSelectionService`.

- verified `SELECTED` may return `READY_FOR_SEALED_CONFIRMATION` only after the existing service
  verifies the immutable report and freezes the selected candidate;
- `NO_SELECTION` closes the campaign through the governor and grants no sealed authority;
- `FAILED / NOT_EVALUATED` closes the campaign through the governor and grants no sealed authority.

The public orchestration status is a derived report status (`READY`, `RUNNING`, `STOPPED`,
`SELECTION_READY`, `SELECTION_COMPLETE`, `FAILED`), never a competing campaign projection. The
campaign event chain remains authoritative. This phase does not call `OOSAccessed` or consume the
one-time confirmation boundary.

## Idempotency, replay, and failure semantics

The deterministic invocation key binds campaign, manifest, current Ledger snapshot, ContextPack,
AgentRun ordinal, and relevant policy hashes. An exact retry reuses the same request and exchange.
The immutable exchange is created if absent; the same key with different bytes is a hard conflict.
The AgentRun/proposal exchange is published before trial append. If a process stops between those
operations, restart replays the same exchange and the governor's trial idempotency key prevents a
second trial. A campaign/run ordinal with an existing exchange cannot be rebound to a newer Ledger
snapshot or changed policy after a crash; it fails closed instead of starting another AgentRun.
Conflicting input under an existing key fails closed.

Corrupt event chains, missing campaign/family/budget/manifest, stale Ledger/ContextPack, policy or
manifest mismatch, proposal hash mismatch, invalid AgentRun binding, replay tampering, and an
out-of-manifest candidate are orchestration integrity failures. They stop the loop. Expected
research outcomes (schema reject for a resolved candidate, PIT reject, execution failure, and
soft reject) are recorded and can continue only if the deterministic stopping policy permits.

## Report and limitations

The immutable `AutonomousLoopReport` binds campaign, family, budget, manifest, initial/final Ledger
snapshot hashes, AgentRun/request/context/proposal hashes, trial event hashes, counts, stopping
reason, projected budget usage, P14c report/event hashes when present, final derived status, and
limitations. It is orchestration evidence only. It grants no independent selection authority,
sealed-access authority, historical vendor-vintage PIT claim, or real-market conclusion.

Implementation status: P14d-A's deterministic execution port is wired through
`QuantosResearchExecutionAdapter` to the existing snapshot/PIT evidence builder, Qlib-backed
signal and backtest services, Validation service, immutable ResearchResult builder/verifier, Ledger,
and `CampaignSelectionService`. The adapter verifies the frozen manifest candidate, execution
identity, snapshot/dataset/view, validation segment, policies, and result artifact chain. Offline
integration evidence uses a frozen synthetic dataset but real PIT, native Qlib Workflow and
Simulator, Validation, ResearchResult, campaign accounting, Ledger, and P14c services. It covers
exact retry, duplicate suppression, replay reuse, result/event and event/Ledger crash recovery, and
conflicting retries. P14d-A meets its Definition of Done.

P14d-B is **QUALIFIED** at clean implementation commit
`13d2b7acc44fe33c4f0c45d240fd5fd26e993845`. The immutable qualification report is
`13355dcb0c623c604ff5d0e4a5cd92d9aba59673d62bd76ffa9c839ee0754825`; both independent roots
executed the real PIT/Qlib/Validation/ResearchResult path, produced byte-identical principal
hashes, and passed the canonical `SELECTED`, `NO_SELECTION`, and `FAILED_NOT_EVALUATED` cases,
27 negative cases per root, three restart cases per root, and replay reuse. The bundle was
independently re-verified with the runner's `--verify` command. This grants bounded synthetic
offline autonomous engineering authority only. P14d-C live runtime qualification remains blocked
by FR-03 `NO_GO` and is not implemented. This work does not call `OOSAccessed`, implement sealed
confirmation, claim vendor-vintage PIT, or add a live model dependency.
