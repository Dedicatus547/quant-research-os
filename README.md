# quant-research-os

Deterministic and auditable A-share quantitative research pipeline. Tushare Pro is the
canonical upstream source; immutable Parquet snapshots are canonical locally; Qlib is reused
for data views, research workflows, models, records, and reference backtests.

The implementation follows [PLAN.md](PLAN.md). Offline engineering and Data-qualified releases
are reported separately: lack of a Tushare token never turns synthetic evidence into live-data
evidence.

## Bootstrap

```bash
UV_CACHE_DIR=/tmp/quantos-uv-cache uv sync --frozen
UV_CACHE_DIR=/tmp/quantos-uv-cache uv run quantos doctor
UV_CACHE_DIR=/tmp/quantos-uv-cache uv run pytest
```

Build and verify the deterministic, network-free synthetic snapshot vertical slice:

```bash
UV_CACHE_DIR=/tmp/quantos-uv-cache uv run quantos snapshot build-synthetic \
  tests/fixtures/synthetic_snapshot
UV_CACHE_DIR=/tmp/quantos-uv-cache uv run quantos snapshot verify \
  artifacts/data/snapshots/sha256-<snapshot_hash>
```

After caching the locked official Qlib source, build and verify its derived view:

```bash
UV_CACHE_DIR=/tmp/quantos-uv-cache uv run quantos qlib build-view \
  artifacts/data/snapshots/sha256-<snapshot_hash>
UV_CACHE_DIR=/tmp/quantos-uv-cache uv run quantos qlib verify-view \
  artifacts/data/qlib-views/sha256-<view_hash>
```

Run an experiment-time lineage/PIT audit and publish its immutable evidence:

```bash
UV_CACHE_DIR=/tmp/quantos-uv-cache uv run quantos pit audit \
  artifacts/data/snapshots/sha256-<snapshot_hash> canonical-pit-request.json
```

The request contains selectors, a safe expression, schedule, and versioned operator delays. Source
timestamps and membership evidence are never accepted from the caller; they are resolved from the
verified snapshot. Proposal/unbound reports cannot be published as validated evidence.

The live acquisition command additionally requires an explicit, account-qualified execution
policy—there is intentionally no guessed rate-limit default:

```yaml
schema_version: tushare-execution-policy/v1
policy_id: account-qualified-YYYYMMDD/v1
requests_per_minute: <verified-account-limit>
max_attempts: 3
retry_min_seconds: 1.0
retry_max_seconds: 8.0
```

```bash
UV_CACHE_DIR=/tmp/quantos-uv-cache uv run quantos snapshot build-tushare \
  configs/tushare/snapshot.yaml execution-policy.yaml
```

It first checkpoints SSE/SZSE calendars, then builds the complete row-limit-safe plan. Tushare is
used only during acquisition; normalization, DQ, publication, research, and PIT verification are
offline.

Cache and verify the official Qlib tools omitted from the wheel, then run the offline spike:

```bash
UV_CACHE_DIR=/tmp/quantos-uv-cache uv run python scripts/bootstrap_qlib_tools.py
UV_CACHE_DIR=/tmp/quantos-uv-cache uv run python scripts/qlib_feasibility.py
```

From a clean Git checkout, publish the canonical synthetic P4 SignalArtifact feasibility slice:

```bash
UV_CACHE_DIR=/tmp/quantos-uv-cache uv run python scripts/signal_feasibility.py \
  artifacts/data/snapshots/sha256-<snapshot_hash> \
  artifacts/data/qlib-views/sha256-<view_hash> \
  --output-root artifacts/research/signals
```

This runner accepts only an explicitly synthetic snapshot. It verifies the clean Git commit and
`uv.lock`, constructs member-by-member snapshot-bound PIT evidence, executes the safe expression
through Qlib, and publishes an exact-file-set immutable artifact. Live/Data-qualified execution is
a separate later run.

Run the complete P5 artifact chain against the dedicated signal/execution/closeout fixture:

```bash
UV_CACHE_DIR=/tmp/quantos-uv-cache uv run python scripts/backtest_feasibility.py
```

The runner requires a clean Git checkout and the locked Qlib source. It performs Snapshot → Qlib
view → PIT → SignalArtifact → Qlib reference backtest → BacktestArtifact twice and rejects any hash,
schema, schedule, arithmetic, trade-unit, no-short, or exchange-code mismatch.

Run the native-Qlib P6 engineering acceptance slice from a clean Git checkout:

```bash
UV_CACHE_DIR=/tmp/quantos-uv-cache uv run python scripts/validation_feasibility.py
```

This runner performs two independent Snapshot → official Qlib converter/health check → PIT →
SignalArtifact → Qlib backtest/robustness grid → G0-G10 → ValidationReport pipelines. It requires
exact equality for the snapshot, view, baseline signal, baseline backtest, and ValidationReport
content hashes. The compact synthetic policy deliberately uses windows 1/3 and top-k 1/2; the
fixture's suspended session makes window 2 non-finite, which remains a hard execution rejection
rather than being imputed. The latest compact hash summary is retained at
[`artifacts/feasibility/validation-p6/report.json`](artifacts/feasibility/validation-p6/report.json).

