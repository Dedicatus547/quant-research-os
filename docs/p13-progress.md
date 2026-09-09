# P13 Qualified Event Feature progress

Status date: 2026-09-09

Status: **real benchmark human-frozen; formal P13 execution freeze not yet claimed**.

The first P13 engineering slice now fails closed from an extraction proposal through deterministic
admission, strict-next-open-session resolution, immutable `EventFeatureArtifact` publication, and a
bounded event study. It deliberately uses a synthetic share-repurchase fixture. It does not turn the
three retained P12 SZSE documents into research inputs: their permission is still `UNKNOWN`, and none
of their announcement titles is a share-repurchase case.

## Implemented boundary

- a frozen, hash-bound share-repurchase benchmark policy with exact Evidence, extracted-text,
  entity, event-time, attribute, citation-range, and cited-text-hash expectations;
- deterministic admission checks for source lineage, exact cited text, research permission,
  availability, and exact benchmark semantics;
- `EventFeatureArtifact/v2`, now binding the immutable market snapshot and every trading-session
  resolution hash in addition to Evidence, proposal, admission, policies, code, and runtime;
- snapshot-backed entity and exchange resolution plus a bounded `STRICT_NEXT_OPEN_SESSION` policy;
- atomic content-addressed publication, idempotent rebuild, exact-file verification, and tamper
  rejection for EventFeature artifacts;
- deterministic event-study primitives limited to the admitted `event_count`,
  `mean_abnormal_return`, and `mean_car` metrics; calculations use canonical Parquet closes and
  adjustment factors and are explicitly not a portfolio or backtest engine;
- immutable EventStudy artifacts binding feature, snapshot, spec, code, runtime, rows, and summary,
  with independent-output-root hash equality and summary recomputation;
- a narrow newline-delimited JSON-RPC adapter over the existing P11 typed facades, with a stable tool
  schema hash, P8 resource budgets, allowlisted methods, and payload-free transcript hashes.
- a hash-bound `EventSignalEvidence` and `EventSignalArtifact` bridge that aligns an admitted event
  to the first eligible weekly decision, emits the existing `SignalRow/v2` Arrow schema, checks
  same-session tradability, and delegates execution unchanged to `QlibBacktestService`;
- `ResolvedEventExperimentSpec` and an event-signal alignment policy that bind the EventFeature,
  snapshot, Qlib view/spec/version, schedule witness, cost/backtest policies, code, and lockfile.

## Current evidence

The checked-in benchmark and resolver policies are:

- `configs/research/p13_synthetic_evidence_v1.yaml`
- `configs/research/p13_share_repurchase_benchmark_v1.yaml`
- `configs/research/p13_real_sse_share_repurchase_benchmark_v1.yaml`
- `configs/research/p13_trading_session_resolver_v1.yaml`
- `configs/research/p13_event_signal_alignment_v1.yaml`

The real SSE benchmark was explicitly human-approved with an empty v1 attribute set. Its policy
hash is `dcae0005fe5a0ea8323629b1336cb2c94d5e915c7191d94139c3811ad2ee78a6`; its sole case
hash is `4f6fc3171da7ceb18ddca0d0efdb6312b3e9f2dded35d558a53cacf04102cb39`. The benchmark
binds EvidenceRecord `a9bded47...16aee`, ExtractedTextArtifact `36850b39...8d46`, entity
`600010.SH`, conservative publication time, two exact citation ranges, and `attributes: []`.

`scripts/event_feature_feasibility.py` is the clean-worktree freeze runner. It executes two complete
synthetic roots and emits a compact `P13QualificationReport`; it intentionally reports zero Agent
tokens and `NO_AGENT_GENERATED_PROPOSAL` until the real Codex benchmark exists.

The synthetic vertical slice resolves a 2024-01-02 after-close announcement for `600000.SH` to the
strict next open session, 2024-01-03, and evaluates the 2024-01-03 to 2024-01-04 window against
`000300.SH`. Two independent EventFeature roots and two independent EventStudy roots produce equal
content hashes. The values are engineering fixtures, not market findings.

