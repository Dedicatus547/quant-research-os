# P14-DQ entry review

Review date: 2026-09-24

Prior independent Sol High result: **APPROVE_WITH_REQUIRED_FIXES**

Status: **required contract fixes incorporated; ready for diff-only independent Sol High review**

## Finding

P14-DQ uses the already-qualified, content-addressed Tushare snapshot and derived Qlib view to
qualify the bounded deterministic campaign path. P14d-B's two committed synthetic
snapshot/view fixtures, family/manifest identity and historical qualification evidence remain
unchanged. P14-DQ has its own Data-qualified campaign contract, family/manifest identity and
report-only selection-finalization profile.

The snapshot and view passed their existing `verify_snapshot` and `verify_qlib_view` checks during
the original entry audit, and the view names the snapshot hash as its source. The upstream P7
release binds the same pair and reports `PASS / DATA_QUALIFIED / data_qualified=true`. Its
`ValidationReport` outcome `SUCCEEDED / REJECT` and Registry state `REJECTED` remain historical
research outcomes; neither is mutated or treated as an engineering qualification failure.

## Reusable components

- `AutonomousCampaignOrchestrator`, `ScriptedAgentDriver`, `ReplayAgentDriver`, immutable
  exchange store, campaign governor and event chain from P14d-A/B, subject to the P14-DQ
  report-only finalization profile below.
- `QuantosResearchExecutionAdapter` and `build_autonomous_execution_bindings`; the adapter
  composes snapshot/PIT, Qlib Workflow and Simulator, Validation, immutable ResearchResult,
  execution receipts and the existing failure taxonomy.
- `ResearchLedgerService`, ContextPack construction, P14b candidate enumerator and frozen-family
  verifier.
- `CampaignSelectionService` and its P14c plan/report verifiers. P14c statistical policy,
  eligibility and report bytes do not change.
- `verify_snapshot`, `verify_qlib_view`, canonical contracts, provenance capture, artifact
  publication, exact-file verification, and independent-root/replay/restart patterns from
  `scripts/p14d_qualification.py`.
- Official Qlib 0.9.7 view artifacts produced by `dump_bin` and checked by Qlib health tools. The
  Qlib view is derived; the immutable Parquet snapshot remains canonical.

## Frozen live-data and time bindings

| Input or period | Exact binding | Required check |
|---|---|---|
| Canonical snapshot | `artifacts/data/snapshots/sha256-6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9`; dataset `cn-a-share-hs300-eval-2015-2025-v1`; hash `6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9` | `source_kind=TUSHARE`, provider `tushare-pro`, acquisition range `2014-11-01..2025-12-31`, quality report `e89933f2db98870e6a1143b6ca546713a2abfae30c0c5f00e79dea1d4d275ed8`, full manifest/file hashes, exact set, `SINGLE_SOURCE_NON_VINTAGE` |
| P7 `research_policy` | `train=2015-01-01..2019-12-31`; `validation=2020-01-01..2022-12-31`; `test=2023-01-01..2025-12-31` | Bind exact policy bytes/hash |
| Campaign periods | `development=2020-01-01..2022-12-31`; `validation=2023-01-01..2025-12-31` | `campaign.validation == research_policy.test`, as enforced by `QuantosResearchExecutionAdapter` |
| Sealed placeholder | `2026-01-01..2026-01-30` | Retain in existing campaign schema but leave unvisited; no `OOSAccessed`, sealed trial or sealed-confirmation authority |
| Derived Qlib view | `artifacts/data/qlib-views/sha256-fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b`; hash `fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b` | `source_snapshot_hash` equals the snapshot above; view spec `b349355d62166327fc67f3911eb60e7bdd9d639e0218799f124dcb3c85581375`; health and semantic samples pass; bind Qlib `0.9.7`, source commit `da920b7f954f48ab1bb64117c976710de198373e`, converter and every view-file hash |
| Prior Data-qualified release | `artifacts/releases/data-qualified-v0.1-f3fc768/report.json`; SHA-256 `6e3d6d8f6d1f8c9fd50124ce9cfcd6e22febb0099c05d5931878ca972da0ebca` | Canonical bytes and exact hash; `PASS / DATA_QUALIFIED / data_qualified=true`; binds the snapshot/view hashes above. Preserve existing `SUCCEEDED / REJECT` and `REJECTED` history. |
| Implementation | Future clean Git commit, `uv.lock` hash, runtime fingerprint, contract and policy hashes | Capture from the exact clean root and fail closed on dirty or mismatched provenance |

The current P14d-B evidence remains bound to implementation commit
`13d2b7acc44fe33c4f0c45d240fd5fd26e993845`, its frozen P14d contract, and synthetic fixture-set
hash `6f3f53d6d9586d52c529900f44231160c6d1400c57e8bb755a93af33af9991eb`. P14-DQ must publish
separate evidence and must never rewrite or relabel that report.

