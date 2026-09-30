# HM request export and Q01 successor narrow review

Date: 2026-09-30. Status: **REQUEST_EXPORT_REVIEW_NO_OPEN_P1 / NOT_QUALIFIED**. This review does not complete HM-07 or grant Q01, Q07, Q09, Q10 or Q11 qualification.

The independent reviewer was assigned `gpt-6.1-sol/high` under the user's development/review override. Observed model, effort and usage are unavailable. The frozen research profile remains `gpt-6-sol/high`. No additional agents were used. The reviewer read implementation and original diagnostic artifacts, ran offline checks, and added this successor record; no implementation, existing review or frozen record was changed. No real auth or vendor credential contents were read, and no commit was made.

## Exact scope and retained diagnostic

The base HEAD was `9ae5537dcb06cb2f9c6cd1caf85b8b65fa9f8022`. This review covers uncommitted request-export wiring in the fixed host wrapper/manager/live driver, the Q01 and Q11 draft predicates and their original-source bindings, the positive offline-run helper and manager sidecars, and the added C11 Ledger filename binding. The Q02–Q06, Q08–Q10 and Q12 acceptance matrix is not complete. The offline helper is not currently an implemented complete Q09/Q10 predicate.

The retained original manager root was independently supplied as `/tmp/hm-stage-9ae5537-attempt06`, profile `b9ff7d3c0986f9e7111cc739dcf5330907a5d3f6dd5b69f3e26835300311db9a`. The latest diagnostic directory was `/tmp/hm-q01-q07-9ae5537-attempt06-reverified-pending-summary`, manifest hash `87e697043cfc5c49ecf244c079c32a0a5ecda01e87be684732b1a439ebef66ea`.

The reviewer independently ran `verify_manager_export` and `verify_staging`, and required its canonical result bytes to equal the saved original `verifier-result.json`. They agreed exactly: Q01/Q07 PASS, the other ten cases NOT_EVALUATED, overall NOT_QUALIFIED. The saved result hash was `2db337001c6c19a07faaa511b027e008c10725239b1e29d5de100ed51243bfd3`.

Calling the publication-level `verify_bundle` directly on this diagnostic directory correctly failed its required `sha256-<qualification_hash>` basename check. That failure is not a Q01 scenario failure and was not bypassed to award qualification. Staging diagnostics and published qualification layout remain distinct.

The reviewer also checked the two earlier retained diagnostic directories, `/tmp/hm-q01-q07-9ae5537-attempt06` and its `-reverified` sibling. Both still retain Q01 FAIL and overall NOT_QUALIFIED, manifest hash `3d91f6c15a17edd0227857aa32119a5d36734bfefa44da55321560dd4e4cc49d` and result hash `6eb747178b30fab736db9924fc188b4676c47fc01dfde9bf17aaa0a57487effd`. They were not overwritten. The main agent identified the two prior predicate mistakes as rejecting the protocol's prepublished fixed EXHAUSTED receipts and parsing the public pending identity summary as a full request. Their corrected interpretation was checked against the actual implementation below.

Inspected working-tree hashes bind this narrow review; subsequent edits require matching checks:

