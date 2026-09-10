# quant-research-os

Deterministic and auditable A-share quantitative research pipeline. Tushare Pro is the
canonical upstream source; immutable Parquet snapshots are canonical locally; Qlib is reused
for data views, research workflows, models, records, and reference backtests.

The implementation follows [PLAN.md](PLAN.md). Offline engineering and Data-qualified releases
are reported separately: lack of a Tushare token never turns synthetic evidence into live-data
evidence.

Documentation roles:

- [PLAN.md](PLAN.md) is the authoritative roadmap, scope, and acceptance policy.
- [Implementation status](docs/implementation-status.md) tracks the completed P0-P12 stages, the
  current P13 boundary, and the evidence summary.
- [P12 progress](docs/p12-progress.md) records the exchange Evidence boundary, bounded official-source
  probe, and clean-commit reproducibility freeze.
- [P13 progress](docs/p13-progress.md) records the qualified event-feature boundary, synthetic
  native-Qlib bridge freeze, qualification runner, and remaining frozen-Agent benchmark gate.
- [Stage-one architecture review](docs/reviews/stage1-review.md) is the historical review input that shaped
  PLAN v7; its proposed phase numbers are not the current execution plan.
- [P11 architecture review](docs/reviews/p11-review.md) evaluates the post-P11 boundary and records
  the qualified limits and recommended P12-P14 sequencing.
- [Qlib 0.9.7 feasibility record](docs/feasibility/qlib-0.9.7.md) records component evidence and
  explicit runtime limitations.

Links under `artifacts/` refer to workspace-local immutable evidence. That tree is intentionally
excluded from Git because it can contain licensed market data, so those links may be absent in a
fresh clone; the tracked status document retains the content hashes and commands needed to locate
or reproduce authorized evidence.

## Bootstrap

```bash
UV_CACHE_DIR=/tmp/quantos-uv-cache uv sync --frozen
UV_CACHE_DIR=/tmp/quantos-uv-cache uv run quantos doctor
UV_CACHE_DIR=/tmp/quantos-uv-cache uv run pytest
```

P12 deliberately separates network acquisition from authority publication. Run the collector in a
sandbox where only the staging root is writable, then run the publisher with network denied and the
staging directory read-only:

```bash
env -u TUSHARE_TOKEN UV_CACHE_DIR=/tmp/quantos-uv-cache \
  uv run quantos-evidence-collector \
  configs/evidence/collection_example.yaml configs/evidence/collector_v1.yaml \
  --staging-root artifacts/acquisition/evidence

UV_CACHE_DIR=/tmp/quantos-uv-cache uv run quantos-evidence-publisher publish \
  artifacts/acquisition/evidence/sha256-<staging_hash> \
  configs/evidence/availability_v1.yaml configs/evidence/parser_v1.yaml \
  --code-commit-hash <clean-implementation-commit> \
  --runtime-fingerprint-hash <runtime-fingerprint-hash>
```

The commands do not create the OS sandbox themselves. A canonical run must enforce those mounts and
network rules externally. The collector strips `TUSHARE_TOKEN` without reading or logging it; the
publisher accepts only an explicit hash-addressed staging directory and explicit provenance hashes.
SZSE permission remains `UNKNOWN`, so its records fail closed before P13 admission.

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

Run the synthetic P13 EventFeature → EventSignalArtifact → native-Qlib bridge from a clean
implementation checkout:

```bash
UV_CACHE_DIR=/tmp/quantos-uv-cache uv run python scripts/p13_event_signal_feasibility.py
```

The runner publishes only synthetic Offline Engineering evidence. It requires an explicit clean
Git/lockfile provenance, uses the locked official Qlib converter and existing Simulator/Exchange
path, and does not qualify real Evidence or assert a market conclusion.

Run the complete P13 qualification attempt against the human-frozen Evidence Store. The binding
file fixes the Store, Evidence, extracted-text, and benchmark-policy hashes; a mismatched Store
fails closed before Agent execution. The result is an immutable hash-only qualification bundle:

