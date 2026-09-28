# P14 Release Candidate v1 freeze audit

Status: **BLOCKED**

This record freezes the P14 evidence and authority matrix for RC review. It does not change any
qualification report or grant authority. The P14-DQ engineering result and its natural research
outcome remain separate.

## RC source and implementation provenance

- Starting `main`: `78e5b948ccf5f0dd6f951b29d25854de3ece0b79`.
- RC candidate source/head before this record: `8a402791559e3fb168da1703e4f52b6b40fcfd8b`
  (documentation synchronization commit; its production sources are unchanged).
- P14-DQ qualified production-code baseline: `6573112a7ae46c2c6a5c29f85ff38a2450ca41ba`.
- Current P14d-B qualification runner commit: `908ee826cdd88cd9a46a55d4462b99e32ec35d31`.
  `src/quantos/` is byte-identical between this commit and the P14-DQ baseline; qualification
  runner changes are limited to fresh-process isolation for Qlib-sensitive cases and final
  self-verification.
- `uv.lock` SHA-256: `0f5cd349fb32eed64a0cb907242f0ddd333f69efdc77461bdff90602e5bed7ca`.
- Runtime fingerprint: `66d954a1ff034d6ecb555885e12926e585543a4d71c92ea35bb5720465730321`.
- P14-DQ runtime environment binding: canonical record hash
  `a0508ea725d8d43296b0eca87ae251d11df05d721f9c7d4ea0a0972e37064f3a`; schema
  `p14dq-runtime-environment/v1`; CPython 3.11.15, Linux x86_64/glibc 2.35,
  `PYTHONHASHSEED=0`, `hash_randomization_enabled=false`.

Each report below qualifies only its named implementation commit and frozen inputs.

| Track | Immutable report hash | Implementation commit | Retained result |
|---|---|---|---|
| P14a Research Ledger | `9954649acc79c3b3aed42d2e3b9b73c9e7a8de7b8f0c7cd2577393e26d9d8640` | `5032fea2882eaa8a11dcc57e27a370a16ecce3d6` | PASS, Ledger engineering scope |
| P14c deterministic selection | `d0412a30d27c4d793fe527a28432292f1616a4ad726830d3cb1ce24a5836913a` | `618498a64b8e46ab5c38f66ea08a03a2afdaea32` | PASS, bounded synthetic Offline Engineering selection scope |
| P14d-B historical | `13355dcb0c623c604ff5d0e4a5cd92d9aba59673d62bd76ffa9c839ee0754825` | `13d2b7acc44fe33c4f0c45d240fd5fd26e993845` | PASS for this historical implementation only |
| P14d-B current-code compatibility | `35465fcf21cea713ceba95073f3b4972dcd5a5b0a42aeee0d82442a04b118b35` | `908ee826cdd88cd9a46a55d4462b99e32ec35d31` | PASS, independent roots, principal hashes byte-exact |
| P14-DQ Data-qualified engineering | `f75455152dbd90827d8d1a015ecf1b0fa5ad749f53b67a06226b9d7039f2cb53` (`p14dq-qualification-report/v5`) | `6573112a7ae46c2c6a5c29f85ff38a2450ca41ba` | Accepted `SUCCEEDED / PASS`; report is retained unchanged |

The current P14d-B report has principal summary `b8a205c9a45ac490be4c8549d6fe373832f69faed11c344cd1a985785b9b230a`, 54 negative cases, 6 restart cases, byte-exact independent roots, Replay reuse, and a passing bottom-up bundle verifier. Its default selected path reaches `SelectionFrozen` and `READY_FOR_SEALED_CONFIRMATION`; `NO_SELECTION` and `FAILED_NOT_EVALUATED` also pass their canonical cases. The P14-DQ report-only finalization profile does not alter this default P14d-B behavior.

The P14c and historical P14d-B reports were mechanically verified against their retained bundles.
The accepted P14-DQ acceptance record has SHA-256
`83854e0e5e0bcc0251448890e0a3ba2ef9209f852bad05d94a4ce13673c17422`; it records the original
full bottom-up verification as PASS. The RC re-verification used the full bottom-up verifier and
explicit frozen inputs (not bundle-integrity mode) and returned `SUCCEEDED / PASS`; the accepted
qualification hash remained `f75455152dbd90827d8d1a015ecf1b0fa5ad749f53b67a06226b9d7039f2cb53`,
external-bindings hash `cdc3f98383b422f3adbb018894749e4488d2058dcc11d6e1fe40cb46c3f281c3`, and
principal summary `ad402d40959ddc8e21bc918667751b89b39bff1f45cfaa66320756a656d2ebf8`. The verifier
did not regenerate or replace the accepted report. It used snapshot
`6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9`, Qlib view
`fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b`, and upstream Data-qualified
release `6e3d6d8f6d1f8c9fd50124ce9cfcd6e22febb0099c05d5931878ca972da0ebca`. The accepted report
also binds external-input aggregate `cdc3f98383b422f3adbb018894749e4488d2058dcc11d6e1fe40cb46c3f281c3`.

## P14-DQ contract and qualification bindings

