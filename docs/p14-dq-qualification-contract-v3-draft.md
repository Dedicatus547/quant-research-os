# P14-DQ engineering acceptance contract v3 — draft amendment

Status: **DRAFT — independent contract review required before formal qualification**

This amendment changes only the P14-DQ engineering acceptance layer. It supplements the
approved v2 amendment (SHA-256
`645794fd37108669d712e133bcbdf0305418098d53be10f18155d1321444b13f`) and
supersedes v1 §6's rule that two genuine Validation rejections cannot support P14-DQ
engineering PASS, and v2 §4's corresponding sentence. All other v1/v2 bindings and
gates remain in force. In particular, P14c, Validation, PIT, family, candidate,
window, policy thresholds, statistical method and denominator are unchanged.

## 1. Reason and authority boundary

This revision was proposed **after** observing the clean-commit v2 zero-eligible result
at `artifacts/qualification/p14-dq/attempts/sha256-c9db27763e6b39be70fe96fe1047cd3f39f593b891f035f999864b0567eeeed0`.
That attempt remains permanently `FAILED / NOT_EVALUATED / SOURCE_INCOMPLETE` under v2;
its bytes, report and history must not be replaced, relabelled or cited as a v3 PASS.
The observed P14c report is
`sha256-c79d18ca3decd7157084361325f3e04cfbfb7ea63e31bc36bba5a2168a18db6c`.

Engineering PASS under v3 proves only that the frozen pipeline reproducibly executed
and verified its evidence on the exact qualified snapshot/view. It adds no alpha,
profitability, candidate-selection, sealed-confirmation, live-Agent, or broader data
authority. The natural research outcome is recorded separately and verbatim.

## 2. Natural outcome and engineering acceptance

P14-DQ may issue a new v3 `SUCCEEDED / PASS` engineering report for either of these
mechanically verified natural outcomes:

| Eligible candidates | Required P14c natural result | Selection performed |
|---|---|---|
| One or more | `SUCCEEDED / SELECTED` or `SUCCEEDED / NO_SELECTION` | `true` |
| Zero, solely because both complete candidate trials have genuine Validation rejection | `FAILED / NOT_EVALUATED / SOURCE_INCOMPLETE`; no scores or selected candidate | `false` |

The zero-eligible case requires **both** frozen candidates to run exactly once on the
exact qualified snapshot/view and each to have a bottom-up verified ResearchResult,
DQ native-label export-audit sidecar and ValidationReport. Each Validation execution
must be `SUCCEEDED` with verdict `REJECT`, and each trial outcome must be only
`SOFT_REJECT` or `HARD_REJECT`. P14c's verified disposition for each candidate must
be `NONPASS_VALIDATION`, with no eligible score. Its complete report must mechanically
rebuild to the exact `FAILED / NOT_EVALUATED / SOURCE_INCOMPLETE` result from the full
two-candidate denominator. A failed PIT, execution, Validation execution, sidecar,
artifact, accounting, calendar, or statistical/evidence gate cannot use this exception.

The v3 P14-DQ report records the P14c status, verdict, reason, eligible count and
`selection_performed` explicitly alongside the unchanged P14c report hash. In the
zero-eligible case these fields are `FAILED`, `NOT_EVALUATED`, `SOURCE_INCOMPLETE`,
`0`, and `false`. It must never say `NO_SELECTION`, name a selected candidate, freeze
selection, emit `OOSAccessed`, or grant sealed authority. The existing report-only
close, Ledger binding and autonomous-loop `SELECTION_COMPLETE` state remain required.

Engineering PASS still requires all v1/v2 exact-lineage, independent-root principal
equality, restart/replay, negative-case, exact-file, and full bottom-up verifier
gates. A v3 report is a new immutable artifact from a new clean implementation
commit; it does not amend the failed v2 attempt.

## 3. Qualification gate

This draft and its implementation grant no qualification. Before any formal v3
qualification run, an independent contract review must approve and pin the exact v3
bytes. Only then may a clean-commit, independent-root qualification and independent
acceptance gate assess a new report. Until those gates pass, P14-DQ remains
unqualified and the P14 Release Candidate authority matrix is unchanged.
