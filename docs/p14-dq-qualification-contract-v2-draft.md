# P14-DQ data-qualified qualification contract v2 — draft amendment

Status: **DRAFT — independent Sol High approval required before implementation**

This is a proposed amendment to the v1 contract at `37880e8` (file SHA-256
`2e8dab7816f49c45e8728892288673d8565947a76d7202d14681f830f2957069`).
All v1 provisions remain binding except the exact clauses superseded below. The
failure evidence and rationale are in `docs/reviews/p14-dq-contract-reopening.md`.
This draft is not an authority input to the current P14-DQ runner and grants no PASS.
Specifically, this draft replaces v1 §3's use of the P7 policy bytes for the new
campaign, the `2025-12-31` campaign/test endpoint and P14c calendar bound; it adds
the DQ-only native-label export rule to v1 §5; and it replaces v1 §11's statement
that those choices are closed. V1's historical P7 release binding remains exact.

## 1. Replaced research and campaign dates

The exact snapshot, Qlib view and P2–P7 release identities in v1 §3 remain unchanged.
Their files and historical reports are never rewritten. The P7 research and validation
policies remain bound to that historical release only.

For this P14-DQ campaign, use the separate proposed research policy bytes at
`docs/reviews/p14-dq-proposed-research-policy.yaml`:

| Binding | Proposed v2 value |
|---|---|
| Train | `2015-01-01..2019-12-31` |
| Research validation | `2020-01-01..2022-12-31` |
| Research test and campaign validation | `2023-01-01..2025-12-30`, exactly equal |
| Campaign development | `2020-01-01..2022-12-31` |
| Sealed placeholder | `2026-01-01..2026-01-30`, never accessed |
| Research policy file SHA-256 | `0858014140d42472eddf216caba32910354c6ad7c3cbe4d72ca004cd7fff1dc9` |
| Research policy contract hash | `bd5e4ac708d7c72b6b8f6dcde649a028e80db77134ba531a74a103a67ae128f6` |

The P14-DQ research policy changes the v1 policy ID and test endpoint only.
Its `label_horizon_trading_sessions=1`, purge, model, seed, thread count, boosting
rounds and stopping parameters are unchanged. Before the first trial, verify the
complete Qlib view and its ordered calendar, derive the last evaluable date as the
trading session immediately before the view's final session, and require it to be
`2025-12-30`. The view's `2025-12-31` session supplies the one-session forward label
for the last evaluated session. No caller-supplied date or calendar may override this.

Use the separate proposed validation policy bytes at
`docs/reviews/p14-dq-proposed-validation-policy.yaml`, file SHA-256
`4214f8ed1160f8b4134c0b1efbbdedbcbda32d0e42042cf26bf6c4059c07b3e6`,
contract hash `5db574205ab112fcd9ad49216813567bfccd61cad0b6211187e8ea505e5f10dc`.
Only its policy ID and last subperiod endpoint change from the v1 validation policy;
the last subperiod ends at `2025-12-30`. All gates, thresholds, minimum observations,
stress/parameter grids, earlier subperiods and tolerances remain unchanged.

For **each** of the four policy subperiods, derive its complete weekly schedules
independently from the verified full Qlib-view calendar for that subperiod, retaining
only schedules whose decision **and** execution dates are both inside its bounds.
The frozen view yields 152 schedules for `2015-2017`, 153 for `2018-2020`, 151 for
`2021-2023`, and 103 for `2024-2025` ending `2025-12-30`; reject a different count
or a canonical schedule hash that differs from an independent derivation from the
same verified view. Build and verify that subperiod's PIT cross-section evidence from
the same immutable snapshot/view and candidate expression using the existing PIT
service, then run the existing Qlib signal and backtest variant over its full period.
The `2023-01-01..2025-12-30` campaign-validation schedules and PIT evidence may
not be sliced or reused as substitutes for earlier subperiod evidence. Retain the
existing minimum 20 observations per subperiod and every original Validation gate.
These are robustness variants, not additional autonomous campaign trials. P14d-B's
historical subperiod behavior and artifacts remain unchanged.

## 2. Replaced P14c calendar binding

The P14c plan calendar is the complete ordered set of trading sessions from the
verified, frozen Qlib view in the inclusive campaign validation interval
`2023-01-01..2025-12-30`; the current view yields exactly 726 sessions. Freeze its
view hash, bounds, dates and plan hash before any trial. The unchanged P14c service
must reject any eligible Rank IC series whose dates differ from that entire calendar
or whose values are nonfinite. Keep the full two-candidate denominator, identical
bootstrap/Holm procedure, eligibility accounting, failure taxonomy and thresholds.
Do not remove any date from the frozen P14c calendar after a trial.

