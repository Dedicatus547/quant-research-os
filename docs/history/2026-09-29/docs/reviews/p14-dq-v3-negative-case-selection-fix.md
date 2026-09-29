# P14-DQ v3 negative-case receipt selection fix

Status: **IMPLEMENTATION CONFORMANCE FIX — independent review required before re-running qualification**

This record documents the second defect found by a formal P14-DQ v3 qualification run and
the minimal fix for it. It amends no contract bytes.

## Defect observed

The run from fix commit `81f94cab95c05a39d4683bf5d0a4262a3339d625` completed root-A's natural
campaign and then failed closed:

```text
attempt: artifacts/qualification/p14-dq/attempts/sha256-1f9fcda5c01a1795fa241a2503d19821dd07fd9a7e4e0c5d6d2cd3c6e4ac99a5
error:   negative case CANDIDATE_HASH_MISMATCH action unexpectedly returned
status:  FAILED / NOT_EVALUATED
```

## Cause

`scripts/p14d_qualification.py` selected the negative-case request as
`_load_receipts(context)[0]`, i.e. the first content-addressed receipt path, and then mutated
it by swapping in `manifest.candidates[1]`.

Receipt artifact names are content-addressed and the receipt binds `code_commit_hash`, so the
sort order is not stable across commits. When the first sorted receipt already belonged to
`candidates[1]`, the swap replaced that candidate with itself. The mutated request was then
fully valid, `_verify_request` correctly accepted it, and the case reported that its action
"unexpectedly returned" - the case silently tested nothing while still failing the run.

Evidence across the two runs on the identical frozen snapshot/view/release:

| run | first sorted receipt | candidate swap |
|---|---|---|
| `sha256-17a5226c…` (activation commit `75de5c1`) | trial ordinal 1, candidate `b7ca426a…` | real mutation, case passed |
| `sha256-1f9fcda5…` (fix commit `81f94ca`) | trial ordinal 2, candidate `f6941537…` | no-op, case failed |

So the negative case passed or failed depending on the commit hash, not on the behaviour it
is supposed to assert.

## Fix

- `_negative_case_receipt` selects the earliest executed trial deterministically
  (`trial_ordinal`, then content hash) instead of trusting file ordering, and fails closed
  when no receipt exists.
- `_candidate_swap_target` returns a frozen manifest candidate whose hash differs from the
  request's candidate, and fails closed when no such candidate exists, so the swap can never
  degenerate back into a no-op.
- The `CANDIDATE_HASH_MISMATCH` case uses that target.

The fix strengthens the negative case: it now always performs the mutation it claims to
perform. No gate is relaxed, and no research, Validation, PIT, P14c, statistical, family,
manifest, denominator, policy or sealed/OOS semantics change.

## Evidence

Replaying the preserved failed run's two real receipts through the fixed helpers selects trial
ordinal 1 (candidate `b7ca426a…`) and swaps in candidate `f6941537…`, a real mutation, where
the previous code selected ordinal 2 and swapped it with itself. An impossible swap now raises
instead of passing vacuously.

## Unchanged

- The approved v3 contract bytes
  `563b1c44ff8e3b87822902c1f70183de2ddd97b007550f2028990bb37f858e17` and the approval record
  `6010a6c2d53727fabce7e3a6caf9cc5f0dd9dfd2ced131e2a524cd1993f0aa74`.
- Both preserved failed attempts (`sha256-17a5226c…`, `sha256-1f9fcda5…`) remain immutable
  historical failures.
- Everything outside `scripts/p14d_qualification.py` and its tests.

## Status

No qualification is granted or implied. A fresh clean-commit independent double-root
qualification, the full bottom-up verifier and an independent GPT-6 Sol High evidence review
are still required.
