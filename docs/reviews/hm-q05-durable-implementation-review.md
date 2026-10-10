# Independent Q05 durable-subset implementation review

**NOT_QUALIFIED. Three independently reproduced P1 defects block acceptance of the reviewed durable predicate.** The physical process/FD tests pass; they do not close the scenario verifier's file-delta, result-binding and read-only holes. The parent acknowledged the findings and started a successor repair; this report covers the original reviewed bytes, not that subsequent repair.

Assigned reviewer model `gpt-6.1-sol`; reasoning effort `high`; review attempt 1; observed usage unavailable. Base HEAD `81638bbd1abb53123a3da30010c2b8064dbd0657` in `/home/zjw/quant-research-os`. No implementation/repository edit, original actual15/diagnostic mutation, clean worktree mutation, credential/model-auth read, provider/model invocation, commit or push was performed by the reviewer. Test/canary fixtures and review artifacts are under `/tmp`.

## Exact original scope

Initial tracked diff SHA-256 (`git diff --binary`): `636947674060940051cbbaa1f7a1aadc3f648fe4f4e295c4e00b809fbe9bcdee`; it was unchanged through the first two successful canaries and capture of original code. Initial tracked scope: 13 files, 889 insertions and 395 deletions, plus new untracked Q05/runtime/test files. A git diff hash does not include untracked files; the important individual source hashes are recorded below. Later tracked hash changed while the parent repaired the findings and is not used as the reviewed original identity.

| Reviewed source | Original SHA-256 |
| --- | --- |
| `hosted_fault_cases.py` | `7681c79b3426f2f4190f6c3ae92382d1e34c899f14a3b41ef1a53688747ec2f9` |
| `hosted_fault_probe.py` | `1f70c24d1272508e2153e17821700d81b5f72de15d7f02403e8f4342c48f0ccc` |
| `hosted_fault_verification.py` | `0c635ce633edc56228425a51dc0609fa46e0fdeceaa38fabeaad732fb98a85d8` |
| `hosted_management_runtime.py` | `4a527219a3079c8be52399352fd964ccb93d2560c8338709c35798b9fb8d8e85` |
| `hosted_business_verification.py` | `7d4756989fbba4ee205fc208fac85eeb61a5a42357fbc482f0ba7f2bfe63a6ae` |
| `hosted_negative_origin.py` | `fe9f0e9cef3f940b9944638ff995396d212fe9c5ba5b12da7159006e221bb2cf` |
| `hosted_admission_checkpoint.py` | `e52c25dfe3bb3a7d5ff0a7f3df7986ef89d7a76b0c61b69ff5c375493d015256` |

Original verifier and business-verifier source copies are retained under `/tmp/hm-q05-review-original-code/` with the exact hashes above. The third canary explicitly imports those copies, so the parent's in-progress repairs cannot accidentally turn the original finding into a successor test result.

## P1-1: additional recovered files acquire implicit permission

Original `verify_fault_recovery_scenario` requires recovered==after and preservation of existing principal files from before→crashed→recovered (lines426–435), but never establishes the complete allowed set of newly created principal files. The transport branch verifies native initial budget/events/Ledger; it does not reject a separate unknown file. Source hashes and accurate inventories establish what was produced, not whether every produced file is authorized by the native transition.

Independent native component reproduction at `register-intent_published-1`: genuine physical exit73 and two new application recoveries pass the original core. Add `unpublished-q05-review.json` to recovered and after, and update the two recovery inventory observations to the exact new inventories. The core still passes, verification remains read-only, and the file has no protocol publication, native trial/event/Ledger or execution-artifact role. This confirms the acceptance gap with real native component state, not merely a guessed producer PASS.

Minimum correction: derive exact new protocol publication/operation, event, Ledger and native execution-file closure for each phase; compare the full raw delta. Do not treat arbitrary new files, arbitrary journal publications or the final inventory itself as permission. Runtime exclusions must remain restricted to verified native execution identities and their fixed recorder prefixes, while all runtime/raw bytes stay observable. Add unknown recovered file, valid orphan publication, misplaced native artifact and recorder-prefix negatives.

## P1-2: two matching canonical results need not match native authority

