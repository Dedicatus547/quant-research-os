# HM native recovery and principal comparison successor review

Review date: 2026-09-30. Status: **NARROW_IMPLEMENTATION_REVIEW_ACCEPTED / NOT_QUALIFIED**, subject to the evidence limits below. This record grants no HM-07, HM-09, Q07, Q09, Q10 or Q11 qualification.

The reviewer was independently tasked under the user's development/review override: configured model `gpt-6.1-sol`, reasoning effort `high`. Observed model/effort and token usage are unavailable to this reviewer. The override does not change the frozen research profile `gpt-6-sol/high`. No additional agents were used.

The exact base HEAD was `719afbbef2543304bf5fc16e0f699a0c260a669c`. Findings concern the uncommitted implementation, not that commit alone. The reviewer only read implementation and tests, ran offline checks, and added this successor document. Existing reviews, source authority, frozen contract, acceptance and freeze records were not edited. No real credentials were accessed.

## Scope and inspected bytes

The narrow scope is `hosted_protocol._scan_safe`, native execution receipt recovery and inspection, report/result/backtest binding, managed service's empty-channel guard, principal/runtime path classification, and the C11 projection function. The in-progress overall Q01–Q12 verifier and current native probe changes are outside this approval. Their presence in the same working tree or file does not extend the review.

The following file hashes identify an inspected working-tree snapshot. The main agent continued editing concurrently; subsequent bytes require subsequent validation.

| File | SHA256 at the inspected snapshot |
| --- | --- |
| `src/quantos/application/autonomous_execution.py` | `a6b389593d9a893762d28ec0681274c948b4bb267e4c1300931c8eeb7081a131` |
| `src/quantos/application/hosted_protocol.py` | `d773bae37b5d80d7a00476c77fb0e9d35dc05c144ad316bb1e6aaa8863fc96b4` |
| `src/quantos/infrastructure/hosted_business_verification.py` | `99ca21d4de56508e8e003d810ce3e15580160d0d2b1b6bee3632ae249981ec0a` |
| `src/quantos/infrastructure/hosted_manager.py` | `b82d2c3af87cc6bfa2f65e2ea420895d7b1ec518af210183e4fc931a3bde3f21` |
| `src/quantos/infrastructure/hosted_verification.py` | `dde4c1a13545cb258fcc5e2184cf50e539e719fb4e916e2152ec238148be279e` |
| `tests/integration/test_hosted_business_e2e.py` | `82f052ef6f75fc8f92bd2a571246f0ecde90d85449976016c07d58512009169f` |
| `tests/unit/test_hosted_scan.py` | `01e9bf6d9b56b41279f398c020262afb7439197d2abbe8207e081ed001334f48` |
| `tests/unit/test_hosted_manager.py` | `d922d2723554e3b3f416e4ebf05130558b1f40b555de8809f899c73b8938fd51` |
| `tests/unit/test_hosted_business_verification.py` | `e93400d98346d2687a9f38a0ed0c3d038ee78dae482a615555f4df35a9be056b` |

The inspected tracked diff, limited to the five implementation paths above and the two tracked unit test paths, had SHA256 `f99725a6ac62c5125790911c1e0375ea885d9c4a1bedeb9f1113d3fa9f460f03`. The two new test files were untracked and are bound separately by their file hashes. Later additions to the overall verifier are not approved by this diff digest.

## Typed scan view

The exception is narrowly justified. `ValidationReport.reproducibility.exact_content_hash` is an existing boolean field, whereas the generic secret scanner treats a key ending in `_hash` as a digest. The implementation recognizes the exact `reproducibility-comparison/v1` schema, validates the entire existing `ReproducibilityComparison`, requires the original field's Python type to be exactly `bool`, and requires complete canonical bytes to agree before renaming that single field in a copied scan view.

Unknown schema, missing fields, additional fields and coercions cannot acquire the exception. The remaining reference and detail strings still enter recursive secret scanning; a credential-shaped detail remains rejected. Original objects and protocol bytes are not rewritten. Recognizing a complete comparison at arbitrary nesting depth does not permit an arbitrary sensitive string to bypass inspection because the exceptional value is only a boolean.

