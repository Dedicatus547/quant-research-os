# P14-DQ data-qualified deterministic campaign qualification contract v1

Status: **DRAFT — requires independent Sol High review before implementation**

Proposed authority: bounded deterministic autonomous Data-qualified engineering evidence for one
explicit immutable live snapshot/Qlib-view lineage.

## 1. Scope

P14-DQ qualifies the existing bounded P14 campaign path on the exact qualified Tushare snapshot
and derived Qlib view in this contract. It reuses the existing P14b deterministic enumerator,
P14d-A/B campaign, Agent, Ledger and execution services, and the unchanged P14c selection service.
It uses only `ScriptedAgentDriver` and `ReplayAgentDriver`; Agent output remains a proposal. No LLM
or live Agent runtime is invoked. P14-DQ uses the report-only finalization profile in §7 instead
of the normal P14d autonomous sealed-confirmation handoff.

The run is offline after snapshot acquisition. It does not acquire, normalize, amend, rebuild or
replace market data. A new data revision requires a separate contract review and a new snapshot
identity. P14-DQ is separate from P14d-C.

## 2. Authority, limitations and non-claims

A verified `SUCCEEDED / PASS` report establishes bounded deterministic engineering qualification
for the exact snapshot/view lineage below, including identical principal evidence in two
independent roots. It does not establish research performance or grant authority beyond that
lineage.

Every P14-DQ report freezes and carries this P14-DQ-specific limitation set:

```text
DQ_EXACT_SNAPSHOT_VIEW_LINEAGE_ONLY
DQ_LIVE_AGENT_RUNTIME_NOT_QUALIFIED
DQ_NO_ALPHA_OR_PROFITABILITY_CLAIM
DQ_NO_OOS_ACCESSED
DQ_NO_UNRESTRICTED_AUTONOMOUS_RESEARCH
DQ_SCRIPTED_REPLAY_AGENT_ONLY
DQ_SEALED_CONFIRMATION_NOT_EXECUTED
FR_03_NO_GO
SINGLE_SOURCE_NON_VINTAGE
```

These limitations mean deterministic scripted/replay Agent drivers only; live Agent runtime is
unqualified; FR-03 remains `NO_GO`; the source is single-source and non-vintage; sealed
confirmation is not run or authorized; no `OOSAccessed` event is permitted; no alpha or
profitability claim is made; authority is limited to this exact snapshot/view lineage; and
unrestricted autonomous research is not authorized. P14-DQ uses qualified live market data, so
its limitations must not imply that the run used no real market data. Do not carry forward
`P14D_A_OFFLINE_ORCHESTRATION_EVIDENCE_ONLY`,
`P14D_B_DOUBLE_ROOT_QUALIFICATION_PENDING`, or
`REAL_MARKET_CONCLUSION_NOT_ESTABLISHED` as P14-DQ limitations.

The result does not establish historical vendor-vintage PIT, tradability, investment suitability,
live-Agent/production-LLM qualification, sealed-confirmation authority, or any change to prior
Validation, Registry, campaign, Ledger, P14c or P14d-B evidence. It must not imply that P14d-C has
passed.

## 3. Exact input bindings and time semantics

All input paths are explicit content-addressed paths. A directory name alone is not authority;
the supplied path, canonical manifest, content hash, complete file inventory and verified lineage
must agree. `latest`, `current`, `auto`, fallback lookup, silent substitution, network refresh,
reacquisition and data/view rebuild are forbidden.

