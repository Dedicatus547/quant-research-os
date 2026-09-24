# P14-DQ entry review

Review date: 2026-09-24

Status: **entry audit complete; qualification contract awaits independent Sol High review**

## Finding

The smallest change from qualified P14d-B to a Data-qualified deterministic campaign is to
replace P14d-B's two committed synthetic snapshot/view fixtures with the already-qualified,
content-addressed live snapshot and its derived Qlib view. The campaign control plane and execution
services remain the same. The runner and report contract need a separate Data-qualified binding and
evidence type so P14d-B's frozen synthetic-only authority is preserved.

The local snapshot and view passed `verify_snapshot` and `verify_qlib_view` during this audit. The
view names the snapshot hash as its source. The upstream P7 release report binds the same pair and
reports `PASS / data_qualified=true`. Its `ValidationReport` outcome is `SUCCEEDED / REJECT` and its
Registry state is `REJECTED`; those historical results stay unchanged and are not qualification
acceptance criteria.

## Reusable components

- `AutonomousCampaignOrchestrator`, `ScriptedAgentDriver`, `ReplayAgentDriver`, immutable exchange
  store, campaign governor and event chain from P14d-A/B.
- `QuantosResearchExecutionAdapter` and `build_autonomous_execution_bindings`; the adapter already
  composes the snapshot/PIT path, Qlib Workflow and Simulator, Validation, immutable ResearchResult,
  execution receipts, and failure taxonomy.
- `ResearchLedgerService`, ContextPack construction, P14b candidate enumeration and frozen-family
  verifier.
- `CampaignSelectionService` and its plan/report verifiers from P14c. No P14c policy or statistical
  computation needs changing.
- `verify_snapshot`, `verify_qlib_view`, canonical contracts, provenance capture, artifact
  publication, exact-file tree verification, and the independent root/replay/restart patterns in
  `scripts/p14d_qualification.py`.
- Existing official Qlib 0.9.7 view artifacts produced by `dump_bin` and checked by Qlib's health
  tool. The view is a derived cache; the snapshot remains the canonical dataset.

## Required live-data bindings

| Input | Exact binding | Required check |
|---|---|---|
| Canonical snapshot | `artifacts/data/snapshots/sha256-6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9`; dataset `cn-a-share-hs300-eval-2015-2025-v1`; manifest hash `6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9` | `source_kind=TUSHARE`, provider `tushare-pro`, range `2014-11-01`–`2025-12-31`, quality report `e89933f2db98870e6a1143b6ca546713a2abfae30c0c5f00e79dea1d4d275ed8`, exact files and hashes, `SINGLE_SOURCE_NON_VINTAGE` |
| Derived Qlib view | `artifacts/data/qlib-views/sha256-fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b`; view hash `fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b` | `source_snapshot_hash` equals the snapshot above; view spec `b349355d62166327fc67f3911eb60e7bdd9d639e0218799f124dcb3c85581375`; health check and semantic samples pass; bind Qlib `0.9.7` / source commit `da920b7f954f48ab1bb64117c976710de198373e` and converter hashes |
| Prior Data-qualified release | `artifacts/releases/data-qualified-v0.1-f3fc768/report.json`; file SHA-256 `6e3d6d8f6d1f8c9fd50124ce9cfcd6e22febb0099c05d5931878ca972da0ebca` | Canonical bytes and exact file hash; report says `PASS`, `DATA_QUALIFIED`, and `data_qualified=true`, and binds the two hashes above. Preserve its existing `SUCCEEDED / REJECT` and `REJECTED` results. |
| Qualification implementation | The future clean implementation commit, `uv.lock` hash, runtime fingerprint, contract hash and policy hashes | Capture from an exact clean repository root; fail closed on dirty/incorrect provenance. |

The current P14d-B evidence remains bound to implementation commit
`13d2b7acc44fe33c4f0c45d240fd5fd26e993845`, its frozen P14d contract, and synthetic fixture-set
hash `6f3f53d6d9586d52c529900f44231160c6d1400c57e8bb755a93af33af9991eb`. P14-DQ must publish
separate evidence and must never rewrite or relabel that report.

## Synthetic-to-live delta

P14d-B's `_run_root_canonical_bundles` loads exactly the committed `selected` and `no_selection`
fixtures. Its fixture calendars are 77 sessions long, its campaign text explicitly says
“synthetic,” and its three canonical cases require those fixtures to produce two different P14c
decisions plus a synthetic injected PIT rejection. Those fixture assumptions cannot be carried
into P14-DQ.

The Data-qualified path must instead:

1. Accept only the exact live snapshot/view/release bindings above. The run is offline after
   acquisition; it must not call Tushare or refresh/replace any source artifact.
2. Derive its frozen data window from the verified view and bind the selected dates into the
   campaign and policies. The intended period and family are contract decisions below.
3. Run one natural campaign whose P14c outcome is reported as produced. `SELECTED` and
   `NO_SELECTION` are both valid evaluated outcomes. Do not synthesize one outcome or require
   `SELECTED` for engineering qualification. Use report-only selection finalization: even a
   `SELECTED` report must not append `SelectionFrozen` or transition to
   `READY_FOR_SEALED_CONFIRMATION`.
4. Retain a separate known failure injection to prove that a real PIT rejection or execution
   failure yields `FAILED / NOT_EVALUATED`; injected failure evidence is labelled as such and is
   never reported as market evidence.