Original lines278–292 check first/second result equality, parse the expected result schema and validate its own content hash. They do not bind that result to the recovered native status/receipt/report. A valid but wrong result can therefore be consistently reported by both recoveries while authority verification succeeds.

In the same passing register physical component, independently changed both recovery `HostedCampaignStatus.state` fields from WAITING_FOR_AGENT to the legitimate enum value RECOVERY_REQUIRED and recomputed both canonical result hashes. The native recovered state/artifacts were unchanged. The core still passed. This does not assert that the production host can rewrite original management records; it shows the source-bound scenario predicate cannot catch a real producer/result discrepancy.

Minimum correction: bind canonical returned receipt/terminal/status/report to exact recovered authority references and derived native facts for each action. Construct/read the expected projection without bootstrapping, recovering or invoking a status method that repairs authority. Check full result fields/hash and applicable clock/request/budget/head/report references, not only two producer results agreeing. Add valid alternate enum/result reference and request/receipt/report mismatches as native-copy negatives.

## P1-3: before-root inspection can rebuild missing directories and still pass

For expire (original lines226–228) and admission resume (lines387–392), the original helper constructs `HostedProtocolStore` on before without first validating the complete protocol root. The store constructor creates directory structure. Raw inventories contain files rather than empty-directory topology, so the helper can silently repair a missing directory while all file-inventory checks still agree.

Independent `expire-intent_published-1` native physical positive control passes. Delete only the disposable before `protocol/specs` directory (and its original spec file), then call the original helper copied above: it **passes**, recreates an empty specs directory, and reports unchanged file inventories across the verifier call. This is both an omitted before-root completeness check and a concrete violation of read-only verification. No original manager/deployment evidence was changed.

Minimum correction: verify every nonempty complete before protocol before constructing a store, especially both branches above. Empty REGISTER/start before roots may bind their real empty sidecar/fresh prelaunch and inspect directory identity without a creating constructor. Crashed pending INTENT roots must continue to be inspected without a recovering store. Add missing specs/campaigns and corrupt/incomplete before roots, asserting both rejection and unchanged directory topology.

## Other reviewed boundaries

The finite registry contains 28 protocol, 7 schema-invalid admission and 9 native execution windows. Only management's fixed `--case` selects them. Fault callbacks are explicit Python dependency parameters with defaults None through service/store/native business loading; no RPC, profile JSON, proposal, environment, arbitrary code, clock or root option exposes them to the research host. The manager requires new retained case roots and fixed installed module/namespace argv. The immutable openat/fsync primitive adds explicit callback points after file fsync/link/unlink/directory fsync; normal duplicate publication still returns without opening a new write window. Physical atomic-boundary unit tests cover retained temp/hard-link states, but those tests are not the missing source-bound fsync/corruption acceptance cases.

Private authorization stays in parent RAM: single hydration, exact slot100+index and 32-byte pread capture, private memfd restoration at offset0/close-on-exec for each cold bootstrap, normal production consumption/close. The Q02 helpers retain their old aliases after extraction; actual credential bytes are absent from inventories, counters, argv, environment and logs. Each fault child invokes a newly constructed production application from disk; the parent does not carry forward a repaired child application. Three actual fork/waitpid records require exits73/0/0 and distinct child PIDs; first and second recovery result/inventory equality supplements, but does not replace, the required native bindings above.

The cold-parent execution fixture avoids invoking training before the fault fork. Recovery selects unattempted candidates from on-disk native research-budget facts rather than repeatedly choosing the first candidate option. Execution receipt reuse is verified via the existing native inspection path. Durable STARTED with no verified receipt must remain RECOVERY_REQUIRED/EXECUTION_UNCERTAIN with its trial/execution/compute reservation retained and no recovery execute/Workflow call; it must not refund or infer that execution probably never occurred. The original core has these explicit count/denominator checks and both recoveries are offline; a frozen installed source run is still required.

The native helper extraction substantively recomputes PREPARED/STARTED proposal/execution identities, event time, native reserved workload and budget operation IDs/times, and closes published trials against the event trial set. The default Q04 checkpoint remains strict: `allow_pending_successor=False` requires the original cancellation shape, and the Q04 wrapper separately checks its cancellation. Q05 admission alone explicitly enables a pending, active, unaccepted second request. This flag is not a host/RPC option.