| Binding | Required value |
|---|---|
| Snapshot artifact | `artifacts/data/snapshots/sha256-6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9`; snapshot hash `6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9` |
| Snapshot source and quality lineage | Dataset `cn-a-share-hs300-eval-2015-2025-v1`; acquisition range `2014-11-01` through `2025-12-31`; `source_kind=TUSHARE`; provider `tushare-pro`; quality-report hash `e89933f2db98870e6a1143b6ca546713a2abfae30c0c5f00e79dea1d4d275ed8`; limitation `SINGLE_SOURCE_NON_VINTAGE` |
| Frozen P7 research policy | `train=2015-01-01..2019-12-31`; `validation=2020-01-01..2022-12-31`; `test=2023-01-01..2025-12-31`; bind the exact policy bytes and hash |
| Campaign periods | `campaign.development=2020-01-01..2022-12-31`; `campaign.validation=2023-01-01..2025-12-31`; `campaign.validation` must equal `research_policy.test` exactly, as required by `QuantosResearchExecutionAdapter` |
| Sealed-confirmation placeholder | `2026-01-01..2026-01-30`, retained because the existing campaign schema requires it; it is an unvisited placeholder only |
| Derived Qlib view | `artifacts/data/qlib-views/sha256-fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b`; view hash `fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b` |
| View-to-snapshot lineage | `source_snapshot_hash` equals `6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9`; view-spec hash `b349355d62166327fc67f3911eb60e7bdd9d639e0218799f124dcb3c85581375`; health check and semantic samples pass |
| Qlib implementation | Version `0.9.7`; source commit `da920b7f954f48ab1bb64117c976710de198373e`; bind `dump_bin`, health-check and converter hashes plus every view-file hash |
| Prior P2-P7 Data-qualified release | Explicit `artifacts/releases/data-qualified-v0.1-f3fc768/report.json`; file SHA-256 `6e3d6d8f6d1f8c9fd50124ce9cfcd6e22febb0099c05d5931878ca972da0ebca`; canonical report must state `status=PASS`, `release_track=DATA_QUALIFIED`, `data_qualified=true`, and bind the snapshot/view hashes above |
| Implementation | Future clean Git commit; exact `uv.lock`, runtime fingerprint, frozen P14-DQ contract, P14d execution/campaign policies, P14b manifest and P14c selection-plan hashes |

The P14c selection calendar is mechanically exported from the bound, verified Qlib view's real
trading sessions in the inclusive range `2023-01-01..2025-12-31`. The sorted unique dates, view
hash and exact start/end are frozen in the P14c plan before any trial. Calendar dates must not be
fabricated, truncated to P14d-B's synthetic 77 sessions, or supplied independently of the view.

The P7 report's existing Validation outcome `SUCCEEDED / REJECT`, Registry status `REJECTED`, and
`SINGLE_SOURCE_NON_VINTAGE` limitation remain historical evidence and are not rerun or
reinterpreted. P14-DQ binds that release report and creates separate live-data campaign evidence.

### External immutable artifact verification

The snapshot and Qlib view remain external immutable artifacts and are not copied into the
qualification bundle. At run and full-verification time, the caller supplies their explicit
content-addressed paths. The path does not confer authority by itself. The verifier must run the
existing `verify_snapshot` and `verify_qlib_view`, verify each complete manifest and every listed
file hash, reject extra, missing or tampered files, and bind the view to the exact snapshot. No
network retrieval, reconstruction, or fallback is permitted.

The qualification bundle records the snapshot and view identities/hashes, source and view
lineage, quality-report binding, P7 Data-qualified release-report binding, canonical manifests,
and full manifest/file-set verification evidence. It contains no full market-data file copies.

Two verification levels are distinct:

- **Bundle integrity verification** verifies the qualification bundle's own canonical bytes,
  exact file set and hashes, plus the upstream identities, manifests and hashes recorded inside
  it. It does not establish that external snapshot/view directories are currently present or
  intact.
- **Full bottom-up qualification verification** additionally requires the external
  content-addressed snapshot/view directories and explicitly re-runs both existing artifact
  verifiers over every file before rebuilding the qualification roots. Missing external inputs
  make this level fail; it never fetches or rebuilds them.

## 4. New P14-DQ family and deterministic manifest

P14-DQ must not reuse the P14d-B synthetic `ResearchFamilySpec` or candidate-manifest identity.
It reuses the same frozen search-space shape, but creates a new P14-DQ family identity and
deterministically re-enumerates its manifest with the existing P14b enumerator.

Freeze the new family as follows:

| Field | P14-DQ value |
|---|---|
| `family_id` | `p14-dq-live-data-engineering-v1` |
| `research_question` | `Can the bounded deterministic P14-DQ scripted/replay campaign reproduce identical principal engineering evidence in independent roots on the exact Data-qualified snapshot and derived Qlib view using the predeclared two-candidate adjusted-close DELTA family?` |
| `hypothesis_hash` | `147495c5a1f583aa8cd58c11d3de84ee1612d7149495ffed8c5257f43d4231a3`; SHA-256 of canonical JSON bytes for `{"claim":"The bounded deterministic P14-DQ scripted/replay campaign reproduces identical principal engineering evidence in independent roots on the exact qualified Tushare snapshot and derived Qlib view using the predeclared two-candidate adjusted-close DELTA family."}` |
| Template/search expression | `template_id=p14-dq-adjusted-close-delta-template-v1`; `template_hash=a9df666299ac2feac2a50608d76b568bf6bc31bbfaaa1d98c0c60a4a6a69158a`; expression `adjusted_close -> DELTA(window)` |
| Allowed operator set | Unchanged: `FIELD`, `DELTA` |
| Parameter space | Unchanged: `window ∈ {2, 3}` |
| Declared candidate count | `2` |
| Frozen family hash | `fbc0a11c08e502eaeb8abe5f7f9f5db390d9296a24a34607cd404e3655991bbb` |
| P14b deterministic manifest | `manifest_hash=b5fcc8e59f2bc9e63a307a512254dd0a165c7c50ea5904c0b4b546543a52d4ae`; `window=2` candidate hash `b7ca426ad868e15827365aa2bfcceb20870893a91add47713ff88dc2a43d444f`; `window=3` candidate hash `f6941537f61ba9cde4c0e866d365919a0fc3dda96c30304c1378bfc069364e96` |

The frozen `ResearchFactorTemplateSpec` has `schema_version=research-factor-template/v1`,
`expression_schema_version=safe-qlib-expression/v2`, `input_lag_trading_days=0`, and
`output_node_id=factor`. Its ordered nodes are: (1) `ResearchFactorTemplateNode` with
`schema_version=research-factor-template-node/v1`, `node_id=price`, `operator=FIELD`,
`inputs=()`, `field_name=adjusted_close`, `window=None`; (2) a node with the same node schema,
`node_id=factor`, `operator=DELTA`, `inputs=(price,)`, `field_name=None`, `window=None`. Its sole
parameter slot is `ResearchTemplateParameterSlot(schema_version=research-template-parameter-slot/v1,
name=window, node_id=factor, field=window)`. These complete fields reproduce the template hash
above.

The existing P14b enumerator was applied to the exact family/template above; it must reproduce
the listed family, manifest and candidate hashes. The complete two-candidate family remains the
P14c denominator. Properly recorded non-PASS validation dispositions covered by frozen P14c
semantics remain in that denominator at `p=1`. Missing, unverified or corrupt evidence and other
strict P14c failures remain `FAILED / NOT_EVALUATED`; they must not be downgraded to benign `p=1`
dispositions. The statistical policy and P14c method are unchanged; the search space does not
expand. P14d-B's synthetic family or manifest identity must never enter Data-qualified authority.

## 5. Frozen campaign and execution path

All date, family, manifest, research/validation/cost/backtest, campaign/Agent-budget,
compute-accounting, Ledger, ContextPack, P14c plan and execution-request hashes are bound before
execution. Only existing P14b enumeration, P14d-A/B control-plane and existing PIT, Qlib Workflow,
Qlib Simulator, Validation, ResearchResult, Ledger and P14c services are execution authorities.
No P14c statistical, PIT, Validation, family-denominator or failure-taxonomy rule changes.

The campaign's `sealed_confirmation` segment stays in the existing schema as the date placeholder
in §3. No `OOSAccessed` event is allowed; no sealed trial may execute; no sealed-confirmation
authority is granted. The placeholder is never an accessible campaign segment. The natural
campaign freezes `trial_segment=VALIDATION`; it does not submit development trials. This keeps
every execution request on `campaign.validation == research_policy.test` as the adapter requires.

## 6. Qualification and natural-campaign outcomes