```bash
env -u TUSHARE_TOKEN UV_CACHE_DIR=/tmp/quantos-uv-cache \
  uv run python scripts/p13_qualification.py \
  --store <authorized_store_root>/sha256-<frozen_store_hash> \
  --output-root artifacts/qualification/p13 \
  --agent-output-root artifacts/qualification/p13-agent-runs
```

The Agent can see only the two read-only `quantosP13` MCP tools. `--candidate-store` is available
for an explicitly non-frozen extraction attempt; it never promotes that attempt to downstream
EventFeature, EventStudy, or backtest qualification. Failed Codex transcripts retain only bounded
events and hashes, never stderr text or secrets.

The approved real benchmark is v2 (see
[the approval record](docs/reviews/p13-benchmark-v2-review.md)). To continue deterministic
evaluation from a retained successful extraction, pass `--agent-run` with its explicit
`sha256-<manifest_hash>` directory. The runner verifies the manifest, run specification, transcript,
proposal, instructions and schema bindings against the selected Store and benchmark before
reusing it. This path makes no model call. Deterministic execution requires a clean implementation
checkout; previous failed attempts remain retained separately.

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
  configs/tushare/snapshot.yaml configs/tushare/execution_policy_20260904.yaml \
  --quality-policy configs/tushare/data_quality_20260905.yaml
```

The quality policy is explicit so observed provider precision (for example rounded index-weight
totals) is never handled by an unrecorded tolerance. The command first checkpoints SSE/SZSE
calendars, then builds the complete row-limit-safe plan. Tushare is used only during acquisition;
normalization, DQ, publication, research, and PIT verification are offline.

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

Run the final P7 offline release acceptance slice from a clean Git checkout:

```bash
UV_CACHE_DIR=/tmp/quantos-uv-cache uv run python scripts/release_feasibility.py
```

This executes two independent native-Qlib Snapshot → PIT → SignalArtifact → BacktestArtifact →
G0-G10 → append-only Registry pipelines. It requires exact equality of every principal artifact,
the experiment manifest, and the rebuilt registry index. The retained compact result is
[`artifacts/feasibility/release-p7/report.json`](artifacts/feasibility/release-p7/report.json) and is
explicitly synthetic Offline Engineering evidence, never Data-qualified evidence.

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

Register and inspect already-published validation evidence with explicit immutable paths:

```bash
UV_CACHE_DIR=/tmp/quantos-uv-cache uv run quantos registry register-experiment \
  artifacts/validation/sha256-<validation_report_hash> \
  --event-root artifacts/events \
  --snapshot-path artifacts/data/snapshots/sha256-<snapshot_hash> \
  --qlib-view-path artifacts/data/qlib-views/sha256-<view_hash> \
  --signal-path artifacts/research/signals/sha256-<signal_hash>
