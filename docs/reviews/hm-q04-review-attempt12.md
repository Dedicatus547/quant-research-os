# HM Q04 and formal-verifier source binding: independent narrow review

Status for reviewed frozen commit: **CHANGES_REQUIRED / NOT_QUALIFIED**.

Two independently reproduced P1 findings remain open in frozen `a6d1859`: the formal verifier's source-only installation check can accept stale bytecode, and the known-invalid business admission helper accepts an unrelated additional authority file. The parent has acknowledged the former and described a successor fix; that design is not recorded here as an implementation closure. No actual attempt12 result is asserted in this first-phase report: the managed Q03/Q04 deployment was still running and the reviewer was instructed not to draw conclusions from its unfinished directory.

## Reviewer and exact scope

- Assigned model: `gpt-6.1-sol`; reasoning effort: `high`; independent narrow-review attempt: `1`; observed usage: **unavailable**. The frozen research-model profile is unchanged.
- Exact reviewed commit: `a6d1859398225f94cdc75c7f80adc73b1cc9b4ad`. The main worktree was clean at initial and final code/canary checks. The parent identified the followup worktree as the same clean commit.
- Code reviewed: Q04 admission worker, deterministic fixture recipes, business and bounded-rejection reconciliation, Q03/Q04 original-manager matrix, its manager invocation, added security probes, formal verifier source/runtime binding, and their tests.
- Reviewer changed no main/followup implementation, frozen file, real managed evidence, or commit. Temporary canary scripts/logs and this report are under `/tmp`. No real model/vendor credentials were read, no model was called, and no acquisition/network transport was invoked.
- The temporary native canary uses existing synthetic snapshot/contracts/native adapter/test scaffolding. It does not qualify live sources or a deployment. It executes existing Qlib services; it does not implement a research/backtest/accounting engine.

Frozen source hashes:

| File | SHA-256 |
| --- | --- |
| `hosted_admission_verification.py` | `9c2fcdd04b303a6bff0f13900cabcd4585d8986f2e7d096cd8346616efa4676a` |
| `hosted_admission_probe.py` | `a094b166d802b16c03f588f53107564589a1a52aaf4f42818b3984e581bbae36` |
| `hosted_fixture_frames.py` | `d62ba9e37912cd85d8ec99c035a0e0e7778f228ba02d900ca93ffd292f13c083` |
| `hosted_negative_origin.py` | `f6f72c67d0b802baa7d1e056b00de871b74433ef632750a886c674a334830486` |
| `hosted_negative_probe.py` | `49a19df7cd6be2ac3dadbd462c35c4c850c24e4e2b0b257b82d31fddc6427728` |
| `hosted_negative_verification.py` | `7412e40f92bca9033a8863302b639f83aaecba06f10a95c2e1d6650ef12ce214` |
| `hosted_verification.py` | `f7cb8bda6e3d93bc74f1a79739a7a728ff75c5f026c7f080cf06a462d369ec38` |

## P1-1: disk source hashes do not prove executed verifier code

`verify_loaded_project_installation` checks each QuantOS module's `__file__` `.py` hash against an installation inventory entry inferred from its module name. It rejects a final symlink or changed source bytes, but accepts an identical source file from an external checkout and does not check which bytecode CPython actually loaded.

I reproduced this with real CPython import machinery, without monkeypatching the verifier or module registry:

1. Under a reviewer-owned TemporaryDirectory, compile a timestamp `.pyc` for the harmless module `MARKER = 'staled'`.
2. Restore the same-length frozen disk source `MARKER = 'frozen'` with the cache's expected mtime.
3. Import the temporary module through the ordinary SourceFileLoader as `quantos.review_canary`.
4. Call the real source-binding helper with the expected disk source hashes for all loaded QuantOS modules.

Observed output is `disk_source_frozen=True`, `loaded_module_marker='staled'`, `formal_installation_helper_accepted=True`. The interpreter executed different code from the bytes the helper certified. This is a concrete failure of the new source-binding proof; the canary does not purport to forge an entire qualification bundle or establish a production-host write capability.

