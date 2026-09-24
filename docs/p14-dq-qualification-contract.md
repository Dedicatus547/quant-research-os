# P14-DQ data-qualified deterministic campaign qualification contract v1

Status: **DRAFT — requires independent Sol High review before implementation**

Proposed authority: bounded deterministic autonomous Data-qualified engineering evidence for one
explicit immutable live snapshot/Qlib-view lineage.

## 1. Scope

P14-DQ extends the already-qualified P14d-B deterministic campaign path to the single qualified
Tushare snapshot and derived Qlib view listed in this contract. It uses the existing P14b finite
candidate manifest, P14d-A/B orchestrator and execution adapter, PIT evidence builder, native Qlib
Workflow/Simulator path, Validation, immutable ResearchResult, Research Ledger and P14c selection
service. Agent output remains a proposal. Only deterministic `ScriptedAgentDriver` and
`ReplayAgentDriver` are allowed; there is no LLM or live runtime call.

The run is offline after snapshot acquisition. It does not acquire, normalize, amend or replace
market data. A new data revision requires a separate contract review and a new snapshot identity.
P14-DQ is a separate authority track from P14d-C.

## 2. Authority and non-claims

A verified `SUCCEEDED / PASS` P14-DQ report would establish that the bounded deterministic campaign
path was independently reconstructed on the exact qualified snapshot and Qlib-view lineage below,
with identical principal evidence in two independent roots. It would add bounded Data-qualified
autonomous engineering authority for that lineage.

It would not establish or imply:

- live-Agent, production LLM, or FR-03 qualification;
- sealed-confirmation authority, an `OOSAccessed` event, or execution of a sealed trial;
- alpha, profitability, tradability, or investment suitability;
- historical vendor-vintage PIT. The source remains `SINGLE_SOURCE_NON_VINTAGE`;
- unrestricted autonomous research, mutation, crossover, family expansion, arbitrary code, or
  model search;
- any change to historical Validation, Registry, campaign, Ledger or P14c evidence.

The result must not say or imply that P14d-C has passed. P14d-C remains blocked by FR-03
`NO_GO`.

## 3. Exact input bindings

All paths are explicit inputs. Their hashes, manifest contents and exact file sets are authoritative;
directory names alone are insufficient. `latest`, `current`, `auto`, fallback lookup, source refresh,
and silent substitution are forbidden.

| Binding | Required value |
|---|---|
| Snapshot artifact | `artifacts/data/snapshots/sha256-6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9`; snapshot hash `6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9` |
| Snapshot source and data-quality lineage | Dataset `cn-a-share-hs300-eval-2015-2025-v1`; range `2014-11-01` through `2025-12-31`; `source_kind=TUSHARE`; provider `tushare-pro`; quality-report hash `e89933f2db98870e6a1143b6ca546713a2abfae30c0c5f00e79dea1d4d275ed8`; limitations include the qualified `SINGLE_SOURCE_NON_VINTAGE` claim; verify every listed raw/canonical file and reject extra files |
| Derived Qlib view | `artifacts/data/qlib-views/sha256-fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b`; view hash `fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b` |
| View-to-snapshot lineage | `source_snapshot_hash` must equal `6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9`; view-spec hash `b349355d62166327fc67f3911eb60e7bdd9d639e0218799f124dcb3c85581375`; health check and all semantic samples pass |
| Qlib implementation | Version `0.9.7`; source commit `da920b7f954f48ab1bb64117c976710de198373e`; bind the manifest's `dump_bin` and health-check hashes and every view-file hash |
| Prior P2-P7 Data-qualified release | Explicit `artifacts/releases/data-qualified-v0.1-f3fc768/report.json`; file SHA-256 `6e3d6d8f6d1f8c9fd50124ce9cfcd6e22febb0099c05d5931878ca972da0ebca`; canonical report must state `status=PASS`, `release_track=DATA_QUALIFIED`, `data_qualified=true`, and bind the snapshot/view hashes above |
| Implementation | Future clean Git commit; exact `uv.lock`, runtime fingerprint, frozen P14-DQ contract, P14d execution and campaign policies, P14b manifest and P14c selection plan hashes |