| File | SHA256 |
| --- | --- |
| `scripts/hosted_live_qualification.py` | `9e89406fb8718c548292a382c9769c92a2fe9e08b399e2b98fc596492b8eaeee` |
| `src/quantos/infrastructure/hosted_host.py` | `bd8dde490cf94efed97e7cb84ddf58f81d2ba0ce10dbbb7f7a28da0063420066` |
| `src/quantos/infrastructure/hosted_manager.py` | `c78820a82685b95e50f77163b98371a767a8993dc951bfb4276f27f4404a2d5c` |
| `src/quantos/infrastructure/hosted_case_predicates.py` | `960407f5e234ea7eea1c2893a14662d19e890d2010f47017fee8de5073b9b649` |
| `src/quantos/infrastructure/hosted_offline_verification.py` | `f7589ca53c04518a22202311754d8f7c4c5de5d638d773327a75a72494f6c12c` |
| `src/quantos/infrastructure/hosted_verification.py` | `42b6a65ed3c3149cc78757b4d105b12d2234eb1f8346eb7f1bce3990faabd949` |
| `src/quantos/artifacts/store.py` | `fc6fd277f45ed1801f30315d6d261b5de2f1ea50e9054c216f7b3651327158ce` |
| `tests/unit/test_hosted_case_predicates.py` | `795a960a09c0d68fd03d56cd9e237126a045681c30cfd1bdcd2dc34ab1f86ade` |
| `tests/unit/test_hosted_offline_verification.py` | `debcc37ce2eb482420d91a7dcf0019cf23c5738c41501cb170ed1523405209db` |
| `tests/unit/test_hosted_cli.py` | `910aad2897c76d25271b5504c8c361d755102d5f700f1c0c3e78918ace9a4264` |

## Request export implementation

The public `pending` CLI intentionally emits only status, campaign hash, request hash and expiration. Treating its reply as `HostedAgentRequest` in the live driver was a real wiring error. The new driver uses the existing `request-export` CLI and compares the resulting complete request hash against the pending summary before checking the frozen hosted specification and preparing the request projection.

The manager adds only the fixed `request-export` operation to its existing operation allowlist and fixes its output argument to `/tmp/hosted-request.json`. The normal host namespace already has a private tmpfs `/tmp`; there is no new externally writable mount and no new RPC. The existing CLI asks the existing authenticated pending API, verifies the full canonical request/campaign/hash and creates an absent local file. The fixed wrapper then reads only the fixed leaf name through the existing bounded regular-file reader, validates `HostedAgentRequest` canonical bytes, and sends those exact bytes plus one framing newline to its captured stdout.

CLI import diagnostics and the export command's normal metadata stdout are redirected to stderr during the fixed wrapper invocation. Nonzero command results do not become request bytes. The reader rejects symlink, hardlink, FIFO, corrupted and noncanonical files, and has the request's existing 1 MiB cap. The manager's decoded object and the driver's typed validation do not redefine transport authority: the wrapper first requires canonical original bytes and the driver compares the content hash with the separately observed pending identity. Normal request issuance/reservation/authentication remains in the existing service.

No new clear P1 was found in that wiring. The attempt06 frozen install predates this uncommitted wrapper change. The existing actual Q01/Q07 diagnostic therefore does not prove the new request-export path in a deployed profile. A new exact commit/install/profile and an actual restricted fixed-wrapper export must be checked before using it as HM-08/live evidence. The review did not read model auth or run `drive_live_campaign`.

## Q01/Q11 and source bindings

Q01 now reads exactly one full saved request from the source protocol. The scenario reply may be either a full typed request equal to that authority, or the exact public four-key PENDING summary with matching campaign, full request hash and parsed expiration. Its two repeated pending replies must equal the recorded pending identity. Thus a summary does not replace the saved request, ContextPack, ordinal, attempt identity, expiration, reservation or checkpoint bytes.

The generic protocol verifier supplies exact journal/object/spec, budget chain/caps, request ordinals, request reservation and checkpoint checks before the scenario predicate. Q01 separately requires one reserved request, zero unique submissions, no terminal receipt, the sole INITIAL research budget with zero trial/execution/compute, two equal raw authority snapshots, six expected pending/status/resume replies and unchanged suspended status/budget/journal bindings. Any prepublished receipt must be EXHAUSTED, have zero observed bytes, no submission or prefix hash and identical before/after budget hashes. This does not allow a charged or accepted submission to be treated as an untouched pending state.

The two recorded wrapper PIDs must differ and both must appear in exported original service-start observations. Complete deployment/process evidence remains in the separately reviewed original manager root; a basename or synthetic PID alone is not an origin proof. The component unit fixture intentionally uses synthetic IDs to test only predicate logic. Actual qualification requires the original frozen launcher/install/proc/namespace observations and exact export binding described in the preceding Q07 review.

