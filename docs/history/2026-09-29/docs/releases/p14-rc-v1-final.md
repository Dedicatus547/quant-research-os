# P14 Release Candidate v1 final freeze

Status: **P14_RC_FREEZE_READY**

Date: 2026-09-29

This is the final resolution and freeze record for P14 RC v1. It does not rewrite either
historical blocked attempt or any qualification report. The enclosing Git commit is documentation
and evidence only; production behavior was qualified on commit e318dc450e5c02f1120da7644250767bf682b6f9.

## Production and qualification provenance

- Starting formatter baseline: ea2573ffd1d72e3f1f28390550e174338d88dda9.
- Final production baseline: e318dc450e5c02f1120da7644250767bf682b6f9
  (fix: drain Qlib metrics before artifacts).
- Lockfile SHA-256: 0f5cd349fb32eed64a0cb907242f0ddd333f69efdc77461bdff90602e5bed7ca.
- Runtime fingerprint: 66d954a1ff034d6ecb555885e12926e585543a4d71c92ea35bb5720465730321.
- Runtime environment: PYTHONHASHSEED=0; hash randomization disabled; environment record schema
  p14dq-runtime-environment/v1.

| Track | Qualification report | Qualified implementation | Result |
|---|---|---|---|
| P14c retained evidence | d0412a30d27c4d793fe527a28432292f1616a4ad726830d3cb1ce24a5836913a | 618498a64b8e46ab5c38f66ea08a03a2afdaea32 | retained verifier SUCCEEDED / PASS |
| P14d-B | 41a27c6fd2b5f0f522a1fcae13424b924b9cdc2fa4e8aa0df24ff12d79fadc71 | e318dc450e5c02f1120da7644250767bf682b6f9 | SUCCEEDED / PASS |
| P14-DQ | f912cb0b376c981c94dae267cb0b16a4d2f1e0a52edcd36d08f938f92964d38a | e318dc450e5c02f1120da7644250767bf682b6f9 | SUCCEEDED / PASS engineering qualification |

P14d-B has principal summary db5c8a0dfe0672fb5c326971d44bd9e8d29c720bb998c281c42c1b0ada96ab64.
Its independent roots are byte-exact. The canonical cases are SELECTED, NO_SELECTION, and
FAILED_NOT_EVALUATED. The selected path records SelectionFrozen and ends at
READY_FOR_SEALED_CONFIRMATION. The report covers 54 negative cases and 6 restart cases; Replay
reuses its recorded exchange and execution receipt without another Qlib run. The full artifact
verifier returned SUCCEEDED / PASS.

The P14-DQ report binds the same frozen snapshot, Qlib view, upstream data-qualified release,
approved v3 contract and reproducibility amendment, family, denominator, policies, and report-only
finalization as the accepted v3 qualification. It binds snapshot
6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9, Qlib view
fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b, and upstream release report
6e3d6d8f6d1f8c9fd50124ce9cfcd6e22febb0099c05d5931878ca972da0ebca. The external-bindings hash is
cdc3f98383b422f3adbb018894749e4488d2058dcc11d6e1fe40cb46c3f281c3. The approved v3 contract hash
is 563b1c44ff8e3b87822902c1f70183de2ddd97b007550f2028990bb37f858e17; the approved reproducibility
amendment hash is a63058df2df0a89c054965fb33046d99dc0851624bd231b45a2446709539dbce.

Both P14-DQ roots have principal summary
affa9baefe5880b1bc54886e1c48688a4be5fcb92f41fd699a74326ef1abaf9b. Their principal hashes and
artifact trees are byte-exact. Qualification totals are 54 P14d negative cases, 24 P14-DQ negative
cases, and 6 restart cases. The full bottom-up verifier, which rebuilt both roots from explicit
frozen inputs, returned SUCCEEDED / PASS.

The natural P14-DQ research outcome remains FAILED / NOT_EVALUATED / SOURCE_INCOMPLETE. Candidates
b7ca426ad868e15827365aa2bfcceb20870893a91add47713ff88dc2a43d444f and
f6941537f61ba9cde4c0e866d365919a0fc3dda96c30304c1378bfc069364e96 each executed once and
produced SUCCEEDED / REJECT validation with SOFT_REJECT through G5_OUT_OF_SAMPLE /
SOFT_THRESHOLD_NOT_MET. There are zero eligible candidates, selection was not performed, and
sealed-confirmation authority is false. The engineering PASS does not change that research result.

## Qlib order-dependence diagnosis and correction

Historical failing observation:

- Candidate: f6941537f61ba9cde4c0e866d365919a0fc3dda96c30304c1378bfc069364e96.
- Window: DELTA window 3.
- Expected natural result: SOFT_REJECT.
- Observed result: EXECUTION_FAILED / QLIB_EXECUTION_FAILED, with no ResearchResult or
  ValidationReport.
