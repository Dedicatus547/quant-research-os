# P14-DQ v3 reproducibility environment amendment — draft

Status: **DRAFT — independent review required before it can support a qualification run**

This amendment supplements the approved v3 engineering acceptance contract (SHA-256
`563b1c44ff8e3b87822902c1f70183de2ddd97b007550f2028990bb37f858e17`). It does not edit
those bytes and does not change any research, Validation, PIT, P14c, statistical, family,
manifest, denominator, policy or sealed/OOS semantics. It binds the process environment in
which P14-DQ reproducibility is asserted.

## 1. Observed reproducibility defect

The formal qualification from commit `1d4c995e7266266b475af3ce86f4e0150005063a` produced an
engineering `SUCCEEDED / PASS` report
(`sha256-10cf6e09f32e39716daea7f48e565ad2798f8a0362eb4e81faaed04a14fc92a3`), but the
mandatory full bottom-up verifier rebuilt both roots and refused them:
`P14-DQ roots did not reproduce from explicit external inputs`.

Diagnosis over the retained evidence:

- Agent exchanges, signal artifacts and `ResearchResult` hashes reproduce exactly.
- `order-indicators.parquet` and `trade-indicators.parquet` reproduce byte for byte, so the
  trading decisions are identical.
- Only valuation-derived outputs diverge: `portfolio.parquet` `account`/`value` by at most
  `5.8e-10`, `positions.parquet` `portfolio_weight` by at most `1.7e-17`, and
  `risk-metrics.parquet` by about `8.9e-16`.
- Re-executing one frozen candidate in separate processes yields different backtest artifact
  hashes, and the result is fixed by `PYTHONHASHSEED`: two independent processes with
  `PYTHONHASHSEED=0` produced the identical artifact
  `f50eda7406431b3eab1f8f155bb85853744fd9463ff93706af47400e54691182`, while
  `PYTHONHASHSEED=1` produced `fa00f3371641f7f23574ebe8abf3a1950b944d2ad5e467488aee5ebb26990c47`.

The cause is in the reused third-party engine, Qlib 0.9.7
(`qlib/backtest/position.py`): `Position.calculate_stock_value()` sums per-instrument values
over `list(set(self.position.keys()) - {...})`. Set iteration order depends on the interpreter
hash seed and floating-point addition is not associative, so the reported account value
carries last-bit noise that differs per process. Rule 1 of `AGENTS.md` requires reusing the
Qlib engine rather than implementing a project-owned backtest or portfolio accounting engine,
so this amendment freezes the process environment instead of re-implementing valuation.

## 2. Frozen interpreter environment

P14-DQ qualification and verification must execute Qlib in an interpreter started with

```text
PYTHONHASHSEED=0
```

and with hash randomization therefore disabled. A process that cannot prove at entry that it
was started this way must refuse to run rather than silently produce environment-dependent
evidence. A command-line invocation that needs the frozen seed must re-execute itself in a
controlled way before any Qlib execution, and the re-execution must not be able to loop.

Setting the variable inside an already running process is not sufficient and is not
accepted: CPython reads it before interpreter start.

## 3. Runtime environment record and binding

The qualification bundle gains an immutable `runtime-environment.json` record carrying the
frozen seed, the disabled-hash-randomization fact, the existing runtime fingerprint hash and
the hash of this amendment. The qualification report binds that record, its schema version is
raised accordingly, and both the bundle integrity check and the full bottom-up verifier must
reconstruct and compare it. The pre-existing `runtime-fingerprint/v1` record keeps its schema
and parsing; no historical schema is rewritten.

Engineering `SUCCEEDED / PASS` is invalid if the runtime environment record is missing,
tampered with, inconsistent with the report, or records a seed other than the frozen one.

## 4. Acceptance scope and non-claims

Reproducibility is asserted only for the exact frozen snapshot/view lineage, the exact clean
implementation commit and the frozen runtime environment defined here, including the seed. It
is explicitly **not** a claim that the reused Qlib engine is hash-order independent, and it is
**not** a claim that artifacts equal those produced under any other interpreter hash seed.

This amendment adds no alpha, profitability, candidate-selection, sealed-confirmation,
live-Agent, FR-03 or vendor-vintage PIT authority.

## 5. Status of previously published evidence

The bundle `sha256-10cf6e09f32e39716daea7f48e565ad2798f8a0362eb4e81faaed04a14fc92a3` is
**not accepted** as a qualification artifact: its mandatory full bottom-up verification
failed with a root reproducibility mismatch, which the runner of that commit reported as
`ARTIFACT_CORRUPTED` because the generic classification was in force then. It is retained
unmodified as immutable evidence of the defect, and the earlier failed attempts remain
immutable failures.

That bundle predates this amendment, so it cannot be re-verified under it: the report schema
was raised, and a pre-amendment report must never be presented as covered by this amendment.
Reproducibility mismatches produced under this amendment must be reported as
`REPRODUCIBILITY_MISMATCH`, not as generic artifact corruption.

## 6. Qualification gate

Nothing here grants qualification. A new clean-commit independent double-root qualification,
the full bottom-up verifier and an independent GPT-6 Sol High evidence review must all pass on
a bundle produced under this amendment before P14-DQ holds any Data-qualified engineering
authority.
