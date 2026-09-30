# Independent Q02 original-evidence review — attempt15

**Narrow result: actual15 Q02 original-source scenario verifies; overall NOT_QUALIFIED.** Independent staging recomputation returns Q02 PASS, the other eleven gates NOT_EVALUATED, and exact saved result bytes. No additional Q02 P1 was established by this review. This is not formal hosted qualification, Q11 execution success, HM09 readiness or retrospective acceptance of attempts13/14.

Assigned reviewer model `gpt-6.1-sol`; reasoning effort `high`; review attempt 1; observed usage unavailable. Used only clean frozen worktree `/tmp/hm-negative-followup-worktree`, exact HEAD `81638bbd1abb53123a3da30010c2b8064dbd0657`; did not import/recompute against the root's Q05 development diff. No repository edit, original manager/bundle mutation, model authentication read, provider/model invocation, commit or push was performed. Review artifacts and negative-test copies are under `/tmp` only. The research model/profile is unchanged by this development review.

## Original identities and source proof

| Identity | Exact value |
| --- | --- |
| Original manager root | `/tmp/hm-stage-81638bb-attempt15` |
| D | `1c5041d717022ff0dce5976763fee552f7e711436a3a1fe3e7e40b74504d985f` |
| B | `eab6752191c6e297245980a5a0751069f8d4985852cf7573b44c659cc90df0b3` |
| Diagnostic bundle | `/tmp/hm-q02-81638bb-attempt15-diagnostic` |
| Manifest SHA-256 | `3253382d69dfbffb767abdec503a16abd23c5c3bf6121d523f15a5f846f9e079` |
| Original manager export | `ec280ddc58c650097786c03922073c8ab4c6c94c6cc68bc33b01ef10304aa810` |
| Exact saved result SHA-256 | `2fb3559ebbafe5c99b736b3993390ce8e592cec06c9656a228fd2b92b9e97ffe` |

Independently verified canonical manifest bytes and the complete exact bundle file set/hash/length map. `verify_manager_export` verified **427 original-source files**, the retained original export bytes, independent manager root, explicit commit/profile/configuration, complete installation/provenance inventories and exact original→bundle file mapping. Directly compared the installed duplicate-probe `.py` against `git show 81638bb:src/quantos/infrastructure/hosted_duplicate_probe.py`; bytes match. Its SHA-256 is `28ffc8524bfb0f494f4480a2dd18a5796a6b974a40e2738cea901e796e73fcd0`; the frozen duplicate-verifier SHA-256 is `7187e1d61661314c6e595e48c9790c5cab83e05ef178c566c0f4f6bde48a9ff9`.

The complete fixed source predicate independently reconciles each original observation with its hashed prelaunch/completion, fresh empty authority, frozen installed module hash, exact namespace argv and private descriptors, actual recorded kernel wrapper/init/service chain, `/proc` native executable hash/command, bwrap container PID/namespace information, separate net/pid/mount/user namespaces, frozen principal UID/GID and zero capabilities. It binds observed namespace parent PID from the saved kernel NSpid line. Completion return_code0 and observation hash are mandatory, and complete original authority/channel inventories must match their recorded and exported bytes. These are preserved original kernel observations bound to the launched fixed program, not a new query of expired/reused PIDs or a same-UID inference.

The two fixtures require all six original phase roots each, verify every inventory against its exact original source prefix, and verify protocol/object publication/budget structure before constructing read-only stores. Direct `verify_q02` checked **59 hashes**. `verify_staging` recomputation matched saved `verifier-result.json` byte-for-byte. Frozen contract/acceptance bytes remained `14704b9cbbe0f0ca281751833bc08248820da0c277a281a140bfd12bc6b102df` / `e5877b503259f6e758f22a6feb9307efdc45397155a9229527b2a8ae5dbfc55e`.

## Actual cross-process observations and accounting

| Fact | Accepted case | Rejected case |
| --- | --- | --- |
| Six namespace child PIDs | 50, 51, 52, 53, 96, 136 | 50, 51, 52, 53, 93, 133 |
| Namespace parent PID | 2 | 2 |
| All six waitpid exits | 0 | 0 |
| Stable lock `(device,inode)` | (2096, 4817798) | (2096, 4818474) |
| First two barrier flags | true/true | true/true |
| Two fresh-application resume flags | true/true | true/true |
| Native trial count | 1 | 0 |
| Native trial outcome | SCHEMA_INVALID, execution=false | none |
| Final unique submissions / first-request charges | 2 / 2 | 2 / 2 |

The repeated PID numbers across the table are in two separate freshly launched namespaces; within each case, all six PIDs are distinct and match actual parent waitpid accounting. The two first submitters read the before state prior to barrier release, contend through the existing cross-process campaign-directory flock, and return the same canonical receipt. The immediate repeated submission returns that same receipt with no additional publication/charge. The recorded lock device/inode stays the same before/after all calls within the case; production locking itself checks the opened directory's inode.

Both resume children invoke fresh real installed bootstrap/application construction in different processes; the capability-FD restoration defect from attempt14 is absent in this frozen successor. Their statuses match; the second resume's complete before/after inventory is unchanged. Every child and parent has empty execution/Workflow/network call lists. Native artifact verification separately binds one schema-invalid prepared/completed step, accepted exchange, logical event, Ledger object and research reservation/settlement with execution=0; producer counters alone are insufficient.

