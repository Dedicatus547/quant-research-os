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

## Qlib execution race resolution and final RC qualification

This section is an append-only update. The preceding results remain the record of the formatter-only
baseline and the evidence available at that time. The first full-suite Qlib failure was later
reproduced and diagnosed; its engineering failure classification was retained.

- Starting formatter baseline: `ea2573ffd1d72e3f1f28390550e174338d88dda9`.
- Nested exception: `ValueError("Metric 'l2.valid' is malformed. No data found.")` from MLflow
  `FileStore` while Qlib `SignalRecord.generate()` logged a prediction artifact.
- Cause: Qlib queued the `l2.valid` metric asynchronously during `LGBModel.fit`; the synchronous
  artifact logging path read the metric file before the queued write completed. Full-suite thread
  scheduling exposed the race. One pre-fix 75-collected-test prefix plus target reproduced it; the
  prefix was schedule-sensitive and no individual polluting test or cumulative resource threshold
  was found.
- Resource checks showed 9 file descriptors before and after execution against an
  `RLIMIT_NOFILE` soft/hard limit of 10240/1048576. CWD and `MLFLOW_ALLOW_FILE_STORE` were restored,
  no MLflow run remained active, and temporary worker-thread counts showed no cumulative growth.
- Minimal correction: production commit `e318dc450e5c02f1120da7644250767bf682b6f9` drains Qlib's
  async metric queue after model fitting and before artifact generation. The regression test proves
  the metric write finishes before `SignalRecord` emits artifacts. No statistical or authority
  semantics changed; `QLIB_EXECUTION_FAILED` remains fail-closed.
- On `e318dc4`, the target passed 10/10 isolated repetitions and the ordered 75-item prefix plus
  target passed (76 tests). The ordinary full suite passed with 699 tests; `PYTHONHASHSEED=0` full
  suite also passed with 699 tests and 85.01% coverage. Ruff format/check, Pyright, and
  `git diff --check` passed.
- Fresh P14d-B report `41a27c6fd2b5f0f522a1fcae13424b924b9cdc2fa4e8aa0df24ff12d79fadc71` and
  P14-DQ report `f912cb0b376c981c94dae267cb0b16a4d2f1e0a52edcd36d08f938f92964d38a` both bind
  `e318dc4`; the retained P14c verifier and both new full qualification verifiers passed.
- The complete freeze and authority matrix are in the
  [P14 RC v1 final freeze record](p14-rc-v1-final.md). Its enclosing commit is documentation and
  evidence only.
