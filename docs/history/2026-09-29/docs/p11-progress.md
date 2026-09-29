# P11 Quant Research MCP progress

Status: completed on 2026-09-08.

## Qualified boundary and explicit non-claims

P11 qualifies the typed Python application facades, their contracts, durable receipts/events, and
the deterministic downstream execution boundary. The retained E2E constructs a frozen proposal
chain in repository code and calls those facades directly. It does not qualify a production
stdio/JSON-RPC MCP transport, an Agent-generated proposal chain, real-world Evidence acquisition,
or a combined Agent-to-Data-qualified research run. The P10 mock stdio server proves the frozen
Harness capability separately; it is not the P11 service transport.

Before the first real Agent-assisted P13 vertical slice, a narrow transport adapter must receive
its own contract and negative-permission tests without expanding the P11 capability set. Agent
research quality also remains unmeasured until a frozen real-Evidence benchmark exists.

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
the typed proposal chain through both MCP boundaries and the compiler, executes the existing
native-Qlib release path twice, retrieves ValidationReport/Registry evidence, and creates a
non-authoritative reviewer `InterpretationProposal`.

The final run was executed from clean implementation commit
`06eda7290874e9331ec2b28ef61b34491268cc13`. Both independent pipelines produced byte-exact
authority hashes. The retained report is
[`../artifacts/feasibility/proposal-p11/report.json`](../artifacts/feasibility/proposal-p11/report.json),
with payload hash `4c920a513705dc0125f4f2d2e4886e6599cb15f91901c700b7ded4dba4c85baf`.

```text
Evidence                 74374eeea2b465c5eee58238ecb41395c48849ad003c5f20ee2930815db091fd
Compiled proposal        6ac37cb3314b3e6a8b9a883b0d894befc927b40c23dba9752d3ff272d6824c23
Authoring Spec           1ad9c45a5b48a289b9d5ece5a3fb2af494f52ee558514f0a9600c3c6dacbec16
Snapshot                 4ae0b2edfaeb3f57fdc0d9665eb4e1b382c83da41efb297bf3c9fe58506955fb
Qlib view                82b584bc5779d17e1e50f107ac56955b98445b23e9a86c28c3330a28d4b4d23d
Resolved Spec            59133a134feb6459a0bc801e68284d5c1525063bbc6f4a4e2940b10f6b68c538
PIT evidence             36aeeebcc9ac4f5c21e7ecf5445c5e867016dae7d9666d3a2b97ff24d5411016
SignalArtifact           e17397b909513f9918a661eea14600afed9450b4001ba61f3f21d982e298dbdb
BacktestArtifact         dcfebd6b47ad8be47521094d291e75d9aa439d5eb37bf24e99b6f5f8c696ce26
ValidationReport         c664558d165667f93706d41d4e6c4c48a7f9ff4a76b2db37a8b6eae68814c7d1
Registry manifest        d76a6c9b6ec27be87cf67cfa695ae43ff5c1ff46f76c635ff262addafa04cbda
Interpretation proposal  3b234532100eb67782c0ef6c074103a575ccf27e22e394dcdc66186595b0db5a
```

This is an `OFFLINE_ENGINEERING / STRUCTURED_FIXTURE` result with `data_qualified=false`. It does
not upgrade synthetic Evidence to live evidence, does not claim vendor-vintage PIT, and does not
use profitability as an engineering gate. P12 remains responsible for isolated real-world Evidence
acquisition; P14 remains responsible for Research Ledger search and the bounded autonomous loop.
Before P14, the existing admitted DSL must propagate through the proposal compiler beyond the
current field-to-return template, and factor-level Qlib results must gain an immutable adapter.
