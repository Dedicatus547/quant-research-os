# P11 Quant Research MCP progress

Status: in progress from 2026-09-07. The clean-commit offline E2E is the remaining exit gate.

The first implementation slice added the three repository-level logical-role Skills
(`quant-researcher`, `quant-formalizer`, and `quant-reviewer`), a deterministic proposal-chain
compiler, and the typed proposal-ingress application boundary.

The compiler verifies the complete Observation → Hypothesis → Factor → Experiment lineage,
admitted AgentRun hashes, frozen ResearchFamily and Campaign hashes, structured Evidence and
citation inputs, dataset/view/feature hashes, campaign segment dates, registered field sources,
and the current minimal safe field-to-return template. Its output is the existing
`ExperimentAuthoringSpec`; it has no status or verdict and performs no execution.

The proposal ingress exposes only the three `proposal.submit_*` capabilities already frozen in
P9. Each request is resource-bounded and binds an idempotency key, AgentRun, Campaign, Budget, all
input hashes, and one typed proposal. Successful submissions publish content-addressed proposal
bytes plus an immutable receipt and audit event. Identical retries return the same receipt;
conflicting reuse fails with `DUPLICATE_ID_CONFLICT`. Authority fields, secrets, shell/path
capabilities, unbudgeted requests, and mismatched proposal kinds fail closed.

The second implementation slice maps `dataset.describe`, `dataset.fields`, `experiment.resolve`,
`experiment.request_execution`, `job.get`, `validation.get`, `registry.get`, and `registry.search`
to typed application contracts. Requests cannot carry filesystem paths or authority fields. Writes
bind idempotency, AgentRun, Campaign, Budget, and complete input hashes. The durable bounded job
queue uses append-only content-addressed events and defines query, cancellation, timeout, duplicate,
restart, and `FAILED / NOT_EVALUATED` behavior. Its trusted executor is injected and must call the
existing Qlib/Validation/Registry pipeline; the MCP layer contains no backtest or accounting engine.

`scripts/proposal_feasibility.py` stages one frozen structured synthetic `EvidenceRecord`, routes
the typed proposal chain through both MCP boundaries and the compiler, and is prepared to execute
the existing native-Qlib release path twice before retrieving ValidationReport/Registry evidence
and creating a non-authoritative reviewer `InterpretationProposal`. The remaining P11 gate is a
clean-commit execution of this runner, retention of its immutable report, and confirmation of
byte-exact resolved Spec, PIT, signal, backtest, ValidationReport, and Registry hashes.
