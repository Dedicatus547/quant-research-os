# P14-DQ reproducibility amendment approval record

Status: **APPROVED AMENDMENT — append-only review record**

This record binds the independent approval of the P14-DQ reproducibility environment
amendment. It is immutable historical evidence: it must not be edited to change a hash, a
verdict or a claimed authority. The amendment document itself intentionally keeps its
`DRAFT` status line; this record, not that line, is the authority, exactly as with the
approved v3 engineering acceptance contract.

Loading this record does not by itself qualify P14-DQ. Qualification still requires a
clean-commit independent double-root run produced under the amendment, the full bottom-up
verifier, and a separate independent acceptance review of that run's evidence.

## Approved bindings

approved_amendment_sha256:
a63058df2df0a89c054965fb33046d99dc0851624bd231b45a2446709539dbce

approved_amendment_path:
docs/p14-dq-qualification-contract-v3-reproducibility-amendment.md

approved_implementation_commit:
e968ce355a338e15425c27e500b74a9c43beb6af

review_verdict:
APPROVE

review_harness:
Codex

review_model:
GPT-6 Sol

review_reasoning:
Max

review_context:
fresh independent context; first a diagnostic consultation, then a required-fix
confirmation of the final reviewed diff

supplemented_contract_sha256:
563b1c44ff8e3b87822902c1f70183de2ddd97b007550f2028990bb37f858e17

supplemented_approval_record_sha256:
6010a6c2d53727fabce7e3a6caf9cc5f0dd9dfd2ced131e2a524cd1993f0aa74

authority:
the reproducibility amendment and its implementation may serve as the P14-DQ v3
clean-commit qualification implementation baseline

non_claim:
approval itself is not P14-DQ qualification

## What the amendment binds

- The P14-DQ qualification and verification interpreters must start with
  `PYTHONHASHSEED=0`; a process that cannot prove this refuses instead of producing
  environment-dependent evidence.
- The qualification bundle carries an immutable runtime environment record holding the
  frozen seed, the disabled-hash-randomization fact, the runtime fingerprint and this
  amendment's hash; the qualification report binds it, the report schema is raised, and the
  record is re-verified from bundle bytes.
- Root and environment reproducibility mismatches are reported as
  `REPRODUCIBILITY_MISMATCH`, not as generic artifact corruption.
- Acceptance is scoped to the exact frozen snapshot/view lineage, the exact clean
  implementation commit and the frozen runtime environment including the seed. It is not a
  claim that the reused Qlib engine is hash-order independent, nor that artifacts equal
  those produced under any other seed, and it adds no alpha, profitability,
  candidate-selection, sealed-confirmation, live-Agent, FR-03 or vendor-vintage PIT
  authority.

## Why it was needed

Qlib 0.9.7 sums per-instrument valuation over `list(set(...))` in
`qlib/backtest/position.py`, and floating-point addition is not associative, so
valuation-derived artifacts depended on the interpreter hash seed. Trading decisions
reproduced byte for byte; only account, portfolio weight and risk metrics carried last-bit
noise. Rule 1 of `AGENTS.md` requires reusing the Qlib engine rather than re-implementing
portfolio accounting, so the process environment is frozen and bound instead.

## Review and fix chain

- initial implementation commit: `94f8f201fd86f4fae23cd1b0a008d8106d39abe1`
- guard hardening after the first independent review: `0338290956d030893d49efb9bfcc614b45eb9d6c`
- wording, classification and guard-ordering fixes: `97b91ac864e03ad9eb69bd7bc5761fad8f902d28`
- re-exec failure classification and retained same-seed evidence: `e968ce355a338e15425c27e500b74a9c43beb6af`
- the reviewed baseline commit above is a historical binding of what was reviewed; the
  qualification commit that contains this record is bound separately by the report's code
  provenance.

## Retained history and non-claims

- The pre-amendment bundle
  `sha256-10cf6e09f32e39716daea7f48e565ad2798f8a0362eb4e81faaed04a14fc92a3` remains **not
  accepted**: its mandatory full bottom-up verification failed, and it cannot be re-verified
  under the raised report schema. It is retained unmodified as evidence of the defect.
- The earlier failed attempts remain immutable failures.
- The same-seed diagnostic evidence under `artifacts/qualification/diag/` is gitignored local
  diagnostic material. It supports the diagnosis and is not qualification authority.