The P7 report's existing Validation outcome `SUCCEEDED / REJECT`, Registry status `REJECTED`, and
`SINGLE_SOURCE_NON_VINTAGE` limitation remain visible as historical evidence. P14-DQ does not rerun
or reinterpret that result. The clean implementation's own live-data campaign generates new,
separately bound evidence.

## 4. Frozen campaign and deterministic path

The campaign family and policy set must be frozen before qualification starts. The recommended
minimum is the bounded P14d-B finite family and deterministic budget, with a data-qualified
campaign description, exact input hashes and a calendar window explicitly derived from the verified
Qlib view. The run must bind every date, family/candidate manifest, research/validation/cost/backtest
policy, campaign/Agent budget, compute-accounting policy, Ledger snapshot, ContextPack, selection
plan and execution request. It must not silently retain P14d-B's 77-session synthetic calendar or
synthetic campaign descriptions.

The existing P14b, PIT, Qlib, Validation, ResearchResult, Ledger and P14c services remain the sole
execution authorities. All existing PIT and statistical rules, finite-family denominator,
Validation gates, failure taxonomy and P14c multiple-testing policy remain unchanged. A rejection
or failure is retained with its native status and reason. No policy may be relaxed to create a
`SELECTED` outcome.

The exact market-data window and any P14d-B fixture metadata that must be replaced are frozen by
this contract review before code is written. The draft recommendation is to use the complete
predeclared P7 Data-qualified evaluation range that fits the existing Qlib view and to keep the
P14d-B two-candidate finite family unchanged.

## 5. Qualification outcomes

The report separates the qualification verdict from the campaign's research outcome:

| Layer | Allowed result |
|---|---|
| P14-DQ engineering qualification | `SUCCEEDED / PASS` only when lineage, exact-file, policy, natural-run, independent-root, negative-case and verifier gates all pass; otherwise `FAILED / NOT_EVALUATED`. |
| Natural live-data P14c selection | Record the actual verified P14c result. Both `SUCCEEDED / SELECTED` and `SUCCEEDED / NO_SELECTION` are acceptable evaluated campaign outcomes. Selection is not required for engineering qualification. |
| Natural PIT/execution/selection failure | Preserve the actual `PIT_REJECT`, `EXECUTION_FAILED`, or `FAILED / NOT_EVALUATED` evidence. It cannot be relabelled `NO_SELECTION` or counted as a successful natural campaign. |
| Known injected negative case | The expected fail-closed `FAILED / NOT_EVALUATED` result is negative-case evidence only; identify the injected fault and never present it as market evidence. |

The report records candidate-level Validation verdicts exactly as produced. A `REJECT` is not
rewritten as `PASS`, and a qualification PASS does not change a research or Registry verdict.
P14-DQ uses report-only selection finalization. It may record a verified P14c `SELECTED` report,
but it must close the bounded campaign without appending `SelectionFrozen` or entering
`READY_FOR_SEALED_CONFIRMATION`. This requires a narrow P14-DQ finalization mode in the existing
autonomous handoff or an equivalent thin adapter around it. It never emits `OOSAccessed` and never
authorizes a sealed trial.

## 6. Independent roots and equality

Root-A and root-B execute independently in separate output trees. They share only the immutable
snapshot/view/release-report inputs, clean source tree, lockfile and qualification code. They do
not share campaign/event stores, Agent exchange outputs, execution receipts, ResearchResult or
Validation artifacts, Ledger roots, selection artifacts, loop reports or qualification caches.

Each root records the exact snapshot/view/release lineage and the P14d-B principal domains:
candidate manifest, ContextPack, Agent request/proposal, execution identity/receipt, PIT evidence,
Qlib result, ResearchResult, ValidationReport, CampaignTrial/event chain, final Ledger snapshot,
P14c plan/report, autonomous-loop report, restart/replay behavior and negative-case outcomes.
The qualification principal compares every deterministic authority hash. Only documented runtime
telemetry, temporary paths and wall-clock duration are excluded.