The P14-DQ engineering verdict is separate from the natural research verdict:

| Layer | Required treatment |
|---|---|
| P14-DQ qualification | `SUCCEEDED / PASS` only when all lineage, exact-file, policy, natural-run, independent-root, negative-case, restart/replay and verifier gates pass; otherwise `FAILED / NOT_EVALUATED`. |
| P14c with one properly evidenced `TrialOutcome.PASS` and one Validation REJECT | The `PASS` candidate is `ELIGIBLE` only with its uniquely linked, verified ResearchResult. The rejected candidate's `SOFT_REJECT` or `HARD_REJECT` disposition is `NONPASS_VALIDATION` and remains in the full two-candidate denominator at `p=1`. If all other P14c accounting, artifact, calendar and sample gates pass, the unchanged statistical procedure may produce `SUCCEEDED / SELECTED` or `SUCCEEDED / NO_SELECTION`; either outcome can support P14-DQ `PASS` when every engineering gate passes. |
| Both candidates Validation REJECT / no `TrialOutcome.PASS` | P14c has zero eligible candidates and must return `FAILED / NOT_EVALUATED`. It must not be rewritten as `NO_SELECTION`. That natural campaign is not acceptable natural-run evidence for P14-DQ `SUCCEEDED / PASS`. Do not relax Validation or P14c eligibility to obtain qualification PASS. |
| Natural PIT/execution/selection failure | Preserve native `PIT_REJECT`, `EXECUTION_FAILED` or `FAILED / NOT_EVALUATED` evidence. It cannot be relabelled `NO_SELECTION` or counted as a successful natural campaign. |
| Injected negative case | Expected fail-closed `FAILED / NOT_EVALUATED` is negative-case evidence only. Identify the injected fault; never present it as natural market evidence. |

Candidate Validation verdicts are recorded exactly as produced. A qualification PASS does not
change a research or Registry verdict.

## 7. P14-DQ report-only finalization profile

This narrow finalization/authority profile applies only to P14-DQ. It leaves P14c reports and all
historical P14d-B behavior/evidence unchanged. It does not call or emulate `freeze_selection` and
does not create sealed authority.

For a verified P14c `SELECTED` report, P14-DQ must:

1. Publish the verified `CampaignSelectionReport` unchanged.
2. Append the corresponding deterministic-verdict node to the Research Ledger.
3. Not call `freeze_selection` and not append `SelectionFrozen`.
4. Set `selection_event_hash=None` in the P14-DQ autonomous-loop evidence.
5. Not enter `READY_FOR_SEALED_CONFIRMATION`.
6. Deterministically close the campaign with the existing close event.
7. Finish in report-only completion, represented by existing `SELECTION_COMPLETE` state.
8. Preserve `sealed_confirmation_authority=false`.

For `NO_SELECTION`, publish/verify and ledger the report under the existing report path, then
deterministically close the campaign. It grants no sealed authority. A P14-DQ report-only close
does not change the P14c report itself or P14d-B's selected-case `SelectionFrozen` history.

## 8. Independent roots and equality

Root-A and root-B execute independently in separate output trees. They share only the verified
immutable snapshot/view/release inputs, clean source tree, lockfile and qualification code. They
do not share campaign/event stores, Agent exchange outputs, execution receipts, ResearchResult or
Validation artifacts, Ledger roots, selection artifacts, loop reports or qualification caches.

Each root records exact snapshot/view/release lineage and the P14d-B principal evidence domains:
candidate manifest, ContextPack, Agent request/proposal, execution identity/receipt, PIT evidence,
Qlib result, ResearchResult, ValidationReport, CampaignTrial/event chain, final Ledger snapshot,
P14c plan/report, autonomous-loop report, restart/replay behavior and negative-case outcomes.
Compare every deterministic authority hash. Only documented runtime telemetry, temporary paths
and wall-clock duration are excluded.

Retain P14d-B restart checks for an exchange/receipt committed before its trial and for a trial
committed before Ledger reconciliation. Adapt the report-publication restart boundary to §7:
after report publication but before campaign close, restart reuses the report and closes exactly
once without committing `SelectionFrozen`. Replay reuses the immutable exchange and execution
receipt without another Qlib execution.