The independently executed five scanner tests passed, covering a valid comparison without mutation, unknown schema, string-to-bool coercion, sensitive detail and missing reference. Additional-field and noncanonical numeric/default coercion cases are useful follow-up regression coverage; the current explicit full-byte check already rejects them by inspection.

## Report-backed outcomes and actual failure evidence

A report-backed `SOFT_REJECT` legitimately carries `SOFT_THRESHOLD_NOT_MET`. It does not imply an `AutonomousExecutionFailureEvidence` artifact. The recovery branch must follow the presence of `validation_report_hash`, rather than whether `failure_reason_code` is non-null. The checked outcome/reason mapping matches the existing `_outcome_from_validation` writer: failed report, passing report, hard reject, otherwise soft reject; reason is the first non-null gate reason.

The initial draft lacked the candidate/result cross-binding. Two valid reports can share snapshot, view and policies while belonging to different candidates. The reviewer reported that an A result could be paired with a B report under the original four-field check. The inspected fix now retains the verified `ResearchResultManifest` and additionally requires:

- Report authoring hash equals the exact request-derived authoring hash.
- Report resolved-experiment and signal hashes equal those in the verified result.
- A baseline backtest hash is present and included in the receipt's evidence hashes.
- The baseline backtest exists under the exact execution identity, passes the existing `verify_backtest_artifact`, and binds the same resolved experiment, signal, snapshot, view, cost policy and backtest policy.
- Receipt result/report evidence, execution-requested flag, outcome and reason agree with the report branch.

The existing backtest verifier checks its manifest, complete file set, hashes, native table schemas/counts/dates and config/reconciliation bindings. Reusing it introduces no project accounting engine. The native two-candidate test exchanges genuine valid reports while keeping a candidate's own result; the repaired check rejects the exchange. Corrupting the native baseline portfolio file is also rejected.

The initial no-report draft checked only a non-null reason and required complete evidence only in the two completed-execution entry points. Both defects were reported. The inspected successor centralizes a pure, nonrecursive `_verify_failure_for_receipt` under `_verify_receipt`, so ordinary `execute` receipt reuse, online completed recovery and offline inspection all verify exactly one canonical, content-addressed failure artifact with the complete request/execution/campaign/candidate/snapshot/reason/kind bindings. It preserves the original native classification:

| No-report outcome | Allowed native reasons |
| --- | --- |
| `PIT_REJECT` | `LOOK_AHEAD`, `UNKNOWN_AVAILABILITY` |
| `EXECUTION_FAILED` | `QLIB_EXECUTION_FAILED`, `SOURCE_INCOMPLETE` |

This prevents a soft threshold reason from being relabeled as a native failure even if its receipt and evidence are rehashed. The helper reads through pinned directories and does not call `_read_receipt`. `inspect_completed_execution` additionally reads the identity receipt and its existing content-addressed index, verifies exact bytes, and makes no index repair. Online `verified_completed_execution` intentionally retains the older repair behavior; that is not the offline inspection boundary.

Old profile compatibility is structurally preserved: the constructor and result schemas are unchanged, ordinary and P14-DQ profiles continue to use their existing writer, baseline layout and failure classifications, and the optional DQ audit branch remains profile-specific. Genuine older report-backed soft rejections become inspectable without fabricated failure evidence. An older root missing applicable baseline or failure artifacts is rejected rather than repaired into evidence. This review did not claim that every historical saved root was replayed.

## Runtime paths, C11 and managed start

The reviewer independently reproduced an overly broad exclusion: a file at a verified execution's `validation/mlflow-runtime/unrecognized-authority.json` was categorized as runtime merely because its path contained `/mlflow-runtime/`. This would hide an unknown authority difference from principal comparison. The inspected fix uses only the actual fixed producer path `.../{execution_identity}/qlib-workflow/mlflow-runtime/`. The added negative test keeps similarly named files elsewhere, and arbitrary unknown files, in principal inventory. That negative test passed independently.