Retain P14d-B's restart checks for an exchange/receipt committed before its trial and for a trial
committed before Ledger reconciliation. Adapt its P14c restart boundary to the report-only policy:
after report publication but before campaign close, restart reuses the report and closes exactly
once without committing `SelectionFrozen`. Replay reuses the immutable exchange and execution
receipt without another Qlib execution.

## 7. Required negative cases

The frozen P14d-B negative, restart and replay coverage is reused where applicable. Each root also
executes and records these P14-DQ cases:

| Case | Expected fail-closed behavior |
|---|---|
| `DQ_SNAPSHOT_HASH_OR_PATH_MISMATCH` | Reject mismatch among explicit hash, artifact directory and verified snapshot manifest. |
| `DQ_SYNTHETIC_OR_ALTERNATE_SNAPSHOT` | Reject any source kind other than Tushare or any substitute snapshot/fixture. |
| `DQ_SNAPSHOT_FILE_TAMPER_OR_EXTRA_FILE` | Reject changed, missing or unexpected source files. |
| `DQ_QUALITY_REPORT_OR_LIMITATION_MISMATCH` | Reject changed/absent DQ report or removal/mutation of `SINGLE_SOURCE_NON_VINTAGE`. |
| `DQ_VIEW_HASH_OR_FILE_SET_MISMATCH` | Reject changed view hash, manifest, listed file or exact file set. |
| `DQ_VIEW_SOURCE_SNAPSHOT_MISMATCH` | Reject a view whose source snapshot hash differs from the required live snapshot. |
| `DQ_QILIB_SPEC_OR_HEALTH_MISMATCH` | Reject altered view spec, Qlib version/source/converter binding, health result or semantic sample. |
| `DQ_UPSTREAM_RELEASE_REPORT_TAMPER` | Reject noncanonical or hash-mismatched P7 report bytes and report/input lineage disagreement. |
| `DQ_UNQUALIFIED_UPSTREAM_RELEASE` | Reject upstream report lacking `PASS / DATA_QUALIFIED / data_qualified=true`. Historical research rejection remains unchanged. |
| `DQ_ROOT_INPUT_SUBSTITUTION` | Reject any root that resolves a different snapshot, view or upstream release report. |
| `DQ_SELECTED_REPORT_HAS_NO_SEALED_HANDOFF` | Preserve a verified `SELECTED` P14c report while rejecting any `SelectionFrozen` event, sealed-trial authorization, or `READY_FOR_SEALED_CONFIRMATION` state. |
| `DQ_QUALIFICATION_BUNDLE_FILE_SET_TAMPER` | Reject missing, extra, noncanonical or hash-mismatched qualification files. |

Negative-case results must include the case identifier, canonical input hash, deterministic observed
outcome/reason, and outcome hash. A caller-supplied PASS is never accepted.

## 8. Content-addressed report and verifier

The P14-DQ report is a new immutable contract and is published at
`artifacts/qualification/p14-dq/sha256-<report-hash>`. It binds code/runtime provenance, frozen
contract and policy hashes, exact upstream lineage, both root evidence trees, full negative/restart/
replay evidence, principal equality, limitations, and an exact-file manifest. The report's hash is
derived from canonical bytes only after every gate succeeds.

Verification rejects wrong report path/hash, noncanonical bytes, missing or extra files, file hash
or size mismatch, dirty/wrong code provenance, unqualified/substituted input lineage, cross-root
principal inequality and replay/rebuild mismatch. It verifies both external source artifacts
against their content-addressed hashes, then rebuilds both roots bottom-up. Snapshot and Qlib-view
references are supplied by explicit paths during verification; paths never select authority by
themselves.

## 9. Remaining contract decisions for independent review

1. Confirm the recommended full P7 Data-qualified evaluation window and the unchanged two-candidate
   P14d-B finite family, or freeze an alternative exact window/family before implementation.
2. Confirm that verification may reference the two existing immutable source directories by
   explicit path and recorded full file manifests, rather than duplicating the full snapshot and
   view inside every qualification bundle.
3. Confirm the qualification treatment of a naturally completed campaign whose individual
   Validation outcome is `REJECT`, while preserving the exact P14c verdict and never requiring
   `SELECTED`. The report-only selection handoff is mandatory regardless of the research outcome.