- Approved v3 contract bytes: `563b1c44ff8e3b87822902c1f70183de2ddd97b007550f2028990bb37f858e17`.
- Approved reproducibility amendment bytes: `a63058df2df0a89c054965fb33046d99dc0851624bd231b45a2446709539dbce`.
- Contract approval record: `6010a6c2d53727fabce7e3a6caf9cc5f0dd9dfd2ced131e2a524cd1993f0aa74`.
- Amendment approval record: `26e331ce4a2df4664995e23f615a205b817bd3318b4ea9e43c9649fc32577ca9`.
- Qualification acceptance record: `83854e0e5e0bcc0251448890e0a3ba2ef9209f852bad05d94a4ce13673c17422`.

The contract and amendment files intentionally retain their historical `DRAFT` wording. The
hash-bound approval records approve those exact bytes; the runner activates the approved bindings
mechanically, and the separate accepted report supplies qualification authority. These frozen
files and approval records were not edited.

## Regression and gate results

On the final production-code state, the full suite passed in both the ordinary interpreter
environment (`PYTHONHASHSEED` unset) and the frozen P14-DQ environment (`PYTHONHASHSEED=0`):
698 tests passed, coverage 85.01% (repository threshold 85.0%). Ruff lint passed; Pyright passed
with 0 errors and 0 warnings; `git diff --check` passed.

The required repository-wide `ruff format --check .` does not pass: 2 files would be reformatted,
270 files are formatted. The two files are `src/quantos/application/autonomous_execution.py` and
`src/quantos/research/qlib/result.py`; both are byte-identical to the P14-DQ production baseline
`6573112a...`. No formatter edit or gate exception was applied. A formatter-only production
change would create a different implementation provenance and require clean-commit reruns of the
affected qualifications. The existing instruction prohibits production-code cleanup without an
actual correctness defect, while the RC gate requires this full format check to pass; this conflict
is the sole RC blocker.

To clear the blocker, authorize the minimal formatter-only production commit and required affected
qualification reruns, or retain the no-cleanup constraint and leave the RC blocked. Waiving the
repository-wide formatter gate is not recorded as an approved option.

## Canonical authority matrix

| Authority domain | Status |
|---|---|
| P14a Research Ledger engineering | QUALIFIED, exact report and implementation above |
| P14b finite-family enumeration | COMPLETE within the frozen finite family; no expanded family authority |
| P14c deterministic selection engineering | QUALIFIED, bounded synthetic scope |
| P14d-B synthetic bounded autonomous engineering | QUALIFIED for both historical and current runner commits, each by its own report |
| P14 deterministic autonomous Offline Engineering | QUALIFIED, bounded synthetic scope |
| P14-DQ deterministic autonomous Data-qualified Engineering | QUALIFIED for the exact snapshot/view lineage, implementation, runtime fingerprint/environment, and seed below |
| P14-DQ natural research selection | `FAILED / NOT_EVALUATED / SOURCE_INCOMPLETE`; `eligible_candidate_count=0`; `selection_performed=false` |
| Live Agent autonomous runtime | NOT QUALIFIED / BLOCKED |
| FR-03 | NO_GO / THIN_MAINTENANCE |
| P14d-C | BLOCKED_UNIMPLEMENTED |
| Sealed-confirmation authority | NOT QUALIFIED |
| Market alpha / profitability | NOT CLAIMED |
| Investment suitability | NOT CLAIMED |
| Vendor-vintage PIT | NOT QUALIFIED; source is single-source non-vintage |
| Unrestricted autonomous research | NOT QUALIFIED |

Both P14-DQ candidates executed naturally once. Each produced `ValidationReport: SUCCEEDED / REJECT`
and `TrialOutcome: SOFT_REJECT` through the admissible `G5_OUT_OF_SAMPLE / SOFT_THRESHOLD_NOT_MET`
research threshold. No candidate was eligible, P14c did not select, and the campaign did not
produce `SelectionFrozen` or sealed-confirmation authority. This research outcome is not changed by
the engineering PASS.

Reproducibility is bound only to the exact snapshot/view lineage, exact qualified implementation,
runtime fingerprint, frozen runtime environment, and `PYTHONHASHSEED=0`. Qlib 0.9.7 is not claimed
hash-order independent. `Position.calculate_stock_value()` iterates a set-derived unordered
instrument collection, so floating-point accumulation order can change last-bit valuation outputs.
This is a frozen runtime/environment limitation, not alpha or trading-decision instability. Qlib
Position accounting remains unchanged and no project-owned valuation logic was added.

## Preserved history and scope

Failed P14-DQ attempts, the unaccepted pre-amendment bundle, rejected draft contract bytes, and the
historical P14d-B qualification remain immutable. No report was regenerated or replaced. No P15,
P14d-C, mutation/crossover, factor-grammar expansion, FR-03 reopening, live-Agent authority,
vendor-vintage PIT, alpha, profitability, or investment-suitability work is included. Production
code was not changed during RC; the commits `2f51a74`, `b155c98`, and `908ee82` preserve test/report
provenance and repair only qualification-runner process isolation.

This record is committed on top of RC candidate source/head
`8a402791559e3fb168da1703e4f52b6b40fcfd8b`. Its enclosing Git commit is the P14 RC freeze-record
commit; the final audit packet records that exact commit hash and push status.