`principal_business_inventory` partitions the complete raw inventory; it does not authorize discarding runtime files. Before qualification, both complete inventories and the explicit runtime inventories must be bound by their respective immutable manifests. The component test copies the derived principal files into separate comparison roots and verifies those exports against the principal inventories. Passing a full mixed root together with a filtered inventory to `compare_principal_roots` would correctly fail exact raw inventory verification.

The C11 change from `authority.canonical_bytes()` to canonical serialization of the complete `model_dump` is necessary: the former excludes hash payload fields such as `created_at`, so it cannot validate the original full file bytes. The corrected function first validates the exact allowlisted typed object and complete canonical bytes, then removes only the top-level `created_at` from its comparison view. The seven-schema allowlist is unchanged. Other fields, nested timestamps and original bytes remain intact, and each actual projection records its path/schema/raw hashes/projected hash.

One remaining integration condition must be explicit: `ResearchLedgerSnapshot` has no embedded self-hash field. Typed parsing alone is not proof that its path is the authoritative Ledger snapshot. Before projecting a ledger snapshot, the final verifier must bind its content hash/path to the already bottom-up verified ledger/report and source event chain. The component business verifier supplies bottom-up authority; the projection helper alone does not supply all authority bindings. Similarly, equal raw hashes are comparison equality, not a replacement for validating the producer artifact's authority.

The new managed-start guard uses an opened channel directory and rejects any entry before allocating a capability descriptor or spawning a child. It preserves stale evidence and requires explicit stop/forensic handling. The three stale-entry cases passed. This closes the observed stale socket/bootstrap readiness shortcut. The guard assumes serialized trusted management of a stopped channel; it does not establish fresh service provenance on its own. The eventual Q07 proof must combine the frozen install/profile and exact launcher command, original fresh-channel observation, and binding to the newly launched managed service. Producer flags, `PASS`, or matching UID alone are insufficient. This reviewer did not execute a newly frozen native start/probe for these current bytes.

## Independently executed checks and qualification blockers

- Scanner unit suite: **5 passed**.
- Manager, business predicate and raw qualification unit suites at their earlier snapshot: **26 passed**.
- Added exact-runtime-path negative test after the fix: **1 passed**.
- Actual offline Qlib business integration at the initial repaired report/backtest snapshot: **1 passed in 94.26 seconds**, with 232 warnings. It executed two candidates in each of two fresh roots, compared principal exports, preserved source protocol inventory, rejected report exchange/backtest corruption and verified final authority without rerunning execution.
- Pure failure component check on the centralized helper: all four permitted native classifications accepted; missing evidence rejected for each; a soft threshold reason mislabeled as PIT rejected; before/after raw inventory identical. This check bypassed frozen-input validation to isolate the failure verifier and grants no production evidence.
- Pure C11 component check: valid full ledger serialization differing only in top-level creation time projected equally; altered authority remained different; noncanonical bytes, unknown schema and extra-field payloads rejected.

The native integration test was subsequently extended with complete failure-reuse negative cases. A second independent run passed: **1 passed in 93.61 seconds**, with the same 232 warnings. The inspected added cases delete genuine failure evidence and require rejection through ordinary execution reuse, online completed recovery and read-only inspection, then restore the evidence and test a misclassified soft threshold reason. Checks are synthetic/offline component evidence, not a replacement for original live source evidence or a native fixed-profile qualification run.

The remaining qualification blockers are the unfinished independent Q01–Q12 predicate wiring, complete original raw/runtime inventory and authority-path binding, and a new profile plus actual restricted deployment run for changed implementation/probe bytes. The older attempt05 result reported by the main agent cannot attest a later binary or probe. No live model/source capture or new production qualification was performed in this review. No profitability result is an engineering acceptance criterion.

Frozen record hashes checked unchanged:

- Contract: `14704b9cbbe0f0ca281751833bc08248820da0c277a281a140bfd12bc6b102df`.
- Acceptance: `e5877b503259f6e758f22a6feb9307efdc45397155a9229527b2a8ae5dbfc55e`.
- HM-02 freeze manifest: `ac5a4c5e01e8c064906342607ff2ef9f3e9e9b98429188689e6873f76b2ee52e`.
- Original deployment bindings review: `784b573fe47c4e5838a74d2ce39bbb420c707ca39d8d4743610ff55ac3782381`.
