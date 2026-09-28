# P14 RC v1 append-only post-freeze verification

This supplement is append-only and does not edit the immutable P14 RC v1 freeze record committed
as `28876d1415681ee98817c84aa16b1e68e01af6b0` (record SHA-256
`49161b9fdc8f1f749e8be5c177a825ea27acd60327e03b2f24310b68a42f5158`). It records final
post-commit regression and gate results on the same production-code baseline and keeps the RC
status at **BLOCKED**.

## Final regression

- Ordinary interpreter environment (`PYTHONHASHSEED` unset): `698 passed`, 113 warnings, 85.01%
  coverage, 373.34 seconds.
- Frozen P14-DQ environment (`PYTHONHASHSEED=0`): `698 passed`, 113 warnings, 85.01% coverage,
  396.22 seconds. This seed-bound result does not claim Qlib 0.9.7 is hash-order independent.
- The first post-freeze ordinary run had `697 passed, 1 failed`; the failure was
  `test_p14dq_zero_eligible_natural_path_reaches_engineering_acceptance`. That test then passed by
  itself, passed after the preceding autonomous E2E case in the same module, and passed in the final
  full-suite retry above. No code change was made between these executions; the initial failure is
  retained here as unreproduced test evidence.

## Final static gates

- `ruff check .`: PASS.
- `pyright`: PASS, 0 errors, 0 warnings, 0 informations.
- `git diff --check`: PASS; worktree clean at verification.
- `ruff format --check .`: FAIL; exact final output was `2 files would be reformatted, 271 files
  already formatted`. The two files are `src/quantos/application/autonomous_execution.py` and
  `src/quantos/research/qlib/result.py`, both byte-identical to qualified production baseline
  `6573112a7ae46c2c6a5c29f85ff38a2450ca41ba`.

The earlier freeze record states 270 files already formatted. This supplement corrects only that
informational count; the final gate remains blocked for the same two formatter-only changes in the
qualified production baseline. Neither those files nor the formatter gate was changed. Clearing the
block still requires authorizing a production formatting commit and rerunning affected clean-commit
qualifications; no gate exception is applied.
