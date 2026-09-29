# P13 Qualified Event Feature progress

Status date: 2026-09-10

Status: **approved v2 real-event qualification completed; both tracks SUCCEEDED / PASS**.

See [the final v2 freeze record](p13-v2-freeze.md) for the authoritative hashes, attempt accounting,
reproducibility scope and limitations. The remaining sections preserve implementation history.

The user approved v2 on 2026-09-10. The runner now selects the formal v2 binding/policy in
`configs/research/`; v1 and the original proposals remain historical evidence. The approved Store
is locally materialized under `artifacts/evidence-stores/sha256-4fb04acc23c62b72d37df826560e2515a68cf7c7973ce1a0527a42a2b14fc306`.
Agent manifest `4ecafb334fee9ab91baf1ca72fbcf7953153a820a2cd2229166e2b9aed7c31bf` succeeded
with three MCP calls, zero retries, 113,481 input tokens and 1,440 output tokens. Its proposal
passed all six deterministic admission checks. That attempt's downstream execution was stopped
by dirty-checkout provenance (`REPRODUCIBILITY_MISMATCH`), and remains immutable failure evidence.
The subsequent offline replay completed both independent roots with matching principal hashes.
Earlier missing-v1-Store status below is historical.

Current regression: 305 tests passed, branch-inclusive coverage 85.13%; Ruff and Pyright passed.
This single, citation-location-assisted benchmark does not establish general extraction accuracy.

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

On 2026-09-10, a fresh bounded SSE acquisition also completed with one complete source item,
`SUCCEEDED` extraction, and `RESEARCH_ALLOWED` permission. Its immutable Store, Evidence, and
ExtractedText hashes were `4fb04acc23c62b72d37df826560e2515a68cf7c7973ce1a0527a42a2b14fc306`,
`e1e8591a6b3daa9678923c0fd4318fac991679587e1f434efc7da8ae29a1e800`, and
`3d78e4f9f4d05fd67eeca16f589be0179feef1dc131ab6e452b26080348ec3db`, respectively. They do not
match the human-frozen benchmark hashes above, so this acquisition remains a separate immutable
attempt under `/tmp` and is not substituted into the benchmark or Agent run.

The strict qualification entry point is now implemented at `scripts/p13_qualification.py`. It
verifies the checked-in `P13BenchmarkBinding`, native-Qlib bridge report, and the complete
hash-addressed Store before starting the Agent. The Agent receives only read-only `evidence_get`
and `evidence_cite`; schema, citation, admission, PIT, and downstream gates remain deterministic.
Failed tool calls and failed Codex runs are retained as bounded interaction digests and hashes,
without persisting stderr text or secrets.

The fresh Store was deliberately exercised as an explicit candidate input. The runner stopped
before Agent execution with `SOURCE_INCOMPLETE` because its Store hash did not equal the frozen
binding. A separate non-frozen Agent attempt reached the read-only MCP and retained its
`AgentRunManifest` and qualification bundle, but it is failure evidence only. Consequently no
human-frozen proposal has yet admitted this document, and it still produces no real EventFeature
or market conclusion.

The synthetic event-signal bridge independently proves EventFeature → weekly PIT witness →
`SignalRow/v2` → existing Qlib reference-backtest artifact compatibility. It uses a fixture and a
stubbed Qlib execution result at the final service boundary; the existing Qlib normalization,
Exchange, Simulator, and reconciliation paths retain their separate native-Qlib coverage.

The native bridge freeze then ran through
`scripts/p13_event_signal_feasibility.py` against a clean clone of implementation commit
`b466b2ca72e896c0654aeae6335ffb67c1393a49`. Two independent roots rebuilt the official Qlib view,
published an EventFeature and EventSignalArtifact, and executed the existing Qlib
`SimulatorExecutor`/`Exchange` path. The principal hashes were byte-exact:

```text
report hash             dbcb2866d3bc65c745172a1ca77f0cd88ced2f9d2ff22cf73381671612c04d60
snapshot                4ae0b2edfaeb3f57fdc0d9665eb4e1b382c83da41efb297bf3c9fe58506955fb
Qlib view               82b584bc5779d17e1e50f107ac56955b98445b23e9a86c28c3330a28d4b4d23d
EventFeature            5b0531f15e2df216afadf7cf3377932a3d085b6842582cf874ce092a54c19ddd
EventSignalArtifact     fded5bfcd2a58661ec2c261873e0cf19c42c5b2afcf020628a1d82e7c837edf0
BacktestArtifact        5ad0a5e98d6e709dfa03027dbc04efb0b193143c0c2effcca95942f8cbcb9b2c
reconciliation           8e76dad8e98c67940346afc2f58564d059a52c0e90165b0a61963b8817c79a37
signal rows              1
independent roots        byte-exact PASS
```

This is still synthetic Offline Engineering evidence. It does not qualify the real SSE document,
produce a real EventFeature, or create a market conclusion.

Verification on the dirty implementation worktree:

```text
Ruff                       PASS
Pyright                    PASS (0 errors)
full repository regression PASS (303/303; preceding implementation verification)
branch coverage gate       PASS (85.11% >= 85%; preceding implementation verification)
```

## Historical v1 formal status (superseded by approved v2)

```text
Offline Engineering implementation  SUCCEEDED / PASS (synthetic fixture)
Data-qualified event research        FAILED / NOT_EVALUATED
Data-qualified reason                Human-frozen binding exists, but its exact Store is not
                                     materialized in this workspace; the candidate Store is rejected
                                     by hash binding and no frozen Agent proposal exists
Agent-generated proposal             NOT YET RUN (non-frozen candidate attempt retained separately)
Agent token/cost evidence             NOT YET AVAILABLE for the frozen benchmark
Qlib SignalArtifact/backtest bridge  SUCCEEDED / PASS (native Qlib synthetic double-root)
formal P13 end-to-end freeze          NOT YET RUN (frozen Store and real Agent proposal remain)
```

`ACCEPT` is not used as a status. No P12 Evidence, Agent proposal, EventFeature, or EventStudy result
has modified a ValidationReport or Registry verdict.

## Historical exit checklist (completed for v2)

The candidate Store now has a verified local copy under `artifacts/evidence-stores/`.
A v2 policy and binding were prepared under `configs/research/proposals/`; those drafts are retained.
See [the approval comparison](reviews/p13-benchmark-v2-review.md) for verified citation equality,
source limitations, recovery scope, and the approved input change. The formal runner now
selects the approved v2 files in `configs/research/`. Runner changes bind failure manifests to the actual attempt and retain failed
usage; targeted qualification/Agent regression passes (8 tests).

1. Materialize or recover the exact human-frozen Evidence Store bound by
   `configs/research/p13_real_sse_benchmark_binding_v1.yaml`; a hash-mismatched candidate Store
   cannot be promoted.
2. Run the actual Codex extraction through the narrow JSON-RPC adapter and freeze citation accuracy,
   schema-valid rate, admission rate, PIT-valid rate, duplicate rate, usage, and transcript evidence.
3. Combine the immutable Agent-run evidence and the native bridge evidence into a compact
   non-licensed P13 qualification report, and only then decide whether P13 is complete. FR-01 and
   FR-02 remain separate P14 entry gates.