One additional static suggestion was sent without labeling it a reproduced P1: the extracted step helper should also reuse the existing native `verify_research_facts` accepted-receipt→exchange/request/reservation checks, or explicitly repeat them. The full business verifier's manual extraction otherwise does not itself invoke that existing static checker. This requires successor inspection; the three confirmed defects above are independently sufficient to block acceptance.

Shared `verify_managed_fixture_source` preserves Q02/Q03/Q04/Q08 source/kernel/prelaunch/inventory controls and extends only the fixed Q05 family. Empty before roots cannot derive a prefix from file members; the new Q05 path instead requires an exact original phase-inventory sidecar source path, complete original empty inventory and fresh prelaunch, which is an appropriate explicit binding. Original actual15 is not reinterpreted using the refactored code.

## Independent verification and preserved failures

- Physical protocol/admission, atomic fsync and private-FD/Q02 tests: **48 passed /128.97 sec**, `/tmp/hm-q05-independent-physical-and-fd.log`, SHA-256 `2e5517a8750e19847327c0e50f3b43fbe636f4b5aa8b0c94afc9a2c9f2d6d99d`.
- Shared original-source regressions: **38 passed /131.12 sec**, `/tmp/hm-q05-independent-common-origin.log`, SHA-256 `3851da34ed20cc9498e33a84a84ff73e82a73809cea718a4692ef7f4a2934936`; the reviewed common-gate SHA-256 stayed `fe9f0e9cef3f940b9944638ff995396d212fe9c5ba5b12da7159006e221bb2cf`. These source/kernel records are unit fixtures, not actual namespace qualification.
- Native false-acceptance script `/tmp/hm_q05_core_closure_canary.py`, SHA-256 `3564586c6fa80d9e6de8b980f42551087217a66af1a705c3b547c8ba7c14de78`; successful two-defect log `/tmp/hm-q05-core-closure-canary02.log`, SHA-256 `2181955cc5af602b6f91c66af5f51683b92ae50cbb57105c1e5d6f637a12e877`.
- Initial canary log `/tmp/hm-q05-core-closure-canary.log`, SHA-256 `6fabad68c658e4ce2531eea503ace51b13b7a2b7a0cceff6ecd67100704751e5`: first file-delta false acceptance was reproduced, then the reviewer's second mutation used invalid enum READY and failed validation. This failed test setup is preserved; the corrected valid-enum run02 proves P1-2.
- Original-copy read-only canary script `/tmp/hm_q05_before_readonly_canary.py`, SHA-256 `1bbbcd1e2b7f76c42197fab9a61a3c811f12bd87f2c2408aa496dc6d34272bf7`; log `/tmp/hm-q05-before-readonly-canary.log`, SHA-256 `20ae16493639abefaa04e1f948ea06d633e9c67a9f76f9315a153a701eddac38`.

The native canaries use the existing integration fixture's synthetic frozen inputs with real native orchestration, physical exits and fresh service/adapter construction. They stop at the targeted nonexecution case and do not invoke model/provider or claim an installed live source. They are meaningful predicate negatives rather than the entire native integration run.

Parent-reported cold-parent 9-window run03 passed472.55 sec. Full44 run05 passed590.95 sec but loaded code before the latest PREPARED/budget strengthening. Run06 later passed627.08 sec with those bindings/negatives, still before the pending three-defect repairs. Neither run proves a repair it did not load. The earlier training-before-fork SIGSEGV and first-candidate-repeat failures must remain recorded. Passing production/component regressions do not override these separate verifier canaries.

## Acceptance boundary

Q05 durable helper is intentionally not wired into full `verify_case` PASS. Source-bound file/directory fsync and corruption/fail-closed cases remain incomplete. No new installed Q05 namespace/source matrix or model original evidence was reviewed. Parent paused commit/build/actual16 after the findings; the revised bytes need separate independent closure tests and a new frozen profile before any applicable actual-evidence conclusion. No Q05, HM09 or full hosted qualification is granted. No successor code is applied retroactively to the frozen816 actual15 installation or diagnostic.