Evidence:

- Script `/tmp/hm_verifier_pyc_canary_a6.py`, SHA-256 `7056b0576cac71083d40e845e9b7128fb20ad44545a1c72d4d0e97bb4bff89e1`.
- Log `/tmp/hm-verifier-pyc-canary-a6.log`, SHA-256 `83812ebcb57f1678ab5eba9963f8a34dcb2cb0a72e6853b86b65f45a034fc2a9`.

The parent proposes a smaller successor fix that supports no QuantOS bytecode cache: set a private initially absent guest `/tmp/quantos-disabled-bytecode-cache` prefix in native PyConfig before initialization, keep `write_bytecode=0`, require the fixed native interpreter/hash/flags, and require all module file/spec/SourceFileLoader paths to match anchored original installation paths. QuantOS cached files in the installation are rejected; actual `__cached__` must be under the private absent prefix. This design is sufficient to address the reproduced gap if implemented and tested with actual fixed native launch records. Merely disabling bytecode writes does not disable cache reads.

Minimum closure tests: the actual CPython stale timestamp cache above rejects; ordinary external-checkout source cannot substitute for original installed origins; private cache-prefix pollution rejects before loading; a fresh fixed native process with the expected flags and absent prefix accepts actual installed source. The fixed `-m` main module must also be bound, and source paths must use complete ancestor anchoring rather than only a final `is_symlink` check. No marshal parser or supported-cache compatibility path is necessary for the parent's explicit no-cache formal profile. A native launcher change requires a new frozen profile; it cannot retrospectively qualify a6's formal entry.

## P1-2: known-invalid admission can hide an extra authority file

`verify_business_admission_fixture` requires every before file to remain unchanged, checks the accepted exchange/response and one schema-invalid trial, and invokes the native business verifier for reports, events, Ledger, research charges and execution identities. It does not reconcile the entire new after-file set to those verified facts. The shared business verifier preserves complete raw inventory during its own run but does not reject every unreferenced file elsewhere in the authority root. Consequently a new unknown file can be included in raw inventory and still escape the zero-execution admission check.

I confirmed this using the existing integration fixture and real native adapter/events/Ledger, not synthetic replacement business facts. The existing test provides its documented synthetic preflight adapter constructor; its ordinary business/admission verification functions remain real. After the first `known_schema_invalid` trial's unmodified authority passed the original helper, I added `unpublished-review-canary.json` at the temporary after authority root and called the original helper again. It accepted the changed authority. The verification itself was readonly, and the canary file was removed only from this reviewer-created disposable fixture. No actual managed stage was read or altered.

Observed output: `extra_unknown_file_rejected=False`, `native_invalid_trial_helper_accepted=True`, `readonly_verifier=True`. The target canary ends after that first admission case; it is not claimed as a successful complete integration test run.

Evidence:

- Script `/tmp/hm_admission_extra_file_canary_a6.py`, SHA-256 `bd620833a6cbcb42139c08a5e385c095ee7ec4806d22b5aa7c55c66015f57f4e`.
- Log `/tmp/hm-admission-extra-file-canary-a6.log`, SHA-256 `b4e701f2a656b968a70cc7ba575f127473a37998a5ec27e04bcefc2a7c18b9dc`.

The bounded transport helper already rejects this class of unrelated raw additions using its exact journal publication delta. Known-invalid business trials legitimately add trial/event/Ledger/request/report artifacts, so they need a corresponding closed set derived from the verified publications, events, Ledger references and fixed native artifact paths. All actual after files must be accounted for; preserved before files plus an empty execution identity tuple are insufficient.

Minimum closure tests: a normal native schema-invalid trial remains valid, while an unknown non-protocol file, an extra native execution/result manifest or sidecar, and an unrelated canonical artifact under an otherwise plausible business directory are rejected. Do not fix this by excluding unknown files from inventories or accepting an entire output subtree merely because its prefix is known. All checks must remain readonly.