## 9. Required negative cases

Reuse applicable P14d-B negative/restart/replay coverage without changing its historical meaning.
Each root also records these P14-DQ cases:

| Case | Expected fail-closed behavior |
|---|---|
| `DQ_SNAPSHOT_HASH_OR_PATH_MISMATCH` | Reject disagreement among explicit content-addressed path, hash and verified snapshot manifest. |
| `DQ_SYNTHETIC_OR_ALTERNATE_SNAPSHOT` | Reject a source kind other than Tushare or any substituted snapshot/fixture. |
| `DQ_SNAPSHOT_FILE_TAMPER_OR_EXTRA_FILE` | Reject changed, missing or unexpected snapshot files. |
| `DQ_QUALITY_REPORT_OR_LIMITATION_MISMATCH` | Reject changed/absent DQ report or removal/mutation of `SINGLE_SOURCE_NON_VINTAGE`. |
| `DQ_VIEW_HASH_OR_FILE_SET_MISMATCH` | Reject changed view hash, manifest, listed file or exact file set. |
| `DQ_VIEW_SOURCE_SNAPSHOT_MISMATCH` | Reject a view whose source snapshot hash differs from the required live snapshot. |
| `DQ_QILIB_SPEC_OR_HEALTH_MISMATCH` | Reject altered view spec, Qlib version/source/converter binding, health result or semantic sample. |
| `DQ_UPSTREAM_RELEASE_REPORT_TAMPER` | Reject noncanonical/hash-mismatched P7 report bytes or report/input lineage disagreement. |
| `DQ_UNQUALIFIED_UPSTREAM_RELEASE` | Reject an upstream report lacking `PASS / DATA_QUALIFIED / data_qualified=true`; preserve its historical Validation `REJECT` unchanged. |
| `DQ_ROOT_INPUT_SUBSTITUTION` | Reject any root resolving a different snapshot, view or upstream release report. |
| `DQ_FORBIDDEN_SEALED_HANDOFF` | Fail closed on any `SelectionFrozen`, `READY_FOR_SEALED_CONFIRMATION`, sealed-trial authorization or `OOSAccessed`; retain only report-only completion. |
| `DQ_QUALIFICATION_BUNDLE_FILE_SET_TAMPER` | Reject missing, extra, noncanonical or hash-mismatched qualification-bundle files. |

Negative-case results bind the case identifier, canonical input hash, deterministic observed
outcome/reason and outcome hash. Caller-supplied PASS is never accepted.

## 10. Content-addressed report and verification

The P14-DQ report is a new immutable qualification artifact published at
`artifacts/qualification/p14-dq/sha256-<report-hash>`. It binds code/runtime provenance, frozen
contract/policy hashes, exact upstream lineage, canonical upstream manifests and their
file-verification evidence, both root evidence trees, complete negative/restart/replay evidence,
principal equality, the §2 limitation set and an exact-file manifest. The report hash is derived
from canonical bytes only after every gate succeeds. Qualification bundles do not include the
full external snapshot or Qlib-view market-data files.

Bundle integrity verification is limited to the bundle and its recorded upstream
identities/manifests/hashes as described in §3. Full bottom-up qualification verification also
requires explicit external snapshot/view directories, re-runs `verify_snapshot` and
`verify_qlib_view` across their complete file sets, then independently rebuilds both roots. It
rejects missing/extra/tampered files, noncanonical bytes, wrong path/hash, dirty/wrong code
provenance, unqualified or substituted lineage, cross-root principal inequality and
replay/rebuild mismatch. Directory names alone never select authority.

## 11. Independent review gate

The earlier independent Sol High review returned `APPROVE_WITH_REQUIRED_FIXES`. The decisions in
§§3–10 are now frozen in this revision. No market-data window, family/manifest identity,
snapshot/view-copy strategy, Validation REJECT treatment or finalization decision remains open.
This draft is ready for a diff-only independent Sol High contract review before any implementation.