For an already published, explicit SignalArtifact and matching view, the production CLI is:

```bash
UV_CACHE_DIR=/tmp/quantos-uv-cache uv run quantos backtest run \
  artifacts/research/signals/sha256-<signal_hash> \
  artifacts/data/qlib-views/sha256-<view_hash> \
  configs/backtest/cost_v1.yaml configs/backtest/policy_v1.yaml
UV_CACHE_DIR=/tmp/quantos-uv-cache uv run quantos backtest verify \
  artifacts/research/backtests/sha256-<backtest_hash>
```

The command never resolves mutable aliases such as `latest`, `current`, or `auto`; the resolved
experiment is loaded from and verified against the explicit SignalArtifact.

Validate a production artifact set through G0-G10 in one CLI command:

```bash
UV_CACHE_DIR=/tmp/quantos-uv-cache uv run quantos experiment run \
  configs/research/hs300_momentum_v1.yaml \
  configs/validation/research_candidate_v1.yaml \
  configs/research/policy_v1.yaml \
  validation-run-locators.yaml
UV_CACHE_DIR=/tmp/quantos-uv-cache uv run quantos experiment verify \
  artifacts/validation/sha256-<validation_report_hash>
```

`validation-run-locators.yaml` is a runtime-only map to explicit `sha256-<hash>` directories. It
contains the verified snapshot/view, baseline SignalArtifact/BacktestArtifact, an independently
executed reproduction BacktestArtifact, the complete 1.0x/1.5x/2.0x cost grid, the configured
momentum-window/top-k grid, and every configured subperiod artifact. Locator paths are never
treated as evidence: G0-G10 reopen and content-verify every target. `--development` permits a
clearly marked `canonical: false` report; it does not disable artifact, PIT, robustness, or
reproducibility checks.

`experiment run` is intentionally a validation command, not a hidden artifact builder: signal and
backtest variants must already have been published by the Qlib-backed research/backtest services.
The P6 feasibility runner above is the executable full-chain engineering proof. ValidationReport
v2 embeds a separately hashed runtime fingerprint covering Python, OS/kernel, architecture, libc,
and the locked numeric/runtime packages. Rank IC/ICIR thresholds currently fail closed because the
factor path has no immutable Qlib ResearchResult adapter; the v0.1 validation policies therefore do
not enable those thresholds.

Python 3.11 and all dependency versions are locked by `uv.lock`. Tests deny network access by
default through `pytest-socket`.

## Security boundary

- Provide the Tushare token only through `TUSHARE_TOKEN`.
- Snapshot acquisition is the only layer allowed to use the network.
- Research, backtest, validation, and registry code must run offline.
- Local Qlib/MLflow state is a runtime recorder, not the artifact or registry authority.

## Current implementation status

P0/P1 provide the project baseline, deterministic contracts, content hashing, atomic publication,
immutable events, strict configuration, bounded redacted capability evidence, and separate
engineering/research validation policies. P2 covers all nine required endpoint shapes, a resumable
SDK acquisition plan, raw/canonical layers, explicit unit/time normalization, lifecycle and sparse
status gates, immutable snapshot publication/diff/verification, and a Qlib view policy using only
the locked official converter. P3 binds PIT lineage to verified snapshot rows and hard-rejects fake
hashes, incomplete windows, unknown/missing evidence, invalid memberships, and implicit operator
delays. P4 adds official-Qlib expression translation, historical-universe resolution, complete PIT
evidence bundles, strict code/lock provenance, immutable SignalArtifact publication, and a real
`DatasetH`/`LGBModel`/Workflow/Record Template smoke with purged split boundaries. P5 adds the
verified SignalArtifact-to-Qlib reference backtest, explicit Exchange/Simulator/Position/order
generator configuration, immutable normalized result tables, six reconciliation gates, constraint
golden cases, and deterministic `backtest run/verify` commands. P6 adds the offline G0-G10
validation orchestrator, versioned robustness axes and soft thresholds, OOSAccessed events,
independent-run comparison, immutable ValidationReport publication, and deterministic
`experiment run/verify` commands. Its native feasibility runner executes two independent complete
Qlib-backed pipelines and compares all principal content hashes. P7 remains unimplemented.
See [`docs/implementation-status.md`](docs/implementation-status.md) and
[`docs/feasibility/qlib-0.9.7.md`](docs/feasibility/qlib-0.9.7.md).

The token is configured and the bounded capability probe has run, but the account was denied the
required `index_weight` endpoint; live release is therefore hard-blocked pending account access and
an account-qualified rate policy. The locked Qlib source cache and current synthetic derived view
are verified. This workspace is still not a usable Git repository, so canonical commit provenance
also remains blocked.