UV_CACHE_DIR=/tmp/quantos-uv-cache uv run quantos registry verify artifacts/registry
UV_CACHE_DIR=/tmp/quantos-uv-cache uv run quantos registry list
UV_CACHE_DIR=/tmp/quantos-uv-cache uv run quantos registry show <experiment-or-strategy-id>
```

Registry registration reverifies the ValidationReport and every required explicit source before
writing. Indexes are rebuilt projections, not authority. Strategy lifecycle commands reject
invalid transitions; `registry recover` removes only abandoned atomic-writer temporary files.

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
Qlib-backed pipelines and compares all principal content hashes. P7 adds immutable experiment
manifests, imported OOS event chains, monotonic strategy versions, fail-closed lifecycle
transitions, rebuildable list/get indexes, registry CLI operations, tamper/partial-write recovery
tests, and a two-run native-Qlib synthetic Release E2E. P0-P7 Offline Engineering and
Data-qualified DoD are complete on implementation commit
`f3fc7684d09ac351d72d76b2a0370c58bec8589c`. P8 Agent Boundary & Threat Hardening is also
complete: untrusted ingress is capability- and resource-bounded, authority lookup is hash-only and
root-confined, artifact reads reject links, and concurrent immutable/Registry writers fail closed.
P9 Research Semantic Contracts is complete: Agent output remains proposal-only, evidence admission
and campaign/OOS governance fail closed, and the five admitted DSL v2 operators are bound to
official Qlib semantics and the full PIT/Signal reproducibility chain. P10 GPT + Codex Capability
Spike is complete with a 9/9 hard-capability Go for the frozen synthetic configuration. P11 Quant
Research MCP + Offline Proposal E2E is also complete; it qualifies typed application-service
facades and a code-defined structured-fixture chain, not a production stdio/JSON-RPC transport or
an Agent-generated Data-qualified research run. P12 Real-world Evidence Acquisition is complete;
P13 Qualified Event Feature is the current implementation entry. P13 now has a native-Qlib synthetic
bridge freeze, a strict hash-bound qualification runner, and retained non-frozen Agent attempts;
the approved v2 Store, admitted real Agent proposal and clean-copy double-root qualification
now pass. See [the v2 freeze record](docs/p13-v2-freeze.md) for exact hashes and limitations.
Existing admitted DSL propagation and an immutable Qlib ResearchResult are parallel factor-research
prerequisites for P14 rather than substitutes for P12/P13.
See [`docs/implementation-status.md`](docs/implementation-status.md) and
[`docs/p8-security.md`](docs/p8-security.md),
[`docs/p9-research-semantics.md`](docs/p9-research-semantics.md), and
[`docs/adr/0001-gpt-codex-harness.md`](docs/adr/0001-gpt-codex-harness.md). The locked Qlib
feasibility record remains at
[`docs/feasibility/qlib-0.9.7.md`](docs/feasibility/qlib-0.9.7.md).

The 2026-09-05 bounded capability probe confirmed all 12 probed endpoints, including
`index_weight` and `stock_st`. The account-qualified execution policy is fixed at the verified
official 200 requests/minute tier. All 13,614 acquisition requests completed on the first attempt;
the immutable snapshot `6297a968...e3dd9` passed all 16 DQ gates, and its official Qlib 0.9.7 view
`fc809bed...85716b` passed the health check, exact-file verification, and all 668 semantic samples.
The normalizer preserves raw provider values, fills only empty `stk_limit.pre_close` values from the
identical same-key `daily.pre_close`, and rejects nonempty cross-endpoint mismatches. Qlib semantic
readback is checked exactly against the official converter's binary32 representation.

The complete P3-P7 qualification was run from the frozen implementation commit with the explicit
content-addressed snapshot and a commit-specific output root:

```bash
UV_CACHE_DIR=/tmp/quantos-uv-cache uv run quantos release data-qualified \
  artifacts/data/snapshots/sha256-6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9 \
  --output-root artifacts/releases/data-qualified-v0.1-f3fc768
```

Its authoritative summary is
[`artifacts/releases/data-qualified-v0.1-f3fc768/report.json`](artifacts/releases/data-qualified-v0.1-f3fc768/report.json):
engineering release `PASS / data_qualified=true`, ValidationReport `SUCCEEDED / REJECT`, and
Registry strategy state `REJECTED`. The only rejected candidate soft threshold is annualized
turnover (`29.5344 > 12`); this is retained research evidence, not an engineering failure. Both
independent pipelines reproduced the baseline SignalArtifact `dba57f2a...e51e`, BacktestArtifact
`ec318505...4270`, ValidationReport `553d49a7...855a7`, and Registry index `04a276a2...396a`
exactly. All live evidence retains `SINGLE_SOURCE_NON_VINTAGE`; Rank IC/ICIR remain unclaimed until
an immutable Qlib ResearchResult adapter exists.
