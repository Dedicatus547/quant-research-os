# P9 Research Semantic Contracts

Status: complete on 2026-09-07.

P9 freezes the harness-independent boundary for Agent-assisted research. It does not add an Agent
runtime, MCP server, live evidence collector, autonomous loop, or a second execution engine. Agent
content remains a proposal; deterministic artifacts and `ValidationReport` remain authoritative.

## Frozen contract groups

| Group | Contracts | Authority boundary |
|---|---|---|
| Source evidence | `EvidenceRecord`, `ExtractedTextArtifact`, `EvidenceCitation` | Publisher bytes and retrieval metadata are immutable source evidence; parsed text is derived evidence with parser, code, and runtime provenance |
| Agent proposals | `ObservationProposal`, `HypothesisProposal`, `FactorProposalSpec`, `ExperimentProposalSpec`, `EvidenceExtractionProposal`, `InterpretationProposal` | No proposal has lifecycle or validation status, and no proposal can carry or alter a verdict |
| Feature admission | `EventFeatureAdmissionRecord`, `EventFeatureArtifact` | Only a frozen deterministic benchmark or recorded human review can admit a cited extraction; unknown availability and non-permitted evidence fail closed |
| Campaign governance | `ResearchFamilySpec`, `ResearchBudgetSpec`, `ResearchCampaignSpec`, immutable campaign events and projections | The finite family, inputs, periods, budgets, testing policy, stopping rule, OOS access, and contamination are hash-bound before execution |
| Agent provenance | `AgentCapabilityPolicy`, `AgentRunSpec`, `AgentRunManifest` | Capabilities and resource bounds are explicit; manifests bind model/configuration, instructions, tools, inputs, outputs, transcript, usage, failures, and limitations without claiming LLM reproducibility |
| Research ledger | `ResearchLedgerEvent`, `ResearchLedgerSnapshot` | Source assertions, Agent proposals, human-review statements, deterministic experiment evidence, and deterministic verdicts are separate authority classes |

All contracts inherit strict immutable canonical serialization from `CanonicalContract` and remain
free of Tushare, Qlib, Agent-harness, and LLM-SDK dependencies. Mutable lifecycle is represented by
append-only events and reconstructable projections, never by modifying proposal payloads.

Evidence records distinguish `published_at`, `fetched_at`, `observed_at`, and policy-derived
`available_at`; every timestamp is timezone-aware. Revisions bind their predecessor rather than
overwriting it. `UNKNOWN` availability cannot claim an availability time and is a PIT hard reject.
Extraction citations bind the exact Evidence and extracted-text hashes plus page and/or character
ranges. The admission builder rechecks those ranges, lineage, research-use permission, entity set,
event label/time, attributes, and availability before creating a qualified event feature.

## Campaign and OOS state machine

```text
DRAFT --CampaignActivated--> ACTIVE
ACTIVE --CampaignTrialRecorded--> ACTIVE
ACTIVE --CampaignClosed--> CLOSED
ACTIVE --OOSAccessed (exactly once)--> CLOSED + contaminated
```

Every schema-invalid proposal, PIT rejection, execution failure, soft/hard rejection, pass, and
duplicate candidate is a `CampaignTrial` and consumes the applicable frozen budget. An idempotent
retry returns its existing event; it does not create a second attempt. Conflicting reuse of an
idempotency key fails closed. A sealed-confirmation trial is accepted only through `OOSAccessed`,
which closes the campaign and adds its hash to contamination. Interpretations and descendants must
inherit that contamination. A new confirmation additionally requires a new snapshot and a future,
previously unexposed sealed window.

The P9 multiple-testing policy records only `PREFROZEN_FINITE_FAMILY`. It proves that the search
space is bounded and predeclared; it does not claim that selection bias has been statistically
corrected. Statistical correction remains a P14 policy decision.

## Safe Qlib DSL v2 admission

P9 admits only five additions. Translation uses the locked official Qlib 0.9.7 expression provider.

| QuantOS operator | Qlib expression | Shape | PIT source observations | Locked value semantics |
|---|---|---|---|---|
| `abs` | `Abs(x)` | unary, no window | same as input | NumPy absolute value; NaN and infinity remain non-finite |
| `delta` | `Delta(x,N)` | unary, positive integer window | input requirement + `N` | current value minus value shifted by `N`; missing/non-finite arithmetic follows official Qlib/pandas behavior |
| `rolling_sum` | `Sum(x,N)` | unary, positive integer window | input requirement + `N - 1` | official rolling sum |
| `rolling_min` | `Min(x,N)` | unary, positive integer window | input requirement + `N - 1` | official rolling minimum |
| `rolling_max` | `Max(x,N)` | unary, positive integer window | input requirement + `N - 1` | official rolling maximum |

Official Qlib rolling reductions use `min_periods=1` and their locked pandas null/non-finite
behavior. QuantOS is deliberately stricter at the PIT boundary: it requires the complete source
window before execution. Every operator also requires an explicit versioned delay; output
availability is the maximum input availability plus that delay. At SignalArtifact publication,
any missing or non-finite final score is retained as invalid rather than treated as a tradable
value. These operators have no denominator, so zero-denominator behavior is not applicable.

Golden tests lock official syntax and representative NaN/infinity values. A single v2 DAG using all
five operators passes the canonical PIT evidence, SignalArtifact, independent-output-root hash, and
artifact-verification chain. The v1 schema rejects all v2-only operators.

`correlation`, `zscore`, `cross_section_rank`, `clip`, and `log` remain outside the public enum.
Industry and size neutralization also remain excluded. They require separate, operator-specific
semantics, inputs, PIT, golden, and reproducibility evidence before a future schema can admit them.

## Exit evidence and remaining boundary

P9 tests cover canonical proposal/source distinctions, exact evidence and admission lineage,
unknown-availability rejection, finite-family membership, complete trial accounting, budget
enforcement, event-chain integrity, one-time sealed access, contamination propagation, official
Qlib semantics, full PIT/Signal reproducibility, and exclusion of unqualified operators. The full
P0-P8 regression remains green.

At the P9 freeze, P10 was the next stage. P10 and P11 are now complete; P12 is the current entry.
Neither later result widens these contracts, authority levels, capabilities, or deterministic
validation rules without an explicit contract revision. P11 qualified typed Python facades with a
code-defined structured fixture, not a production MCP transport or Agent-generated research chain.