- Historical failure artifact: 125c5688283ce2d603183f932dab13f1b9fab3af6bdbdb187ed0bbaa8295d2ae.
- The target passed 10/10 isolated repetitions; the pre-fix ordinary full-suite run reported
  697 passed and 1 failed.

The non-authority diagnostic capture identified the nested exception as
ValueError: Metric 'l2.valid' is malformed. No data found. MLflow FileStore raised it while
SignalRecord.generate wrote the prediction artifact: that artifact operation caused FileStore to
read run metrics, including l2.valid, from the metric file.

Qlib's LGBModel.fit queued l2.valid through Qlib's asynchronous recorder. SignalRecord.generate
started an MLflow artifact operation before the queue had finished writing the metric file. If the
file-store read landed in that interval, it observed an empty metric file and rejected execution.
Isolated runs usually let the background worker finish first. Earlier suite execution changed
thread scheduling and exposed the race. Prefix reduction was schedule-sensitive: one pre-fix
75-collected-tests-plus-target run exposed the same failure, while repeated prefix runs did not
identify a consistently mutating test. The exact triggering state was a pending asynchronous
metric write at the synchronous artifact read; no single test or cumulative resource threshold
was the cause.

Resource and global-state observations did not show a leak or stale-provider cause. File descriptor
count was 9 before and after Qlib execution; RLIMIT_NOFILE was soft 10240 and hard 1048576. The
working directory and MLFLOW_ALLOW_FILE_STORE were restored, there was no active MLflow run after
execution, and temporary MLflow worker threads returned from 2–4 to 2–3 without cumulative growth.
Qlib initialized against the bound view. The async queue timing was the contaminating state.

Commit e318dc450e5c02f1120da7644250767bf682b6f9 makes the smallest lifecycle correction in
src/quantos/research/qlib/workflow.py: after model.fit it waits for Qlib's metric queue and clears
the stopped queue before SignalRecord.generate writes artifacts. Later recorder logging runs
synchronously. tests/unit/test_qlib_workflow.py adds a regression test that fails if SignalRecord
starts before l2.valid is written.

No Validation, PIT, P14c, P14-DQ v3, candidate-family, denominator, policy, snapshot/view, runtime,
or sealed/OOS semantics changed. QLIB_EXECUTION_FAILED remains a hard engineering failure. No
traceback, host-specific path, or nondeterministic exception text was added to authority evidence.

## Final regression and repository gates

All gates ran on production baseline e318dc450e5c02f1120da7644250767bf682b6f9:

- Target isolated x10: PASS.
- Ordered 75-item prefix plus target after the fix: 76 passed.
- Ordinary full suite: 699 passed, 113 warnings, 197.66 seconds.
- PYTHONHASHSEED=0 full suite: 699 passed, 113 warnings, 197.00 seconds.
- Coverage run: 699 passed, 113 warnings, 85.01%; repository threshold 85.0%.
- ruff format --check .: PASS, 275 files already formatted.
- ruff check .: PASS.
- pyright: PASS, 0 errors, 0 warnings, 0 informations.
- git diff --check: PASS.
- P14c retained verifier: PASS.
- New P14d-B full artifact verifier: SUCCEEDED / PASS.
- New P14-DQ full bottom-up verifier: SUCCEEDED / PASS.

The P14-DQ reproducibility claim remains limited to the exact snapshot/view lineage, implementation
commit, runtime fingerprint, approved runtime environment, and PYTHONHASHSEED=0. Qlib 0.9.7
set-order and last-bit valuation sensitivity remains documented; no hash-order-independent claim
is made.

## Final authority matrix

| Authority domain | Status |
|---|---|
| P14 deterministic autonomous Offline Engineering | QUALIFIED |
| P14 deterministic autonomous Data-qualified Engineering | QUALIFIED for the exact frozen inputs and runtime above |
| P14a | QUALIFIED |
| P14b | COMPLETE within the frozen finite family |
| P14c | QUALIFIED |
| P14d-B | QUALIFIED for the exact e318dc4 implementation and report |
| P14-DQ natural research outcome | FAILED / NOT_EVALUATED / SOURCE_INCOMPLETE |
| P14-DQ engineering | SUCCEEDED / PASS |
| Live Agent | NOT QUALIFIED / BLOCKED |
| FR-03 | NO_GO / THIN_MAINTENANCE |
| P14d-C | BLOCKED_UNIMPLEMENTED |
| Sealed confirmation | NOT QUALIFIED |
| Alpha / profitability | NOT CLAIMED |
| Investment suitability | NOT CLAIMED |
| Vendor-vintage PIT | NOT QUALIFIED; source remains single-source non-vintage |
| Unrestricted autonomous research | NOT QUALIFIED |

Historical blocked RC records remain unchanged: core RC record
28876d1415681ee98817c84aa16b1e68e01af6b0 and blocked freeze
490119cff1ebe8ffe2b698854fbe500f85c42c0a. The formatter-only baseline ea2573ffd1d72e3f1f28390550e174338d88dda9
remains in history. The final freeze commit contains documentation/evidence only, with no production
behavior added after qualification.