All phase deltas close: one initial SUBMIT; accepted native checkpoint with exact BUSINESS ID/time/publication closure; only the bound next-request cancellation pair/receipt between first-resume and after-business; no rejected-case business changes; exact before-cap checkpoint; one additional unique conflict/rejection to cap2; no raw publication for unseen exhaustion; original seen receipt retained after cap and TTL. The late-repeat and second-resume records both preserve complete raw inventories. No extra exchange, trial, step, event, Ledger entry, uncharged sidecar or arbitrary publication is hidden by these comparisons.

Independently checked the separate actual15 `known_schema_invalid` original Q04 checkpoint: worker return_code0, original safe observation hash and complete authority/channel inventories match, and the same installed-commit native component helper verified **26 hashes** without changes. This is one valid Q04 component, not its complete matrix: full Q04 remains NOT_EVALUATED in this diagnostic.

## Independent negative tests on disposable copies

The negative driver starts from the real native before/after/process bytes, with a passing copied-original core-predicate control. Original manager/bundle inputs remain unchanged. For semantic negatives it redirects source prefixes to disposable copied case roots and updates their copied raw file mappings; frozen offline inputs/profile and kernel records remain the actual original values. This isolates the core scenario predicate after the separately passing original-source gate. The redirected copies are **not** claimed to be new trusted manager exports or formal qualification bundles.

| Mutation | Independent rejection |
| --- | --- |
| Uploaded process PID bytes, original source/export unchanged | `exported file differs from original manager bytes` at full source gate |
| Duplicate submitter PID | `Q02 child processes are not distinct` |
| One changed post-call lock inode | `Q02 child source, lock, barrier or side-effect facts differ` |
| Wrong process phase | `Q02 process phase is unknown or duplicated` |
| waitpid exit changed to 1 | `Q02 actual waitpid/exit accounting differs` |
| Missing resume-2 evidence phase | `Q02 original process observations are incomplete` |
| Native SETTLED trial charge changed to 2 | `admission checkpoint budget differs from native event accounting` |
| Additional valid BUSINESS pair publishing an unrelated canonical trial | `admission checkpoint publication chronology differs` |

The budget negative replaces its content hash/object/publication and rebuilds the full subsequent journal hash chain and matching completion tuples. Generic protocol integrity still passes; native accounting rejects the changed charge. The extra-trial negative uses the existing store to publish a structurally valid, hash-consistent pair; generic protocol integrity passes, then native operation/publication closure rejects it. Thus those negatives reach authoritative native checks rather than merely malformed JSON or broken SHA paths. The exit negative targets the core's observation argument; the complete source gate separately protects uploaded observation bytes. Every semantic verifier call preserved copied before/after raw inventories. Restoring the copies returns the core positive control to PASS. Actual originals remained unchanged throughout.

## Evidence and qualification limits

| Independent script/log | SHA-256 |
| --- | --- |
| `/tmp/hm_q02_original_review15.py` | `d77d6fbe85c189be1d4b0e848615d9845c72af0503b030f7d10af7c5a4a4a716` |
| `/tmp/hm-q02-original-review15.log` | `6e7cca2f8277a142f854a06cf5440870f46947e8dd8c0e9ecbe3f2e7eb5c77bd` |
| `/tmp/hm_q02_original_negative_review15.py` | `4bdfd474eb17c0e11488c97979e7fe7a58f1d6e5934dde4d75da82a76e2f8f28` |
| `/tmp/hm-q02-original-negative-review15.log` | `6935f5604906d436c984f517dccde5f2bb096b8ea8d554d3c7f470f57ffd5906` |
| `/tmp/hm_q02_known_checkpoint_review15.py` | `ac1b3c2eac96bc481c634e34621e68727c0300104885a1cae4054f36614d0758` |
| `/tmp/hm-q02-known-checkpoint-review15.log` | `7a6ff984b14aaf341e7fe8aded1aed5317ab7395fe612605c46d10a765471687` |

These are independent staging/component recomputations under clean frozen code, not a formal verifier process launched from the installed native `/install` entrypoint. Called the ordinary `verify_bundle` without a basename override: it correctly rejected `qualification manifest bytes or path disagree`. No formal basename was fabricated and no source-only native-entry guard was bypassed to claim qualification.

The saved limitations are `DIAGNOSTIC_Q02_ONLY`, `Q02_NATIVE_SCHEMA_INVALID_TRIAL_NOT_EXECUTION_SUCCESS`, `FAILED_ATTEMPT_LEDGER_INCOMPLETE`, `NOT_QUALIFIED`; failed_attempt_hashes is still empty. Eleven acceptance gates are not evaluated. The accepted fixture intentionally tests one recorded schema-invalid trial, not profitable or successful Qlib/model execution, actual live CLI source/usage or Q11 success. Earlier 53bb/attempt14 failure is neither erased nor reassigned the new profile's result. HM09/full hosted acceptance remains unavailable. Clean frozen worktree and full original bundle/manager case/evidence inventories were unchanged at review completion.