## Q04 matrix, origin and bounded-accounting findings

The intended Q04 matrix is explicit and finite: seven transport cases (byte cap, invalid UTF-8, duplicate JSON keys, unknown fields, noncanonical bytes, unknown candidate, credential-like payload), plus six known-candidate business cases (proposal schema, unsafe DSL, invalid AST, outside parameters, exact and structural fingerprint mismatch). `verify_q04` requires all twenty-six named before/after roots and both subsets. Transport-only and business-only helpers do not award the complete Q04 gate.

The source checks reuse the already reviewed original-manager boundary: independently supplied manager root, exact mapped files, unique original prelaunch/completion/observation, fixed fresh authority paths, full channel inventory, frozen installation/native image hash, actual fixed argv/descriptors and kernel process/namespace identities. The test fixtures construct synthetic source/kernel records and explicitly do not prove those real origins. Uploaded verdict strings alone establish no source authority.

Recipes are reconstructed deterministically by the verifier. Q04 observations contain no reversible `response_json`; they bind observed digest and exact byte count. The credential-like recipe is explicitly synthetic, and actual rejected credential-like bytes are not accepted as persisted evidence. Unknown candidate produces transport rejection and no business trial. A known candidate's malformed proposal can be accepted at transport, then must produce one SCHEMA_INVALID trial and one trial charge, zero execution/compute, the correct candidate/report denominator, and validation-round charge only for the validation segment. If a second request is issued, its cancellation and final report are explicitly bound.

The oversized worker feeds a larger BytesIO into the real frame reader and requires its cursor to stop at cap+1. The helper requires incomplete receipt, observed prefix hash/count and FRAME_BYTE_CAP_EXCEEDED, not a hash of unseen tail bytes. Complete schema and candidate/scanner rejects bind their full frame digest and rejection reason. The exact transport raw delta verifies preserved journal/artifacts/business files, one new submission and bounded reservation charge, no acceptance overwrite, and late repeats without added publications or refund.

The Q04 full predicate additionally requires the independently checked original deployment security evidence to be exported. Added real host probes cover parent traversal from projection to sealed authority, absolute inputs, channel hardlink and FIFO mutation, in addition to the existing symlink and replacement/race controls. These must be observed in the new completed profile; producer PASS labels or old-profile evidence cannot satisfy the gate. I have not independently inspected actual attempt12 syscall outcomes in this first phase.

## Runtime fingerprint scope

The new formal runtime binding requires canonical `deployment/runtime-fingerprint.json` bytes and exact equality to the outer manifest hash. If Q11 is PASS, every ValidationReport found in the already verified live root must use that same runtime fingerprint and at least one report must exist. The frozen Q11 success/soft-reject rules already require completed validated native executions for every frozen candidate, so the report requirement is consistent with that gate's actual denominator. Diagnostic roots with Q11 NOT_EVALUATED do not establish native live runtime equality merely because their outer fingerprint is canonical.

Formal `verify_bundle` checks the loaded project installation before and after gate recomputation, reads frozen documents from the original provenance tree, and compares the saved result bytes. These changes strengthen origin binding, but P1-1 prevents treating the a6 source-only helper as proof of the code actually executed. The runtime helper's synthetic PASS inputs in unit tests are not a substitute for a true verified Q11 gate.

## Independent tests and remaining evidence

Independent command: repository interpreter with `PYTHONPATH=src`, running `test_hosted_bounded_rejection.py`, `test_hosted_runtime_binding.py`, `test_hosted_verifier_installation.py`, and `test_hosted_negative_origin.py`, `--no-cov`.

Result: **68 passed / 114.53 seconds**. Log `/tmp/hm-q04-independent-unit-a6.log`, SHA-256 `5156b0fdf5faf5112a6decbf33bf196736b9e3de8126464f6f6e542da7bf8d64`. The real canaries above show why these synthetic semantic successes do not establish completeness of the new source and authority checks.

