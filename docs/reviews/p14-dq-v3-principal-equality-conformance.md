# P14-DQ v3 principal-equality conformance fix

Status: **IMPLEMENTATION CONFORMANCE FIX — independent review required before re-running qualification**

This record documents a defect found by the first formal P14-DQ v3 qualification run and the
minimal implementation fix for it. It does not amend the approved v3 contract: the contract
bytes pinned below are unchanged.

## Defect observed

The formal run from activation commit `75de5c1f9a8ecc5987e229317d525a6e6f268313` executed
both roots completely and then failed closed:

```text
attempt: artifacts/qualification/p14-dq/attempts/sha256-17a5226c0a9199fb6e68b6120db0f0567debfd27e486e8fff11ad8a57c6f3833
error:   independent P14-DQ roots produced different principal evidence
status:  FAILED / NOT_EVALUATED
```

Diagnosis over the preserved attempt:

- The two root trees contain the identical 518 file paths, and every content-addressed
  artifact directory name (the artifacts' own authority hashes) is identical between roots.
- Exactly 68 files differ in raw bytes, and every one of them differs **only** in the
  top-level `created_at` field, e.g. root-A `2026-09-26T02:33:32.447918Z` versus root-B
  `2026-09-26T03:42:59.579908Z` for the same signal manifest.
- `artifact_tree_hash` was a raw-byte inventory hash of the whole root tree
  (`_tree_inventory_hash`), it is part of the independent-root principal payload, and it is
  therefore compared for exact equality between roots.

## Contract basis

Frozen contract v1 §8 (unchanged by the v3 amendment) states:

> Compare every deterministic authority hash. Only documented runtime telemetry, temporary
> paths and wall-clock duration are excluded.

The implementation hashed wall-clock bytes, so the two independently executed roots could
never agree, and neither could a rebuilt root in the full bottom-up verifier. This is an
implementation conformance defect against §8, not evidence of a genuine reproducibility
failure: every deterministic authority hash already agreed between the roots.

The defect was latent because every earlier P14-DQ run failed before the principal-equality
gate: v2 always failed at the zero-eligible P14c gate, and the first v3 attempt was rejected
at contract review.

## Fix

`_tree_inventory_hash` now hashes a per-file projection instead of raw bytes:

- a JSON object carrying the documented top-level wall-clock field `created_at` is projected
  by dropping exactly that field and canonicalizing the rest — the same field each artifact's
  own authority hash already excludes;
- every other payload, including non-JSON artifacts, JSON without that field and nested
  structures, is hashed byte-for-byte, so any other divergence still separates the roots and
  fails the qualification closed.

`artifact_tree_hash` is unchanged in name and type but changed in value semantics, so the
evidence schemas that carry it are bumped: `p14dq-root-evidence/v3` → `/v4` and
`p14dq-qualification-report/v3` → `/v4`.

## Evidence that the fix addresses the observed defect

Recomputing the preserved failed attempt with the fixed rule yields the same inventory hash
for both roots (`8598f713caa706548d2b7b8b78712935cbc0924dc892d2b3a11ad133c37c4c62`), and the
two principal payloads are then byte-identical. Any further divergence still separates them.

## Unchanged by this fix

- `docs/p14-dq-qualification-contract-v3-draft.md` bytes:
  `563b1c44ff8e3b87822902c1f70183de2ddd97b007550f2028990bb37f858e17` (still the approved v3
  contract).
- Family, template, candidate manifest and denominator; Validation thresholds and gate
  definitions; PIT rules; P14c eligibility and statistics; sealed/OOS rules; finalization
  profile; policy bytes; the report-only completion rules.
- The v2 failed attempt and the v3 attempt `sha256-17a5226c…` both remain immutable
  historical failures and are neither rewritten nor promoted.
- `V3_CONTRACT_APPROVED = True` and its approval-record binding from
  `docs/reviews/p14-dq-v3-contract-approval.md`.

## Status

No qualification is granted or implied. A fresh clean-commit independent double-root
qualification and the full bottom-up verifier must pass, and an independent GPT-6 Sol High
evidence review must accept the result, before P14-DQ gains any qualification authority.
