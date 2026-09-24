# P14-DQ contract reopening: evaluable live-data window

Status: **DRAFT AMENDMENT — independent Sol High contract review required**

This document proposes a bounded revision to the P14-DQ contract approved at `37880e8`.
It does not approve the revision, change that frozen v1 contract, or qualify P14-DQ. The
implementation at `e9d1487` remains a faithful fail-closed attempt under v1.
The proposed normative amendment is `docs/p14-dq-qualification-contract-v2-draft.md`;
its review candidate SHA-256 is
`645794fd37108669d712e133bcbdf0305418098d53be10f18155d1321444b13f`.
This review record provides its incident evidence and review questions.

## Evidence requiring reopening

The clean-commit run at `e9d1487` retained the content-addressed failed attempt
`artifacts/qualification/p14-dq/attempts/sha256-ce8ce23bfdf975d75d42ae75513028d5eb4ad0b01c2d7e06026a45579587dafe`.
Its 72-file exact inventory and hashes verify. The P14c report is
`FAILED / NOT_EVALUATED / SOURCE_INCOMPLETE`; both candidate execution receipts are
`EXECUTION_FAILED / QLIB_EXECUTION_FAILED`. No qualification PASS report exists.

Both Qlib `SignalRecord` native outputs have 218,016 test prediction/label rows and 530
missing label values. Of those, 298 are on `2025-12-31`; 232 are earlier instrument-date
rows. Both Qlib `SigAnaRecord` IC and Rank IC series have exactly one missing date:
`2025-12-31`. Their 726 observations through `2025-12-30` are finite. The verified view
ends at `2025-12-31`; the frozen research label is
`Ref($close,-1)/$close-1` (`label_horizon_trading_sessions=1`). The view has no following
session to label `2025-12-31`. An offline Qlib query confirms an actual forward label for
`SH600000` on `2025-12-30`, using the view's `2025-12-31` data.

The v1 contract requires a P14c calendar through `2025-12-31`, and unchanged P14c requires
one finite Rank IC value for every frozen calendar date. The existing ResearchResult exporter
also rejects any nonfinite native label row. Thus changing the endpoint alone cannot make
the natural campaign evaluable. Filling the terminal value, dropping a Rank IC date from
the v1 calendar, or relabeling failed execution as `NO_SELECTION` would violate v1 authority.

## Proposed v2 contract delta

1. **Keep all external identities unchanged.** Use the exact snapshot, Qlib view, quality
   report and P2–P7 release already frozen by v1. Do not acquire or rebuild data. The P7
   research and validation policy files remain historical release inputs with their exact
   existing hashes; they are not rewritten.
2. **Freeze an evaluable P14-DQ window.** Create a separate P14-DQ research policy with the
   same train and validation ranges and every existing model/purge setting. Set only its
   test end to `2025-12-30`. Set `campaign.validation` to
   `2023-01-01..2025-12-30`, exactly equal to that policy's test segment. Derive the end
   mechanically from the verified view's last trading date and the one-session forward
   label horizon, then require the derived end to equal `2025-12-30`. The view retains
   `2025-12-31` as the source of the final included forward label. No caller date override.
3. **Align validation workload, retain its gates.** Create a separate P14-DQ validation
   policy whose final `2024-2025` subperiod ends at `2025-12-30`. Preserve every hard gate,
   soft metric, threshold, minimum observation count, stress multiplier, parameter grid,
   earlier subperiod, reproducibility tolerance and cost/backtest rule. Freeze both new
   policy files and hashes before another qualification run. A different natural Validation
   verdict remains binding; no policy tuning after seeing it.

   The review-ready policy bytes are
   `docs/reviews/p14-dq-proposed-research-policy.yaml` (file SHA-256
   `0858014140d42472eddf216caba32910354c6ad7c3cbe4d72ca004cd7fff1dc9`,
   canonical contract hash
   `bd5e4ac708d7c72b6b8f6dcde649a028e80db77134ba531a74a103a67ae128f6`)
   and `docs/reviews/p14-dq-proposed-validation-policy.yaml` (file SHA-256
   `4214f8ed1160f8b4134c0b1efbbdedbcbda32d0e42042cf26bf6c4059c07b3e6`,
   canonical contract hash
   `5db574205ab112fcd9ad49216813567bfccd61cad0b6211187e8ea505e5f10dc`).
   Model-level comparison with the v1 policies shows only the new policy IDs, the test
   endpoint and the final subperiod endpoint differ.