Completed actual attempt12 original profile/export/diagnostic evidence has not yet been provided for this phase. Its source-bound matrix, actual syscall outcomes, full saved results, and readonly original inventories remain to be independently checked after completion. The two a6 P1 findings require successor implementation evidence and regressions; design discussion alone does not close them. No full gate matrix or HM09 acceptance is asserted. **NOT_QUALIFIED remains required.**

## Follow-up: completed attempt12 originals and checkpoint scope

This section follows the parent's notice that attempt12 had completed **FAILED**, and its subsequent original Q03 diagnostic export. It supplements the first-phase report above; it does not replace either historical P1 or turn the failed attempt into a passing Q04. The first-phase report bytes had SHA-256 `4e99dcb94c3097ad60773e6ac69fc98472725a0a920d7fb0d50e086ceb38cd25`. Assigned model/effort remain `gpt-6.1-sol/high`; narrow-review attempt `1`; observed usage unavailable.

Completed original root: `/tmp/hm-stage-a6d1859-attempt12`, exact commit `a6d1859398225f94cdc75c7f80adc73b1cc9b4ad`, D `bab80b80d65268a75e529fb5e2ea2d82f9877fc1957c5d9f7bfff6d4fccb5895`, B `826a9e0996c34046331b90b79e154659ba9b716bed3c92cf4b01daa8e68c3d08`. Independent deployment reads matched both the original install inventory and provenance inventory. Original wheel `e62728a44924efa5d1b15164bf8f2f1125429efcd950901760337e2112599c0b` has its expected digest. All **145** QuantOS members have the exact expected member set and equal bytes across frozen git objects, original wheel, installed source, and original provenance source. The root checkout stayed clean.

### Actual thirteen-case Q04 matrix

| Q04 case | Original native completion | Independent narrow result |
| --- | --- | --- |
| frame_byte_cap | return 0; hashed observation present | bounded transition helper, 13 hashes |
| invalid_utf8 | return 0; hashed observation present | bounded transition helper, 13 hashes |
| duplicate_json_keys | return 0; hashed observation present | bounded transition helper, 13 hashes |
| unknown_fields | return 0; hashed observation present | bounded transition helper, 13 hashes |
| noncanonical | return 0; hashed observation present | bounded transition helper, 13 hashes |
| unknown_candidate | return 0; hashed observation present | bounded transition helper, 13 hashes |
| credential_like | return 0; hashed observation present | bounded transition helper, 13 hashes |
| known_schema_invalid | **return 1; no observation** | original failed attempt retained; partial trial/accounting facts verified below |
| unsafe_dsl | no root/completion | **NOT_LAUNCHED** |
| invalid_ast | no root/completion | **NOT_LAUNCHED** |
| outside_parameters | no root/completion | **NOT_LAUNCHED** |
| wrong_exact_fingerprint | no root/completion | **NOT_LAUNCHED** |
| wrong_structural_fingerprint | no root/completion | **NOT_LAUNCHED** |

The seven successful bounded cases have fresh empty-authority prelaunch records, matching complete original authority and channel inventories, actual three-process identities with container PID/namespace bindings, exact observation hashes and empty execution/Workflow/network-attempt lists. The independently reconstructed recipes and original before/after protocol/authority bytes pass the accounting helper; this is a bounded subset result, not a full Q04 gate pass. No export bundle containing the complete Q04 matrix was provided or asserted.

The eight Q03 transitions also completed return 0, with complete original inventories and observations. Their independent helper counts are 13 for each wrong-binding case, 16 for expired/cancelled, and 19 for conflict. These originals were subsequently independently verified through the saved Q03 source export below.

### Failed known candidate: original facts and reproduced finalization refusal