A first bounded real-source smoke used
`configs/evidence/p13_sse_share_repurchase_probe.yaml`. The official SSE query returned a complete
1/1 count witness for the 2025-08-05 `600010.SH` share-repurchase-progress announcement. Publication
retained a research-permitted EvidenceRecord, but the document response was a gzip-compressed HTTP
200 anti-bot HTML page rather than announcement text. Deterministic extraction therefore failed and
no citation, proposal, admission, EventFeature, or market result was created. This failed attempt
remains part of the evidence history.

```text
real staging hash     b16454877f74105e0138584433f647dff3ff2ac3c55d4a6f7701adc34330f524
real Evidence Store   11680f8e27cc43ab3e11bc87e20f0913fc2488e6f09df3759a19cccd9c9683ca
source completeness   1/1 PASS
research permission   RESEARCH_ALLOWED
text extraction       FAILED / EVIDENCE_TEXT_EXTRACTION_FAILED
authority location    /tmp only; bounded smoke, not a committed formal freeze
```

The follow-up changed the frozen SSE document origin to the SSE-owned HTTPS mirror's explicit
`/site/cht/www.sse.com.cn` path. It does not accept the mirror's HTTP redirect form. Repeating the
same bounded query acquired the official three-page PDF and the offline publisher extracted 1,378
characters with `pypdf`.

```text
mirror staging hash   ea5fc26cb4289d76fc517062df551c905193dead8a3df1eb6aa337918e19e071
mirror Evidence Store be484479b61c7096ffd58e99fa31168dc06a7fc7ae4597a2d455cda2c41250b1
source completeness   1/1 PASS
research permission   RESEARCH_ALLOWED
text extraction       SUCCEEDED / 3 pages / 1,378 characters
authority location    /tmp only; bounded smoke, not a committed formal freeze
```

This qualifies the acquisition and deterministic extraction path only. No human-frozen expected
extraction or actual Agent proposal has yet admitted this document, so it still produces no real
EventFeature or market conclusion.

The synthetic event-signal bridge independently proves EventFeature → weekly PIT witness →
`SignalRow/v2` → existing Qlib reference-backtest artifact compatibility. It uses a fixture and a
stubbed Qlib execution result at the final service boundary; the existing Qlib normalization,
Exchange, Simulator, and reconciliation paths retain their separate native-Qlib coverage. A
clean-commit native-Qlib double-root run of the event bridge is still required for formal P13 exit.

Verification on the dirty implementation worktree:

```text
Ruff                       PASS
Pyright                    PASS (0 errors)
full repository regression PASS (292/292)
branch coverage gate       PASS (85.08% >= 85%)
```

## Formal status

```text
Offline Engineering implementation  SUCCEEDED / PASS (synthetic fixture)
Data-qualified event research        FAILED / NOT_EVALUATED
Data-qualified reason                Human-frozen real benchmark exists, but no actual Agent
                                     proposal/native-Qlib freeze run exists
Agent-generated proposal             NOT YET RUN
Agent token/cost evidence             NOT YET AVAILABLE
Qlib SignalArtifact/backtest bridge  IMPLEMENTED on synthetic fixtures; native clean freeze pending
formal clean-commit freeze            NOT YET RUN
```

`ACCEPT` is not used as a status. No P12 Evidence, Agent proposal, EventFeature, or EventStudy result
has modified a ValidationReport or Registry verdict.

## Remaining P13 exit work

1. Run the actual Codex extraction through the narrow JSON-RPC adapter and freeze citation accuracy,
   schema-valid rate, admission rate, PIT-valid rate, duplicate rate, usage, and transcript evidence.
2. Run the admitted event-signal bridge through native Qlib in two clean-commit output roots,
   publish a compact non-licensed P13 qualification report, and
   only then decide whether P13 is complete. FR-01 and FR-02 remain separate P14 entry gates.
