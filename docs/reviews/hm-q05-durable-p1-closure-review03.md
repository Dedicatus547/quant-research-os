# Independent Q05 TERMINATE corrective review

**NOT_QUALIFIED. The specific early-TTL TERMINATE counterexample is independently rejected by both the fixed scenario core and the native file-closure helper. Latest cancellation and expiry component positives pass, and verification remains read-only.** This is a narrow implementation closure finding; no full Q05, fsync/corruption, deployment or HM09 qualification is granted.

Assigned model `gpt-6.1-sol`; reasoning effort `high`; independent review attempt1; observed usage unavailable. Base HEAD `81638bbd1abb53123a3da30010c2b8064dbd0657`, uncommitted successor. This report covers only the TERMINATE increment. Earlier findings/closure remain in `/tmp/hm-q05-durable-implementation-review.md`, `/tmp/hm-q05-durable-p1-closure-review.md` and `/tmp/hm-q05-durable-p1-closure-review02.md`; they are not overwritten. Review02 retains SHA-256 `aefe3b6d5008ac0065d14b27e6e63e3c47e1e5849ce368a183c64795a8f697b1`.

No implementation/repository, original manager/bundle/actual15 or frozen worktree edit, credential read, model/provider call, commit or build was performed. Independent mutations occur only in disposable `/tmp` component copies.

## Exact latest source

| Source | SHA-256 |
| --- | --- |
| `hosted_business_file_closure.py` | `2d5951a1f082d7db6ed57e598c2cb59cb33ff017c9d75b76b749379d838bc83a` |
| `hosted_fault_verification.py` | `817180e9f9edfe6e244e0f8c45262d575d21b58a48ed9e8fc3de332c5015f11a` |

Exact copies are retained under `/tmp/hm-q05-review03-source-snapshot/` with repository-relative paths. Latest tracked diff SHA-256 was `9c280cdd54de66fd10217fe79f373b4eb98aa95b1fe5f468ee1e207e3e798977`; it excludes untracked files and does not enlarge this narrow review scope. Initial terminal closure hash `8e3b0e764fb2717bd2a9d71fdd8f7e1ee2ba1d3c531dca3fd2de5598f38f467d` differs from latest only by expiry-conjunction parentheses/line wrapping, confirmed by direct diff. Final double-gate canary and retained-native verification used latest2d5951.

## Change and independent result

The fixed cancellation case constructs the expected native terminal from original request and clock: CANCELLED/AUTHORIZED_CANCELLATION/fault.fixture, no business references. Authority and returned receipt must both match exactly. The expiry case constructs EXPIRED/REQUEST_TTL_ELAPSED/service, requires its original expires_at clock and no accepted response, checks exact authority terminal and pure native status.

The shared publication helper tracks accepted requests in journal order. Cancellation outcome/reason derives from prefix acceptance; expiry requires now>=request.expires_at, no prior accepted receipt, service principal, native reason and no business references. It retains exact canonical publication/time/production operation-ID checks. Neither path invokes cancel/resume or recovering status.

Independent physical `cancel-intent_published-1` positive passes before and after mutation. Recreated review02's self-consistent early-expiry false acceptance on disposable crashed/recovered/after copies: EXPIRED/service/REQUEST_TTL_ELAPSED at00:00, actual request TTL01:00, recomputed native EXPIRE operation ID, journal/object hashes, crash observation, inventories and returned terminal. Generic recovered protocol remains valid. The Q05 core now rejects with `Q05 recovered cancellation differs from native authority`; directly invoking the native file-closure helper on the same bad recovered root separately rejects with `native protocol termination differs`. Both checks leave raw inventories unchanged.

The latest expiry physical positive also passes. Its missing before/specs negative remains rejected without rebuilding the directory. Independently repeated native verification on the retained regression08 two-execution root under latest2d5951 passes all320 attributed paths and two ValidationReports, with execute/start/resume blocked. Complete original retained base raw inventory and every directory path remain unchanged. The existing synthetic component adapter/profile is used explicitly; this is not an installed source/profile qualification.

## Evidence and bound

| Artifact | SHA-256 |
| --- | --- |
| `/tmp/hm_q05_termination_semantics_canary03.py` | `08d4bc64784cc4a434732825d2707dc350fac49fa095be3f720ef62078d677ea` |
| `/tmp/hm-q05-termination-semantics-canary03.log`, both rejection gates/positive controls | `8553113da4e2accc985eb048f6927432ccc866a3863d874921d88f6e5151d51b` |
| `/tmp/hm-q05-successor-readonly-canary03.log`, latest expiry positive/missing directory negative | `6d60b42ed556213bde4cce180264cb66697bcb553c6f47e61a15aad9bb304fcf` |
| `/tmp/hm_q05_retained_native_independent_review05.py` | `672fae8a0066a8c23664a644da3dcf6dab2e116c14ef776f0ed53a29f2a9655c` |
| `/tmp/hm-q05-retained-native-independent-review05.log`, complete file/directory invariance | `e99907292af90ab4379445468f84c5e858b5214537c7953135b0994c87f56ea9` |

Parent regression09 reports1 passed/232warnings/599.73sec and loaded protocol/Ledger tuple fixes before TERMINATE strengthening; it is not evidence that the old run loaded this new predicate. Parent latest-code retained recheck `/tmp/hm-q05-all-retained-readonly-recheck01.txt` (SHA-256 `4f38d3c69cc2edf834d202a12353361db7793ebe1d4aab5db4cc374ec7730b4d`) records44 component PASS results and zero execution/Workflow/network calls. Reviewer inspected that completed log, but did not regenerate its full44 recheck. Independent latest cancellation/expiry controls, double-gate counterexample rejection and retained native read-only positive above establish this specific closure.

No earlier failed run is rewritten or retrospectively passed, and no new code is applied retroactively to frozen816 actual15. Source-bound fsync/corruption cases, complete formal Q05 dispatch and a new frozen installed actual matrix remain separate required work.