The original manager completion is `evidence/negative-run-838708ee8585a3915252b85ed847491b6e7c3b3026cee73fe425a53475b6a968.json`, whose file bytes hash equals its name. It records return code **1**, null observation hash, actual wrapper/init/service PIDs **1349102 / 1349103 / 1349104**, a fresh prelaunch, and full authority/channel inventories that still equal the retained original trees. There is no `channel/negative-observation.json`.

Readonly original protocol/event/Ledger inspection found:

- Two original issued requests; one unique submission and its accepted transport handoff. Fixed EXHAUSTED receipts are prepublished authority, not extra charged submissions.
- One native `SCHEMA_INVALID` trial with `execution_requested=false`. Its step has PREPARED and COMPLETED records with no execution request and no STARTED execution phase.
- The research budget **previous_hash** chain is INITIAL → RESERVED → SETTLED: trial charge 0 → 1 → 1, execution/compute 0 throughout, validation rounds 0 → 1 → 1. The original request remains STEP_COMPLETED; the second request has its original CANCELLED terminal. No refund is implied.
- Native governor verification of the campaign event chain and readonly Ledger verification succeed. There are zero files in the native execution authority and zero HostedCampaignReports.
- The frozen full candidate denominator has **two** candidates, while the retained event chain has **one** trial.

Using the existing adapter constructed readonly from the frozen original inputs, I reproduced `verify_preselection_dq_trials` rejecting immediately with `AutonomousOrchestrationError: DQ preselection does not cover the full candidate denominator`. Its first cardinality check rejects before any execution-receipt reading; no receipt repair or recovery was invoked. Complete original raw inventories remained unchanged. This reproduces the exact relevant frozen precondition and agrees with the fixed worker's sequence: initial resume consumed the invalid trial, then cancellation followed by another resume entered production report-only finalization. The original worker stdout/stderr was discarded by its fixed management launch, so this is a readonly reproduction of the cause, not a claim that a historical traceback was retained.

The production DQ finalization refusal is correct: it requires the full candidate denominator and exactly matching native receipts before P14c. One malformed admission trial does not satisfy that complete campaign requirement. The failed worker did not publish a fake report, and it never reached its final observation/repeat verification. Therefore this specific failed known-case attempt cannot prove the later seen-bytes/repeat invariants or obtain completion/source acceptance retroactively.

### Partial checkpoint design is permitted by frozen Q04, with explicit limits

The proposed successor worker can stop after a completed malformed-admission trial rather than cancel and force campaign finalization. Frozen acceptance Q04 requires bounded rejection, unchanged allowlist, original accounting for known candidate schema-invalid trials, no unknown-candidate trial, and no persisted credential-like rejected bytes. It does **not** require each management fault fixture to produce a complete campaign/P14c terminal report. C05/C06 explicitly distinguish transport acceptance from admission and STEP_COMPLETED from a full campaign result. This is an implementation choice within frozen Q04; no frozen-file amendment or weaker DQ predicate is needed.

The minimum legitimate checkpoint verifier must:

1. Verify the source-bound accepted original response bytes and exact expected malformed recipe; reconstruct the request/candidate/context/spec/input identities and original SUBMIT journal/accounting.
2. Reuse readonly native orchestration construction, `prepare_trial` and `finish_trial` against the **correct preceding event prefix**, proving the recorded idempotency key, candidate, no execution request, native SCHEMA_INVALID outcome, trial evidence and corresponding campaign event.
3. Bottom-up verify the native event and Ledger chains, their exact referenced object bytes, preserved initial prefixes, complete budgets through settlement, one trial/segment charge, zero executions/compute, and preserved full candidate/remaining denominator. If the service issued a second pending request, retain and account for its reservation explicitly.
4. Require no final report/selection/fake terminal and no execution receipt/result/sidecar. Account for **every** after raw file using exact verified references and frozen paths, including protocol publications, native trial/event/Ledger/request artifacts; reject unrelated additions. This must close P1-2 rather than simply dropping the final-report check.
5. Capture successful original management completion and observation, then repeat the original accepted/rejected raw bytes after expiry with the same receipt and unchanged full after inventory. Keep fixture/source labels synthetic and preserve the real syscall/allowlist evidence required by the whole Q04 matrix.

