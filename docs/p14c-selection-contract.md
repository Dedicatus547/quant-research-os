# P14c selection contract v1

Status: **method and schema frozen for implementation; statistical qualification pending**.
This freeze is the implementation input for P14c. A report has no campaign-selection
authority until golden, negative, artifact-verification, and independent-root qualification
pass. P14d remains blocked.

## Scope and preregistration

The pre-trial `CampaignSelectionPlan` binds the campaign, full P14b candidate manifest,
family, budget, policy hashes, and the validation trading calendar. Append a
`SelectionPlanFrozen` event immediately after activation and before **any** trial. The
existing `research-campaign-event/v1` bytes are unchanged; the new
`campaign-selection-event/v1` participates in the same sequence and previous-hash chain.
The governor rejects any trial without exactly one matching plan event.
The existing campaign enum must be `PREFROZEN_FINITE_FAMILY`; the plan supplies its
missing method, seed, and calendar bindings. Historical v1 event chains remain
readable, but they cannot yield a P14c selection verdict without this plan.

The policy is `HOLM_CIRCULAR_BLOCK_BOOTSTRAP_V1`, alpha 0.05, 9,999 replicates, a fixed
five-session circular moving block, minimum 40 sessions, and one predeclared common
direction. Only the Qlib-exported daily Rank IC series from a verified ResearchResult
whose resolved experiment lies entirely in the campaign **validation** segment is an
input. The statistic is the arithmetic mean of oriented daily Rank IC. The one-sided
null is that its expected value is at most zero. Rank ICIR and single-experiment
`ValidationReport` PASS do not substitute for this statistic or the campaign verdict.

The selected result is frozen by `SelectionFrozen`, which binds a verified
`CampaignSelectionReport` hash and its one selected candidate hash. It must precede
`OOSAccessed`. The sealed trial must use that same candidate. Once selected, no
development or validation trial may be added. `NO_SELECTION` and `NOT_EVALUATED`
cannot freeze a candidate or authorize sealed confirmation.

## Complete denominator and eligibility

Let `m` be `ResearchFamilySpec.declared_candidate_count`. Verify the manifest by
re-enumeration and require exactly one disposition for every manifest candidate, in
candidate-hash order. Every pre-selection `CampaignTrialRecorded` event appears once in
the report's trial bindings and exactly once in its candidate's `trial_event_hashes`.
Unrun candidates have no trial event and do not consume `max_trials`. Assign
`NOT_RUN_BUDGET` only if a relevant budget limit is exhausted; otherwise use
`NOT_RUN_MANUAL_CLOSE` at the intentional selection stop.

All exact duplicates in the P14b manifest are `EXACT_DUPLICATE` and receive p=1;
their actual trial attempts, if any, remain in the trial ledger. Structural duplicates
remain separate hypotheses and all count toward `m`. Empirical signal correlation is
outside v1 and is reported `NOT_EVALUATED`.

An eligible candidate has exactly one validation-segment trial, outcome `PASS`, one
verified ResearchResult explicitly linked in `CampaignTrial.evidence_hashes`, and one
validated binding to that trial event. A validation result with any other outcome is
ineligible with p=1. Development-only trials do not create a validation result.
Multiple validation attempts for the same candidate, a result reused across candidates,
or a validation result chosen from repeated executions invalidate the **whole** selection
as `FAILED / NOT_EVALUATED`. An eligible result must bind the campaign snapshot and
Qlib view, the candidate expression fingerprint, and evaluation dates within the
frozen validation period. Verify native artifact hashes through the existing
ResearchResult verifier before reading its series. Unverified or missing evidence
cannot be treated as a benign p=1.

All eligible series must have exactly the frozen Qlib-view trading dates, in order,
with no missing, non-finite, or out-of-range Rank IC values (outside [-1, 1]). The
calendar must be derived from and verified against the explicit Qlib view and the
campaign validation period; a caller-supplied list alone is not sufficient. Require
at least 40 sessions and nonzero sample variance for each eligible series. Any
violation yields `FAILED / NOT_EVALUATED`. Zero eligible candidates also yields
`FAILED / NOT_EVALUATED` because the statistical procedure did not run.

## Frozen numerical procedure

For each eligible candidate, set `x[t] = rank_ic[t]` for `POSITIVE`, and negate it for
`NEGATIVE`. Compute `mu = math.fsum(x) / n`, then centered values `z[t] = x[t] - mu`.
For each of 9,999 replicates, repeatedly draw a circular block start uniformly from
`0..n-1`, append five `z` values using indices `(start + j) % n`, and truncate the
last block to get exactly `n` observations. Compute its mean with `math.fsum / n`.
The exceedance count includes `bootstrap_mean >= mu` (ties count against selection).
The raw p-value is `(1 + exceedances) / 10000`.

The stream key is `SHA256(bytes.fromhex(policy.seed) || bytes.fromhex(candidate_hash))`.
Generate SHA256 blocks from `stream_key || counter.to_bytes(8, 'big')`, starting at
counter zero and increasing by one. Read each digest as four consecutive unsigned
64-bit big-endian integers. For a draw from `0..n-1`, discard integers greater than
or equal to `floor(2**64 / n) * n`; return the first accepted integer modulo `n`.
Do not use NumPy/Python global RNG state. Record the seed in the immutable policy.

Give every ineligible candidate raw p=1. Sort all `m` hypotheses by `(raw_p_numerator,
candidate_hash)`; p=1 uses numerator 10000. Holm adjusted numerator at position `i`
(zero-based) is `max` over positions `j<=i` of `(m-j) * raw_p_numerator[j]`, capped
at 10000. Divide by 10000 only for serialized adjusted p-values. Compare to alpha
using integer arithmetic: adjusted numerator `* 20 <= 10000`. The winner is the
eligible significant candidate with smallest adjusted p, then largest oriented mean
Rank IC, then lexicographically smallest candidate hash. Select at most one. If the
procedure executes completely and none passes, emit `SUCCEEDED / NO_SELECTION`.

The circular block bootstrap assumes approximately stationary, weakly dependent daily
Rank IC over the validation window. Holm controls familywise error only to the extent
that the constituent p-values are valid. This method is approximate and does not
establish vendor-vintage PIT or protection from undeclared adaptive validation reuse.
Qualification must state those limits rather than treating a profitable result as
engineering acceptance.

## Report and failure semantics

`campaign-selection-report/v1` binds the plan, campaign, family, budget, manifest,
policy, calendar, exact event-chain prefix, every actual trial, every candidate
disposition, eligible scores, verdict, and limitations. Its hash excludes only the
`report_hash` self-reference; no timestamp affects canonical bytes. Rebuilding from
the same frozen inputs must produce the same bytes in independent output roots.
The verifier recomputes the report from verified inputs and rejects any altered
score, p-value, winner, disposition, event prefix, artifact binding, or extra file.
The report is a deterministic verdict eligible for the P14a ledger v2
`CAMPAIGN_SELECTION_REPORT` node only after verification.

Incomplete manifest/accounting, corrupt evidence, insufficient or invalid series,
unfrozen inputs, or statistical execution failure produce `FAILED / NOT_EVALUATED`
with a reason code. Ineligible candidates with properly recorded schema/PIT/execution
failure remain in the denominator at p=1; a PIT rejection is never promoted to
selection. Only a complete valid run with eligible inputs can produce
`SUCCEEDED / NO_SELECTION` or `SUCCEEDED / SELECTED`.

The v1 contract introduces no sealed-confirmation verdict. Later sealed evidence
requires a separate confirmation report and cannot rewrite this frozen selection.
