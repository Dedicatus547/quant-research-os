# P14 entry review

Review date: 2026-09-11

Decision: **GO for P14a-P14c implementation.** FR-01 and FR-02 satisfy the hard entry criteria.
This decision does not authorize P14d autonomous campaigns before P14a-P14c pass their own gates.

## Entry-gate evidence

| Gate | Result | Evidence |
|---|---|---|
| P13 qualified upstream | PASS | Approved v2 qualification remains frozen in `docs/p13-v2-freeze.md`; no P13 artifact was rewritten |
| FR-01 admitted DSL propagation | PASS | `SafeQlibExpressionSpec` can pass unchanged through proposal compilation and resolution. A non-return `field → delta → abs` DAG traverses PIT, SignalArtifact, Qlib backtest, G0-G10 Validation, and independent output roots. Family-external operators and fields absent from the qualified Qlib view fail closed. Qlib remains the only expression runtime |
| FR-02 immutable ResearchResult | PASS | The adapter consumes Qlib `SignalRecord`/`SigAnaRecord` outputs (`pred.pkl`, `label.pkl`, `ic.pkl`, `ric.pkl`, native metrics), binds resolved experiment, signal, expression, test split, label expression/horizon, research policy, snapshot/view/version/run, and source-file hashes, then publishes a content-addressed exact-file artifact. Verification rejects changed/missing files and inconsistent bindings; independent roots reproduce artifact and payload hashes |
| Validation integration | PASS | G3 accepts Rank IC/ICIR only from a verified, correctly bound ResearchResult and continues to fail closed when it is absent or corrupt |
| Full regression | PASS | Ruff PASS; Pyright PASS; `312 passed` with `TUSHARE_TOKEN` removed from the test environment |

## Frozen limits

- IC and Rank IC are calculated by Qlib `SigAnaRecord`; project code only normalizes and verifies
  Qlib-owned outputs. It does not implement an IC engine.
- Coverage, factor turnover, autocorrelation, and general portfolio analytics are not qualified as
  native ResearchResult metrics.
- The current market-data authority remains `SINGLE_SOURCE_NON_VINTAGE`; this review creates no
  vendor-vintage PIT claim and no profitability claim.
- Parameter stability supports a DAG with exactly one windowed node. Multi-window parameter
  families require an explicit named-dimension policy in P14 rather than an inferred mutation.
- Qlib pickle inputs are accepted only from the trusted runtime recorder boundary. Published
  authority is deterministic JSON plus hashes; downstream validation never opens the pickle files.

## P14 start boundary

P14 may now start with P14a (append-only Ledger persistence/rebuild and deterministic context
packs), followed by P14b deterministic frozen-family enumeration and P14c immutable campaign
selection. The multiple-testing method, assumptions, version, complete trial denominator, and
failure semantics must be frozen in P14c before any selection result has authority. P14d remains
blocked until P14a-P14c pass; sealed confirmation stays one-time and contamination-aware.

No manual filesystem or Store recovery action is required from the user for this entry decision.
