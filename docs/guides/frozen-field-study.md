# Fixed adjusted-volume study CLI

This is the B1 offline implementation. Actual two-source PIT, translation and signal execution
require A1 and the integrated M1 source. No production preparation or scientific execution was
performed by B1. The design is [P1/R0 §4](../roadmap/quantos-evolution-p1-r0-evidence-2026-10-14.md).

`frozen-field-study-config/v1` accepts only the committed V/P Safe DSL, fixed 2015–2025 design,
immutable snapshot/view, and existing research/cost/backtest/validation policies. Every required
validation and robustness stage remains in `quote_autonomous_workload()`; these units are not
wall time. Primary candidates remain two singletons. Robustness variants do not become additional
main candidates. The paired comparison requires both sources, their 90% defined-date coverage and
`ceil(0.9 × expected dates)` common days; missing/rejected sources stay in the two-request denominator.
`volume_minus_price` and `paired_comparison_status` describe the paired result. Original scientific
outcomes, constant/null values and individual sensitivity statistics remain unchanged.

## Configuration and preparation

After M1, use a clean source workspace and explicit absolute data roots. Construct the input with
`quantos.application.field_study.configuration_from_workspace(study_id=..., workspace=...,
snapshot_path=..., qlib_view_path=..., code_commit_hash=..., lockfile_hash=...)`; save its
`canonical_bytes()` to the preparation input inventory. The helper reads the two B0 YAML files and
existing common configuration files; it never executes science or freezes an Agent proposal.
The commit and lock hash must describe the actual source; do not bind a temporary B1 commit as the
formal final source. Paths and hashes below are placeholders for that later preparation.

```sh
python scripts/frozen_field_study.py prepare \
  --config /durable/input/configuration.json --config-sha256 <configuration-hash> \
  --output-root /durable/study/preparation --execution-root /durable/study/execution
python scripts/frozen_field_study.py status \
  --preparation /durable/study/preparation/preparation.json \
  --preparation-sha256 <preparation-hash>
```

prepare verifies retained data and clean code provenance, creates two singleton family/template/
manifest/scope/budget/request tuples, binds the full calendar, actual purged segment boundaries,
last computable label date, prediction policy, complete workload quote and source inventory/capsule.
It does not construct an execution adapter, build PIT/signal, train, backtest, validate or invoke an
external service. Repeating unchanged preparation reuses identical bytes; changed inputs conflict.
All source/data, preparation and execution roots must be disjoint canonical paths. Full expected
test dates remain in the denominator, including final native NaN-label dates; the computable-label
cutoff is separately retained. status only checks frozen inputs and reports receipt presence as
**unverified**, without science or authority writes.

Each execution has its own `frozen-field-study-execution-scope/v1` and budget. These containers do
not create a ResearchCampaign, Ledger, AgentRun or sealed-access authority. The reused autonomous
request port requires an `agent_run_hash` field: under this profile it binds the explicit
`FIXED_DESIGN_NOT_AGENT_RUN` input-reference hash and is checked as such. No Agent manifest,
generation response, HUMAN_REVIEWED proposal or model opportunity is fabricated.

## Explicit run and recovery

Scientific execution requires separate user authorization for the concrete final preparation and
its full budget, plus an active existing host storage supervisor/lease. The CLI verifies the
prelaunch growth reservation and policy and uses the existing guard's root/capacity checks.
Reserve the entire job, concurrency and failure-cleanup growth, not only the selected candidate.

```sh
# Run this child under the existing hosted_storage_guard.py supervisor.
python scripts/frozen_field_study.py run \
  --preparation /durable/study/preparation/preparation.json \
  --preparation-sha256 <preparation-hash> --candidate V \
  --request-sha256 <V-request-hash> --max-compute-units <V-complete-quote> \
  --expected-new-bytes <whole-job-reservation>
```

Use the same command with candidate P and P's request/quote. `--resume` explicitly continues an
unfinished attempt with the same request, source, budget and execution identity. A completed receipt
is independently verified and reused without Qlib execution. Run intents, returned/exception
observations, existing stage attempts and failures remain durable. `returned.json` does not invent
a process exit; `process_exit=null` is intentional, and the supervisor retains the actual wait/exit.
Source changes require later impact-based integration/preparation rather than editing an old request.

The adapter's new `field_study` argument binds the configuration and profile into execution policy,
PIT policy and request identity. It passes `frozen-field-study/v1` to compact PIT and signal builders
and the minimal Workflow profile argument. Recovery rejects a legacy/v3 PIT mismatch. Legacy calls
retain their original binding hash domain, schemas and source permissions. No new backtest,
portfolio, Qlib model implementation, or Agent execution loop is introduced.

## Prediction sources and comparison

A pinned JSON source-descriptor map contains zero, one or two keys `V` and `P`, each an existing
`PredictionImportSource`. Use actual request/outcome/receipt, resolved input, Workflow reservation
and completion, supervisor management exit, source capsule/inventory, split audit hash, native root,
PIT/signal and data roots. For new field-study executions the `research_policy` descriptor points to
`preparation/configuration.json`: the independent reader checks the whole configuration, execution
bindings and regenerated fixed request, then reproduces the v3 compact PIT through A's reader.
`source-capsule.json` and `source-inventory.json` are produced by prepare. Original model splits,
quality checks, native labels and predictions remain independently verified.

```sh
python scripts/frozen_field_study.py compare \
  --preparation /durable/study/preparation/preparation.json \
  --preparation-sha256 <preparation-hash> \
  --sources /durable/study/prediction-sources.json --sources-sha256 <sources-file-hash> \
  --output-root /durable/study/comparison
```

compare runs the existing native prediction verifier/statistics, publishes small immutable evidence
and a content-addressed report, and never runs an execution adapter or research model. Each supplied
original is built/verified once per operation; local verified facts feed the existing coverage and
common-date calculation. No missing source is filled with zero. Old source descriptors and evidence
continue through their original reader; an old return5 name alone is not reuse permission. B2 must
check actual expression/data/model/splits/implementation/report dependencies and preserve original
execution/receipt identity if existing adoption is applicable. This implementation does not relabel
an old request as a new field-study request.