Q11 requires its root to map to the original live authority, rechecks the original live protocol and direct launcher source/projection/isolation records, requires those source hashes to be exported, and then calls bottom-up business verification plus the frozen Q11 gate predicate. It supplies the original `/inputs` root and provenance workspace. It does not turn the Q01 suspended diagnostic into a completed live model campaign or admit an uploaded TRUSTED label as a source. Original-manager selection remains an independent operator trust boundary.

## Offline helper and C11

The offline helper is a positive verification component. It checks successful original manager invocation, explicit mode/source/authority/profile, complete raw source and resulting authority inventories, fixed network-isolated argv/private staged capability, frozen offline program hash, exact observation hash, seed/flags/numeric environment and native execution/Workflow counts. Receipt reuse requires no execution or Workflow calls and unchanged native authority apart from the fixed observation file. Reexecution requires an initially saved-protocol-only target and exactly one native pipeline call per verified execution identity. These conditions do not implement the required Q09 tamper matrix or Q10 two-root equality gate by themselves.

The newly inspected durable prelaunch sidecar binds argv, source inventory hash and before-authority inventory before the subprocess is launched. The completion sidecar refers to that prelaunch hash, binds return code, after-authority inventory, offline program and observation hashes, and is exported from the original management root. The helper checks the original prelaunch bytes and their correspondence with completion. A timeout/launch exception can retain a prelaunch without a successful completion; that must remain a failed/incomplete attempt rather than be accepted as a positive run. Before full qualification, failure attempts still need their complete required outcome/retention accounting.

During review, the reviewer initially suspected that lexical `Path.is_relative_to` admitted `..` or intermediate symlink escape for the source root. This suspicion was withdrawn after testing the actual downstream reader: `opened_directory` starts at `/`, traverses every component with openat/O_NOFOLLOW, and explicitly rejects `..`. Both external canary paths were rejected by `raw_inventory` before data was read. No source traversal P1 was established. The safety argument depends on keeping that anchored inventory check before source use.

C11 still uses the same seven-schema allowlist, validates complete canonical `model_dump` bytes and projects only top-level `created_at`. Ledger snapshots additionally require the actual logical leaf name `sha256-<derived content hash>.json`, which closes the missing embedded-hash case in this comparison helper. The reviewer checked a correct hash-addressed path, equality for a date-only difference, and rejection of absent, ordinary and wrong-hash filenames. Filename binding complements the prior bottom-up Ledger/event/report verification; it does not replace it or waive exact raw inventories.

## Independent checks and outstanding qualification work

The reviewer ran the Q01/source/offline/CLI suites: **50 passed in 12.08 seconds**. The raw qualification suite added **5 passed in 5.13 seconds**, for 55 executed tests. This includes the seven Q01 negative cases and request-export reader positive/alias/corruption cases. The C11 and two source traversal canary checks above also completed independently. The latest original diagnostic staging result was mechanically recomputed and matched exactly; prior FAIL artifacts remain unchanged.

No new open P1 was established within this scope. Outstanding work remains the complete Q02–Q06/Q08–Q10/Q12 predicates and evidence, new deployed request-export bytes, actual completed live source and native replay scenarios, complete raw/runtime/export/failure-attempt manifests, full CI and mandatory exact-commit/bundle independent acceptance. The positive offline helper, component tests and diagnostic PASS cases do not complete those tasks. Overall status remains NOT_QUALIFIED.

Frozen hashes checked unchanged: contract `14704b9cbbe0f0ca281751833bc08248820da0c277a281a140bfd12bc6b102df`; acceptance `e5877b503259f6e758f22a6feb9307efdc45397155a9229527b2a8ae5dbfc55e`; freeze manifest `ac5a4c5e01e8c064906342607ff2ef9f3e9e9b98429188689e6873f76b2ee52e`.