4. **Keep P14c unchanged.** Its plan calendar must be the complete, ordered set of verified
   Qlib-view trading sessions in `2023-01-01..2025-12-30` (726 observed sessions), frozen
   before trials. P14c still requires an exact date-for-date finite Rank IC series over
   that entire calendar, all two enumerated candidates in the denominator, the existing
   bootstrap/Holm method, and the existing fail-closed eligibility and evidence rules.
5. **Specify auditable native-label export.** Qlib `SignalRecord` and `SigAnaRecord` remain
   authorities. For ResearchResult value rows only, require identical, unique native
   prediction/label keys and finite predictions. Export prediction/label pairs exactly
   when the native label is finite. Permit omission only for native **NaN label** keys;
   reject infinities, malformed or unmatched keys, and any missing or nonfinite daily IC
   or Rank IC value. Do not impute, recompute Qlib metrics, or change P14c statistics.
   Bind the unmodified native file hashes, raw/retained/omitted row counts, and canonical
   hash of every omitted key. A DQ bottom-up verifier must read the retained native files
   and independently reconstruct the exported pairs and omission audit. Use a DQ-only
   export profile with the existing strict behavior as default, keep the existing
   ResearchResult v1 schema/verifier, and publish a content-addressed DQ audit sidecar
   in each qualification root. The DQ verifier requires and rederives that sidecar;
   the execution adapter must verify it before returning any result that carries a
   ResearchResult, and the orchestrator must reverify before P14c;
   historical ResearchResult and P14d behavior remain unchanged.
6. **Retain every other v1 gate.** The frozen family/manifest and two-candidate denominator,
   report-only finalization, immutable external verification, PIT/Validation/statistical
   gates, negative cases, restart/replay, independent roots and bottom-up rebuild still
   apply. Both candidates may still be rejected by genuine Validation; that result is
   `FAILED / NOT_EVALUATED`, not an engineering PASS.

## Review questions and qualification sequence

The first independent GPT-6 Sol High review returned
**APPROVE_WITH_REQUIRED_FIXES**. Its required fixes are incorporated in the current
draft for a diff-only re-review:

1. Four complete Validation subperiod schedules and independently verified PIT
   collections must come from the full frozen view/snapshot, rather than slicing
   the 2023–2025 baseline. Observed full weekly schedule counts are 152, 153,
   151 and 103; the existing baseline slice yields 0, 0, 49 and 103.
2. The DQ sidecar must be verified before successful receipt, on every receipt/result
   read and replay, and before P14c sees any trial carrying ResearchResult, including
   an `EXECUTION_FAILED` trial with a ResearchResult from failed Validation. Receipt
   and trial evidence bind its hash; a frozen layout derives the path, which the root
   and final report verify. Missing/duplicate/swapped sidecars make DQ
   `FAILED / NOT_EVALUATED` and block P14c success.
3. Native and exported IC/Rank IC dates must each equal the exact 726-session
   P14c calendar, with values and all four summary metrics checked against native
   output; native prediction/label keys must stay within the test calendar.

The first diff-only re-review also returned **APPROVE_WITH_REQUIRED_FIXES**:
Validation can fail after ResearchResult creation, so the sidecar gate must cover
every trial with a ResearchResult regardless of trial outcome. It also required the
hash-only receipt/trial binding and the pre-P14c DQ failure behavior now stated in
the draft. This revised text awaits another independent diff-only verdict.

The independent reviewer should decide whether the proposed label-pair export and its
DQ sidecar preserve ResearchResult authority, and whether the DQ-specific policy-window
change leaves P14c and Validation semantics intact. The
review must check exact new policy bytes/hashes and the native omission audit design before
implementation. If approved, implement against a new pinned v2 contract hash, run targeted
regression and a natural live-data preflight, then run the formal clean-commit independent
double-root qualification and an independent Sol acceptance gate. A failed natural
Validation or selection outcome must remain failed evidence.