P14c's selection calendar is mechanically derived from the verified Qlib view's real sessions in
`2023-01-01..2025-12-31`, then frozen with the view hash in the P14c plan before any trial. It is
not a synthetic 77-session calendar. The natural campaign freezes `trial_segment=VALIDATION` and
does not submit development trials, so execution requests remain on
`campaign.validation == research_policy.test`.

## External artifact reference and verification strategy

The snapshot and Qlib view remain outside the qualification bundle. Run and full-verification
commands take explicit content-addressed paths; path names alone do not confer authority. The
verifier reruns existing `verify_snapshot` and `verify_qlib_view`, checks each full manifest and
all file hashes, rejects extra/missing/tampered files, and verifies snapshot-to-view lineage.
No fallback, reacquisition, network access, or rebuild is allowed.

The bundle records snapshot/view identity and hash, source lineage, quality-report binding, P7
release-report binding, canonical manifests and full manifest/file-set verification evidence,
without copying market-data files. Bundle-integrity verification checks the bundle and its
recorded upstream identities/manifests/hashes. Full bottom-up qualification verification also
requires both external directories and reexecutes their artifact verifiers before independently
rebuilding the roots.

## Synthetic-to-live and family/manifest delta

P14d-B's `_run_root_canonical_bundles` uses the committed synthetic `selected` and `no_selection`
fixtures. Its family/manifest hashes, synthetic campaign descriptions, fixture-specific P14c
outcomes and injected synthetic PIT rejection remain P14d-B historical evidence. None is
relabeled or used as P14-DQ identity.

P14-DQ freezes a new family while retaining the same bounded search-space shape:

| Field | Frozen P14-DQ identity |
|---|---|
| `family_id` | `p14-dq-live-data-engineering-v1` |
| `research_question` | `Can the bounded deterministic P14-DQ scripted/replay campaign reproduce identical principal engineering evidence in independent roots on the exact Data-qualified snapshot and derived Qlib view using the predeclared two-candidate adjusted-close DELTA family?` |
| `hypothesis_hash` | `147495c5a1f583aa8cd58c11d3de84ee1612d7149495ffed8c5257f43d4231a3`, SHA-256 of canonical JSON `{"claim":"The bounded deterministic P14-DQ scripted/replay campaign reproduces identical principal engineering evidence in independent roots on the exact qualified Tushare snapshot and derived Qlib view using the predeclared two-candidate adjusted-close DELTA family."}` |
| Template | `p14-dq-adjusted-close-delta-template-v1`; hash `a9df666299ac2feac2a50608d76b568bf6bc31bbfaaa1d98c0c60a4a6a69158a`; `adjusted_close -> DELTA(window)` |
| Operators | Existing set unchanged: `FIELD`, `DELTA` |
| Parameter space | `window ∈ {2, 3}` |
| Declared candidate count | `2` |
| Frozen family hash | `fbc0a11c08e502eaeb8abe5f7f9f5db390d9296a24a34607cd404e3655991bbb` |
| Deterministically enumerated manifest | Hash `b5fcc8e59f2bc9e63a307a512254dd0a165c7c50ea5904c0b4b546543a52d4ae`; `window=2` candidate hash `b7ca426ad868e15827365aa2bfcceb20870893a91add47713ff88dc2a43d444f`; `window=3` candidate hash `f6941537f61ba9cde4c0e866d365919a0fc3dda96c30304c1378bfc069364e96` |

The template uses `schema_version=research-factor-template/v1`,
`expression_schema_version=safe-qlib-expression/v2`, `input_lag_trading_days=0`,
`output_node_id=factor`, and two ordered nodes: `price` is `FIELD(adjusted_close)` with no inputs;
`factor` is `DELTA(price)` with its `window` supplied by the sole parameter slot
`(name=window, node_id=factor, field=window)`. Schema defaults are fixed to `inputs=()` and
`field_name=None, window=None` where not supplied. This is the complete template preimage for the
listed template hash.

The existing P14b deterministic enumerator produced this new manifest from the frozen identity;
qualification must re-enumerate and match it. The full denominator remains two. Properly recorded
`NONPASS_VALIDATION` dispositions remain at `p=1`; missing, unverified or corrupt evidence and
other strict P14c failures remain `FAILED / NOT_EVALUATED`. P14c's statistical policy is unchanged,
and the search space does not expand.

The natural campaign runs on the exact live snapshot/view lineage, offline after acquisition. The
P14c dates are the exact `2023-01-01..2025-12-31` Qlib sessions. A natural outcome is reported as
produced; no result is synthesized and `SELECTED` is not required for engineering qualification.

## Validation REJECT treatment

P14c eligibility is based on `TrialOutcome.PASS`. A PASS candidate is `ELIGIBLE` only with exactly
one validation trial and its uniquely linked, verified ResearchResult. A properly recorded
`SOFT_REJECT` or `HARD_REJECT` validation disposition is `NONPASS_VALIDATION` and remains in the
full two-candidate denominator at `p=1`. Missing/unverified evidence, duplicate validation
attempts or other strict failures invalidate the selection as `FAILED / NOT_EVALUATED`; they do
not become benign p=1 dispositions.

