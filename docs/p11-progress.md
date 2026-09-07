# P11 Quant Research MCP progress

Status: in progress from 2026-09-07. P11 exit conditions are not yet satisfied.

The first implementation slice adds the three repository-level logical-role Skills
(`quant-researcher`, `quant-formalizer`, and `quant-reviewer`), a deterministic proposal-chain
compiler, and the typed proposal-ingress application boundary.

The compiler verifies the complete Observation → Hypothesis → Factor → Experiment lineage,
admitted AgentRun hashes, frozen ResearchFamily and Campaign hashes, structured Evidence inputs,
dataset/view/feature hashes, campaign segment dates, registered field sources, and the current
minimal safe field-to-return template. Its output is the existing `ExperimentAuthoringSpec`; it has
no status or verdict and performs no execution.

The proposal ingress exposes only the three `proposal.submit_*` capabilities already frozen in
P9. Each request is resource-bounded and binds an idempotency key, AgentRun, Campaign, Budget, all
input hashes, and one typed proposal. Successful submissions publish content-addressed proposal
bytes plus an immutable receipt. Reusing a key with identical bytes returns the receipt; conflicting
reuse fails with `DUPLICATE_ID_CONFLICT`. Authority fields, secrets, shell/path capabilities,
unbudgeted requests, and mismatched proposal kinds fail closed.

Remaining P11 work is intentionally explicit: implement the remaining read/resolve/execution/job/
validation/registry MCP adapters over existing application services, then run the frozen structured
synthetic proposal through the existing Qlib, ValidationReport, Registry, and reviewer-explanation
path twice with identical deterministic evidence hashes. P11 must not be marked complete until
those E2E, permission, failure, timeout/cancellation, and exact-service-mapping gates pass.
