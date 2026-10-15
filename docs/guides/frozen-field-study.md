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

## Origin-preserving recorder recovery

A recorder implementation change requires a successor source/input identity. The old configuration,
preparation, failed attempt, successful stage checkpoints and artifact manifests remain immutable.
The recovery input is `FieldStudyRecoveryOrigin`: pin the original preparation, reconstructed clean
checkout, complete old/new source-file differences, and the original request, successful baseline
PIT/signal/backtest checkpoints and artifacts. Bind the original failed Workflow completion and its
actual guard exit/prelaunch/request intent. The historical capsule retains its original workspace;
the reconstructed path is an explicit mapping in the new declaration.

Only the reviewed Workflow recorder and field-study recovery wiring, plus documentary/test files,
may differ. Scientific configuration, source lock, data, PIT/expression/signal/backtest/validation
implementations must remain unchanged. Both complete Git inventories and clean checkouts are checked.
The successor configuration differs only in source/workspace/study identity. Freeze that input only
after the final integration commit exists; development fixtures do not create production preparation.

The existing prepare command accepts paired `--origin <file>` and `--origin-sha256 <hash>`. It emits
`frozen-field-study-preparation/v2` and `source-adoption.json`, binding both old/new requests, source
capsule/inventory and independent successor roots. Legacy v1 configurations/preparations keep their
original bytes and request binding domain. Prepare/status do not activate transfers or run science.

Before running either successor, explicitly invoke `supersede --preparation <file>
--preparation-sha256 <hash>`. This is a management operation: it takes the existing global flock,
checks original cleanup and producer proofs, locks both original opportunity identities, then appends
immutable supersession records under the fixed data locator's sibling `field-study-continuity/`.
It never writes predecessor evidence. Both records must exist before either successor may run;
idempotent re-entry is allowed, a conflicting successor or output root is rejected. Current entrypoints
reject superseded original requests. Retained historical executables are evidence, not another
permitted launch path.

Transfers retain the original V/P opportunities, one logical execution and 18 complete policy units
each (36 total), with the unchanged 8 GiB complete-job estimate. Unknown original consumption remains
unknown; storage recovery envelopes grant no extra computation or candidates. The adapter holds an
opportunity lease throughout execution, retaining the existing trial index, checkpoint and receipt
mechanisms. Discovery/SDK source-adoption parameters remain forbidden in the field-study profile.

Only baseline PIT, signal and backtest are adopted. PIT reuses the completed producer proof after
full source/dependency, exact-byte, schedule and policy checks. Signal/backtest call the existing
`adopt_verified` APIs and publish `NativeArtifactAdoptionReceipt` records; native bytes stay identical,
metadata rebindings pass `verify_adoption_bindings`, and parent qualification is never transferred.
The incomplete Workflow runs in the successor identity. Existing parameter/cost/subperiod/reproduction
and validation obligations remain in the quote; no failed Workflow checkpoint becomes success.

For prediction import, the research-policy descriptor still points to configuration.json. The reader
independently checks the v2 preparation/declaration, source delta and reconstructed checkout,
supersession, old successful stages, and both actual native receipts; outcome evidence must retain
those receipt hashes. Its normal data/PIT/native-statistic predicates remain in force. Missing,
misplaced, changed or foreign receipts are rejected, including recovery after an orphan publication.
New recovery failures also retain completed adoption hashes in their execution evidence. For retained
historical failures that omitted those hashes, the reader first verifies both native receipts under
the same exact source/request/artifact predicates, then requires pinned original outcome and execution
receipt, request-bound failed Workflow reservation/completion and immutable failure evidence at their
actual successor paths. This narrow failure path preserves the original outcome and receipt bytes;
it grants no successful Workflow or qualification and does not relax the successful-outcome check.
Actual run/resume/compare still need the existing guard/global lease and fresh host capacity,
reservations, cleanup and scratch observations under the retained authorization.

The transparent field-study wait observer publishes `field-study-cli-process-exit/v1` as
sorted, indented JSON with a final newline. The prediction reader accepts those exact pinned
bytes only for the field-study management-exit input, with the fixed protocol fields, actual
wait, matching integer exit codes and finite nonnegative usage. It does not rewrite the
observation into canonical JSON. Requests, receipts, Workflow metadata and other sources
still require their original canonical encoding; legacy profiles keep that requirement too.
