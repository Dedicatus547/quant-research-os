# P14-DQ v3 qualification acceptance record

Status: **ACCEPTED QUALIFICATION — append-only acceptance record**

This record preserves the independent final acceptance of the P14-DQ v3 Data-qualified
engineering qualification evidence and binds the exact qualification artifacts. It is
immutable historical evidence and must not be edited to change a hash, a verdict or a claimed
authority.

Acceptance is of the engineering qualification only. It is not a research, alpha,
profitability, investment-suitability, live-Agent, FR-03 or sealed-confirmation result, and it
does not start the P14 Release Candidate track.

## Accepted qualification bindings

qualification_hash:
f75455152dbd90827d8d1a015ecf1b0fa5ad749f53b67a06226b9d7039f2cb53

qualification_path:
artifacts/qualification/p14-dq/sha256-f75455152dbd90827d8d1a015ecf1b0fa5ad749f53b67a06226b9d7039f2cb53

qualification_report_schema:
p14dq-qualification-report/v5

implementation_commit_hash:
6573112a7ae46c2c6a5c29f85ff38a2450ca41ba

lockfile_hash:
0f5cd349fb32eed64a0cb907242f0ddd333f69efdc77461bdff90602e5bed7ca

runtime_fingerprint_hash:
66d954a1ff034d6ecb555885e12926e585543a4d71c92ea35bb5720465730321

runtime_environment:
{"hash_randomization_enabled": false, "python_hash_seed": "0",
 "reproducibility_amendment_hash": "a63058df2df0a89c054965fb33046d99dc0851624bd231b45a2446709539dbce",
 "runtime_fingerprint_hash": "66d954a1ff034d6ecb555885e12926e585543a4d71c92ea35bb5720465730321",
 "schema_version": "p14dq-runtime-environment/v1"}

qualification_contract_hash:
563b1c44ff8e3b87822902c1f70183de2ddd97b007550f2028990bb37f858e17

reproducibility_amendment_hash:
a63058df2df0a89c054965fb33046d99dc0851624bd231b45a2446709539dbce

external_bindings_hash:
cdc3f98383b422f3adbb018894749e4488d2058dcc11d6e1fe40cb46c3f281c3

snapshot_hash:
6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9

qlib_view_hash:
fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b

upstream_release_report_hash:
6e3d6d8f6d1f8c9fd50124ce9cfcd6e22febb0099c05d5931878ca972da0ebca

principal_hash_summary:
ad402d40959ddc8e21bc918667751b89b39bff1f45cfaa66320756a656d2ebf8

principal_hashes_byte_exact:
true

## Natural research outcome (unchanged, recorded verbatim)

- P14c: `FAILED / NOT_EVALUATED / SOURCE_INCOMPLETE`, `eligible_candidate_count = 0`,
  `selection_performed = false`, no scores and no selected candidate.
- Both frozen candidates executed exactly once with `SOFT_REJECT` trial outcomes and
  `ValidationReport` `SUCCEEDED / REJECT`: eleven gates present, no `NOT_EVALUATED` gate,
  `G0/G1/G2/G4/G9/G10` PASS, and the only rejection is
  `G5_OUT_OF_SAMPLE` with `SOFT_THRESHOLD_NOT_MET`, which satisfies the v3 admissible
  rejection predicate.
- Autonomous loop closed in `SELECTION_COMPLETE` with no `SelectionFrozen`, no campaign-level
  `OOSAccessed` and no sealed-confirmation authority.

## Engineering qualification outcome

- P14-DQ report: `SUCCEEDED / PASS`, 1054 exact files, schema `p14dq-qualification-report/v5`.
- Independent roots: `root-A` and `root-B` share the same artifact tree hash and the same
  principal evidence, and the report records `principal_hashes_byte_exact = true`.
- Engineering gates: 54 P14d negative cases (27 per root), 24 P14-DQ negative cases (12 per
  root) and 6 restart cases (3 per root) all passed.
- Full bottom-up verification (`verify`, not the bundle-only mode) rebuilt both roots from the
  explicit frozen external inputs and returned `SUCCEEDED / PASS`.

## Independent authority

- Reviewer: Codex, model GPT-6 Sol, reasoning High, fresh independent context.
- Verdict: **APPROVE**, no blocking findings and no required fixes.
- The reviewer re-verified the approval records, the exact file inventory, the report
  bindings and re-ran the full bottom-up verifier itself.

## Authority granted, and excluded authority

Granted: bounded deterministic autonomous Data-qualified engineering qualification for the
exact frozen snapshot/view lineage, the exact clean implementation commit and the frozen
runtime environment recorded above.

Excluded: alpha authority, profitability authority, investment suitability, live-Agent
authority, FR-03 authority, sealed-confirmation authority, unrestricted autonomous research
authority, and any vendor-vintage PIT claim.

## Corrections and non-claims carried forward

- The claim that no `OOSAccessed` event exists is scoped to the campaign and sealed layers.
  Ordinary Validation events legitimately contain `OOSAccessed`, so an unscoped reading would
  be wrong.
- Reproducibility is asserted only under the frozen runtime environment, which includes the
  frozen interpreter hash seed. This is not a claim that the reused Qlib engine is hash-order
  independent, nor that artifacts equal those produced under any other seed.
- The frozen limitation set `P14DQ_LIMITATIONS` is unchanged.

## Preserved history

- Failed attempts `sha256-712e60b4…`, `sha256-c9db2776…`, `sha256-17a5226c…` and
  `sha256-1f9fcda5…` remain immutable failures.
- The pre-amendment bundle `sha256-10cf6e09…` remains **not accepted** and cannot be
  re-verified under the raised report schema.
- The approved v3 contract, the reproducibility amendment, the amendment approval record and
  the earlier approval record are all byte-unchanged.

## Next task (recorded, not started)

P14 Release Candidate freeze.

This acceptance does not start the P14 Release Candidate track, and no P14-RC artifact,
authority or review is created by it.