- One Validation REJECT and one properly evidenced PASS is a legal natural campaign. If all other
  P14c accounting, artifact, calendar and sample gates pass, P14c runs the unchanged complete
  procedure and may return `SUCCEEDED / SELECTED` or `SUCCEEDED / NO_SELECTION`. Either can support
  P14-DQ `PASS` if all engineering, lineage, independent-root and verifier gates pass.
- Two Validation REJECTs mean zero eligible candidates. P14c requires `FAILED / NOT_EVALUATED`,
  not `NO_SELECTION`. That natural campaign cannot serve as successful P14-DQ natural-run
  evidence. Validation/P14c rules must not be relaxed.

## P14-DQ report-only finalization

The existing normal P14d handoff freezes a selected candidate and enters
`READY_FOR_SEALED_CONFIRMATION`. P14-DQ uses a narrow, DQ-only report-only profile:

- For P14c `SELECTED`: publish and verify the unchanged `CampaignSelectionReport`; append its
  deterministic-verdict Research Ledger node; do not call `freeze_selection`; do not write
  `SelectionFrozen`; set `selection_event_hash=None`; do not enter
  `READY_FOR_SEALED_CONFIRMATION`; deterministically close; finish at existing
  `SELECTION_COMPLETE` report-only completion; keep `sealed_confirmation_authority=false`.
- For `NO_SELECTION`: publish/verify and ledger the report, then deterministically close with no
  sealed authority.

This profile changes neither P14c report bytes nor P14d-B selected-case semantics/evidence. It
cannot produce sealed authority.

## P14-DQ limitation set

Freeze the following sorted set in P14-DQ reports: `DQ_EXACT_SNAPSHOT_VIEW_LINEAGE_ONLY`,
`DQ_LIVE_AGENT_RUNTIME_NOT_QUALIFIED`, `DQ_NO_ALPHA_OR_PROFITABILITY_CLAIM`,
`DQ_NO_OOS_ACCESSED`, `DQ_NO_UNRESTRICTED_AUTONOMOUS_RESEARCH`,
`DQ_SCRIPTED_REPLAY_AGENT_ONLY`, `DQ_SEALED_CONFIRMATION_NOT_EXECUTED`, `FR_03_NO_GO`, and
`SINGLE_SOURCE_NON_VINTAGE`. These describe qualification limits on a run over
qualified live market data; do not say that P14-DQ lacks real market data. Do not reuse
P14d-A/B-era limitation text.

## Data-qualified-specific negative cases

| Case | Required rejection |
|---|---|
| `DQ_SNAPSHOT_HASH_OR_PATH_MISMATCH` | Explicit path, hash and verified manifest disagree. |
| `DQ_SYNTHETIC_OR_ALTERNATE_SNAPSHOT` | Source is not `TUSHARE`, or a fixture/other snapshot is substituted. |
| `DQ_SNAPSHOT_FILE_TAMPER_OR_EXTRA_FILE` | Snapshot file changed, omitted or added. |
| `DQ_QUALITY_REPORT_OR_LIMITATION_MISMATCH` | Quality report is absent/changed or the non-vintage limitation is removed. |
| `DQ_VIEW_HASH_OR_FILE_SET_MISMATCH` | View hash, manifest, file or exact file set differs. |
| `DQ_VIEW_SOURCE_SNAPSHOT_MISMATCH` | View points to any snapshot other than the frozen snapshot. |
| `DQ_QILIB_SPEC_OR_HEALTH_MISMATCH` | View spec, Qlib source/version/converter, health or semantic evidence differs. |
| `DQ_UPSTREAM_RELEASE_REPORT_TAMPER` | P7 report bytes/hash differ or report binds another snapshot/view. |
| `DQ_UNQUALIFIED_UPSTREAM_RELEASE` | P7 report is not `PASS / DATA_QUALIFIED / data_qualified=true`; historical Validation REJECT remains unchanged. |
| `DQ_ROOT_INPUT_SUBSTITUTION` | Either root resolves any different frozen live input. |
| `DQ_FORBIDDEN_SEALED_HANDOFF` | Fail closed on any `SelectionFrozen`, `READY_FOR_SEALED_CONFIRMATION`, sealed-trial authorization or `OOSAccessed`. |
| `DQ_QUALIFICATION_BUNDLE_FILE_SET_TAMPER` | Bundle has missing, extra, noncanonical or hash-mismatched files. |

## Entry gate

There is no remaining contract choice about the market-data window, family/manifest identity,
external artifact references versus copying, Validation REJECT semantics, or P14-DQ finalization.
The exact snapshot/view and P7 release were present and passed their existing verifiers during the
entry audit. The next gate is an independent **Sol High diff-only contract review**. No runner,
production orchestrator, execution adapter, schema, P14-RC or P15 work is part of this revision.