The verifier must not call `resume`, recovery, seeding, finalization, `_read_receipt` repair, or any execution/network/model method to make a checkpoint valid. An optional saved cancellation may be verified as an original receipt, but cannot justify resuming into a fabricated final report. If a genuinely consumed fixture naturally cannot reach this bounded checkpoint, retain it as another failed attempt; do not rewrite its production result.

The proposed new checkpoint code was still uncommitted/in progress and was **not** declared closed by this follow-up. Both P1 findings remain findings against frozen a6. A successor fixed commit, native canaries/regressions, and new actual profile/source-bound full matrix remain necessary before any new implementation closure. A permissibility conclusion about the checkpoint design is not a Q04 PASS, Q11 engineering-success exception, or HM09 acceptance.

### Original Q03 diagnostic independently reproduced

Diagnostic `/tmp/hm-q03-a6d1859-attempt12-diagnostic` binds manifest/qualification hash `d8fd68f4a49c7f63b997563367af22f88b853335a4b27e79607eab0f9bd8e48e`, retained original manager export `e5bbff940548291c32589b6f2217cc59a64ea788bccfcb3bbbd5b82c13c5eae4`, and result `1d5804cad2e4efb572131d3bc3aa022961dc5b4755573caf9a233665c55cc778`.

I independently reran `verify_manager_export` (**436 exact mapped files**), direct Q03 (**77 hashes**), and full `verify_staging`. The saved and recomputed results are **byte-identical**: Q03 PASS, all other eleven gates **NOT_EVALUATED**, overall **NOT_QUALIFIED**. Canonical manifest, full bundle file set/hash/lengths, exact original Q03 authority/channel inventory and before/after readonly state also match. Formal `verify_bundle` still rejects the diagnostic basename; no rename or override was used.

The diagnostic explicitly retains limitations `Q04_PARTIAL_FAILED_ORIGINAL_RETAINED`, `SOURCE_CACHE_AND_Q04_RAW_DELTA_P1_OPEN_ON_A6`, and `FAILED_ATTEMPT_LEDGER_INCOMPLETE`. Its failed-attempt reference list is empty, so it does not prove the final immutable historical failure ledger. The new export's inventory sidecars are only in manager evidence; neither original channel nor authority was altered.

Independent reproduction artifacts:

| Artifact | SHA-256 |
| --- | --- |
| `/tmp/hm_attempt12_completed_originals_review.py` | `38eac4f7fe2395c66adc846f09df013f65af43e69d6f1b8de9fa9163930ccba0` |
| `/tmp/hm-attempt12-completed-originals-review.log` | `23dcb557bd697de24ea3c9521575c1ea42e61fcb10ece090a06bfd76f38be48e` |
| `/tmp/hm_q03_independent_review12.py` | `2ab5f08ea3984168e963a0ac538ddefdf433387a7f00e17508d27ec5a652a9c0` |
| `/tmp/hm-q03-origin-independent12.log` | `e041e963376738babb7735ca53df649beeb370001e7a954c9d85391ebffce32e` |

The originals script logs budget facts sorted by timestamps, whose tied times are not a phase-chain proof; I separately followed their original `previous_hash` links to establish INITIAL → RESERVED → SETTLED above. Both inspections were readonly. Complete original qualification-case/evidence raw inventories were unchanged during the first inspection, and the diagnostic/original Q03/evidence inventories were unchanged during the separate source-export verification. Parent creation of the diagnostic happened between those independent checks and was not attributed to the reviewer.

Final follow-up status remains **a6 CHANGES_REQUIRED / ACTUAL_ATTEMPT12_FAILED / Q03_DIAGNOSTIC_ONLY / NOT_QUALIFIED**. The actual partial trial supports the bounded checkpoint design; it does not erase this failed native attempt or close the outstanding implementation findings.