5. Add DQ-specific negative cases for data-source kind, exact snapshot/view identity, upstream
   release lineage, file-set integrity, and synthetic/alternate-source substitution.

P14d-B's selection, accounting, replay, restart, policy, and tamper cases remain reusable where
their semantics apply. Its third selection restart boundary must become a P14-DQ report-only close
boundary: after a verified P14c report is published but before campaign closure, restart reuses that
report, closes once, and never commits `SelectionFrozen`. No statistical, PIT, Validation, or
historical gate changes are proposed.

## Authority boundary

The qualified driver remains deterministic and runtime-independent (`ScriptedAgentDriver` and
`ReplayAgentDriver`). A proposal resolves only against a pre-frozen P14b candidate manifest, then
passes through the existing real-data PIT, Qlib, Validation, ResearchResult, Ledger, and P14c
services. This adds bounded Data-qualified deterministic engineering authority for the exact
snapshot/view lineage in this review.

It does not grant live-Agent or FR-03 qualification, sealed-confirmation authority, alpha or
profitability claims, historical vendor-vintage PIT claims, or unrestricted autonomous research.
No `OOSAccessed` event or sealed execution is in scope. The P14d-C track remains separate and
blocked by FR-03 `NO_GO`.

## Minimum runner and verifier changes

- Add a P14-DQ contract/report schema and `scripts/p14dq_qualification.py`; keep P14d-B's frozen
  contract and synthetic report semantics intact.
- Add a narrow report-only selection handoff for P14-DQ. The current autonomous handoff appends
  `SelectionFrozen` and enters `READY_FOR_SEALED_CONFIRMATION` for `SELECTED`; that authority must
  be suppressed in this qualification while preserving the verified P14c report verbatim.
- Share P14d-B's campaign, execution, restart/replay, negative-case, provenance and publication
  primitives. Keep the added code to explicit live input binding, data-qualified case selection,
  root assembly, and DQ-specific evidence.
- Require explicit snapshot, view and upstream release-report paths and hashes. Never resolve a
  mutable name or silently fall back to a fixture. Verify the entire manifest file set before each
  root starts.
- Run root-A and root-B with independent campaign stores, execution outputs, Ledger roots,
  selection plans/reports and qualification caches. They may share only the verified immutable
  inputs, source tree, lockfile and runner code.
- Publish a content-addressed report with exact-file manifest, clean-code/runtime provenance,
  input lineage, both root evidence trees and principal hashes. The verifier checks every file and
  lineage binding, rebuilds both roots independently, and compares all principal hashes.

## Data-qualified-specific negative cases

| Case | Required rejection |
|---|---|
| `DQ_SNAPSHOT_HASH_OR_PATH_MISMATCH` | Snapshot directory name, explicit hash and verified manifest do not agree. |
| `DQ_SYNTHETIC_OR_ALTERNATE_SNAPSHOT` | Source kind is not `TUSHARE`, or any fixture/other snapshot is substituted. |
| `DQ_SNAPSHOT_FILE_TAMPER_OR_EXTRA_FILE` | A canonical/raw file is changed, omitted or added after qualification. |
| `DQ_QUALITY_REPORT_OR_LIMITATION_MISMATCH` | The bound quality report is absent/changed, or the non-vintage limitation is dropped. |
| `DQ_VIEW_HASH_OR_FILE_SET_MISMATCH` | View hash/path/file set differs from the qualified view. |
| `DQ_VIEW_SOURCE_SNAPSHOT_MISMATCH` | View manifest refers to any snapshot other than the exact input snapshot. |
| `DQ_QILIB_SPEC_OR_HEALTH_MISMATCH` | View spec, Qlib source/version/converter binding or health/semantic evidence differs. |
| `DQ_UPSTREAM_RELEASE_REPORT_TAMPER` | P7 report bytes/hash differ, or the report binds a different snapshot/view. |
| `DQ_UNQUALIFIED_UPSTREAM_RELEASE` | Upstream report is not `PASS / DATA_QUALIFIED / data_qualified=true`. A historical Validation `REJECT` remains a recorded research outcome, not a reason to mutate or bypass that report. |
| `DQ_ROOT_INPUT_SUBSTITUTION` | Either independent root resolves an input other than the exact frozen live binding. |
| `DQ_SELECTED_REPORT_HAS_NO_SEALED_HANDOFF` | A verified `SELECTED` P14c report is recorded without `SelectionFrozen`, sealed-trial authorization, or `READY_FOR_SEALED_CONFIRMATION`. |
| `DQ_QUALIFICATION_BUNDLE_FILE_SET_TAMPER` | Qualification bundle has missing, extra, noncanonical or hash-mismatched files. |

## Prerequisites and blockers

- **No current live-data prerequisite is missing in this workspace.** The exact snapshot and Qlib
  view are present and passed their existing verifiers; the P7 report is present and binds them.
- The snapshot and view are workspace-local artifacts (ignored by Git). Qualification therefore
  must require their explicit content-addressed paths at run and verification time, or freeze
  complete copies. It must not depend on a mutable `latest` path or reacquire data.
- Contract review must settle the data window, frozen campaign family/policies, and whether report
  verification uses exact external artifact references or copies the two upstream artifacts into
  the qualification bundle. These are contract choices, not blockers in the existing services.
- FR-03 `NO_GO` is not a P14-DQ prerequisite and is not changed by this work.