## 3. Explicit Qlib-native missing-label export profile

The P14-DQ natural path continues to use Qlib `DatasetH`, `LGBModel`, `SignalRecord`
and `SigAnaRecord`. Their native outputs remain immutable source evidence. For the
DQ ResearchResult export only, the following deterministic rule supersedes the v1
exporter's blanket rejection of any nonfinite native label row:

1. Require one-column native prediction and label objects with identical, unique
   `(date, instrument)` keys. Require all native predictions to be finite.
2. Require every native label to be finite or `NaN`. Reject infinities and malformed
   values. Export a prediction/label pair exactly when its native label is finite.
   Omit both rows when that native label is `NaN`. Never impute or synthesize a label.
3. Record the raw, exported and omitted pair counts, the ordered omitted-key hash,
   and hashes of the unmodified native prediction/label files. Fail if count
   reconciliation or hashes disagree. The verifier must independently reproduce the
   exported pairs and omission audit from the retained unmodified native files.
4. Require the native prediction/label key dates to lie only in the frozen test
   calendar. Require the **native and exported** IC and Rank IC date sets each to
   equal exactly the 726 frozen P14c calendar dates, with no missing, duplicate or
   extra date. Compare every exported IC and Rank IC numeric value exactly with its
   finite native value. Compare all four exported Qlib summary metric names and
   values exactly with the unmodified native `metrics.json`; reject nonfinite
   values. Do not drop, fill or recompute any daily statistic or summary metric.
5. Use an explicit DQ-only export profile with the strict existing behavior as the
   default for every other caller. Keep the ResearchResult v1 file schema and its
   existing verifier. Publish a content-addressed DQ export-audit sidecar in each
   qualification root, bound to the ResearchResult hash and native source-file hashes.
   The DQ bottom-up verifier must require this sidecar and repeat steps 1–4 from
   the retained native files before accepting the ResearchResult. Preserve all
   historical ResearchResult and P14d-B bytes.

The sidecar binds `research_result_hash`, the five existing native source-file hashes,
`raw_pair_count`, `exported_pair_count`, `omitted_nan_label_count`, the ResearchResult
prediction/label content hashes, and `omitted_keys_sha256`. For the last field, sort
omitted keys by `(trade_date, qlib_instrument_id)` and hash canonical JSON bytes of
objects with exactly those two fields. Its own hash is derived from canonical bytes;
the successful execution receipt's evidence hashes, corresponding campaign-trial
evidence, both root principal-hash sets and final report bind that hash and its
exact file path. Every non-execution-failed candidate ResearchResult must have
exactly one matching sidecar; no sidecar may be reused across distinct results. The
count equation `raw = exported + omitted` is mandatory. The verifier checks every
listed native file and reconstructs every exported value row, rather than trusting
the sidecar's asserted counts or hash.
Publish and verify the sidecar before the execution adapter emits a successful
receipt or records a `TrialOutcome.PASS`. A DQ-specific verifier must repeat the
check whenever the receipt/result is read or replayed, before returning a result
to the orchestrator, and immediately before calling P14c selection over the full
two-candidate trial/evidence set. This preselection check covers `PASS`,
`SOFT_REJECT` and `HARD_REJECT` trials carrying a ResearchResult, not just the
selected candidate. A missing, duplicate, swapped or invalid sidecar causes an
execution/integrity failure and P14c `FAILED / NOT_EVALUATED`; it cannot become
`NONPASS_VALIDATION` at `p=1` or `NO_SELECTION`. The independent qualification
verifier repeats all sidecar checks on every rebuilt root.

Missing instrument-date labels do not become observations in any derived value-row
artifact. Any missing daily Rank IC, absence of a verified ResearchResult, or inability
to reproduce the omission audit is `FAILED / NOT_EVALUATED`, never `NO_SELECTION`.
Nothing in this rule alters PIT, Validation, P14c eligibility or statistical gates.

## 4. Unchanged authority and acceptance

The v1 exact upstream lineage, two-candidate P14b family, report-only finalization,
forbidden sealed handoff, negative cases, restart/replay, independent-root equality,
immutable publication and bottom-up rebuild rules remain binding. A genuine
Validation rejection remains a rejection. Both candidates rejected or any natural
execution failure blocks P14-DQ PASS.

This amendment becomes active only after independent Sol High contract approval,
pinning of this document's exact bytes, and an implementation commit with clean
double-root qualification and independent acceptance. Until then P14-DQ remains
`NOT_EVALUATED` and must not be declared `QUALIFIED`.
