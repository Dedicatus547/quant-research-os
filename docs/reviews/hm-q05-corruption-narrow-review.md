# Independent original Q05 corruption narrow review

**NOT_QUALIFIED. Five fixed corruption byte plans and production-parser rejection pass targeted component checks, but the original verifier has one independently reproduced directory-attribution P1.** A later directory repair is being developed separately and is not marked closed by this original report. No full Q05/MVP/deployment qualification or retroactive acceptance of frozen1122922 attempt16 follows.

Assigned model `gpt-6.1-sol`; reasoning effort `high`; independent attempt1; observed usage unavailable. Base HEAD `379bc4d327afcbc71c64166b645ee883c2e479f5`; original tracked diff SHA-256 `ab3a9b6492343a2cb184eb849fbcf52c4631e40648b82fe40933ca02f6ecbf9c` excludes new untracked source. Six exact original source copies remain under `/tmp/hm-q05-corruption-original-review-source/`. Reviewer made no implementation/source changes, touched no actual16 worktree/install/original evidence, read no authentication/model credentials and called no provider/model. Independent roots/scripts/logs are disposable `/tmp` synthetic native components.

| Original reviewed source | SHA-256 |
| --- | --- |
| `hosted_fault_cases.py` | `7a26b9eac632c7e8564bb102b1ecb3e5d3ba0a6d4496cf0381a9a4f3876697cc` |
| new `hosted_fault_corruption.py` | `06b0984d64a7748c60702adbf59ff14c98cd3cae279159447409993f7719a658` |
| `hosted_fault_probe.py` | `c9656741793b8c41d99f4bcecb83635ae736cffa683077f83506ab0841aa8396` |
| `hosted_fault_verification.py` | `c1944e886e0886a6b230f516d8d2da4ec269858562b1c7ba711714115bb33e3b` |
| `hosted_manager.py` | `70ed5f949ff64675f2910c02d7aa370c14a45514382589b60e464b3f7b5430bb` |
| `hosted_negative_origin.py` | `f2abaa537b84f4230c46688820322d33077cee941b7865f58047226bf481574e` |
| unit `test_hosted_fault_probe.py` | `0e6068a7b311a1d1923b0eb7fa23ff7428c70a69a35bdadfb2b24bcae91062c2` |
| integration `test_hosted_business_e2e.py` | `03fc1710015fe64a05f1f80ccbed377223208b5e67ba4263ca02cf99a21f317e` |

## P1: actual directory topology is not bound

Original core lines695–703 only require each producer directory list to be a list, equal to its other list and the other recovery's list. It neither compares those lists to actual phase directories nor verifies directory topology around the parser. Its exact before+damage closure is a file map, which cannot detect additional empty directories.

Independent native physical `corruption-journal_fragment` positive passes. Two negative changes both **pass the original full scenario core**:

- Replace both recoveries' before/after directory observations with empty lists although actual trees are nonempty.
- Stronger: on disposable recovered/after copies only, add `unobserved-recovery-directory`, leaving original records and all original files/inventories untouched. A real directory change after the crash is accepted. The original physical positive passes again afterward.

Neither negative changes original manager records or claims uploaded observations can impersonate source. The second exposes the actual-root omission even with unchanged observation bytes. Shared source/root-origin checks also bind raw files, not empty directory topology. `snapshot_management_authority` originally copies only raw files, so simply comparing future snapshot directory lists requires snapshots/exports to preserve empty directories too.

Minimum repair: descriptor-anchored no-follow directory inventory including empty directories, with safe type/count checks; derive actual four-phase lists and require equality for these directory-preserving plans. Bind each recovery record list to its actual phase tree. Verify full files and directories before/after production parser inspection. Snapshot/export must preserve original complete directory topology, and source wrapper must compare actual exported and original phase directories. Reject false empty lists, extra/removed empty directories and unsafe directory types without rebuilding or deleting them. This finding was sent immediately; successor closure requires a separate review.

## Corruption semantics and original positive checks

Each plan derives exact bytes from one verified unaccepted native request and zero submission charge. Prepublished EXHAUSTED receipts are correctly distinguished from submissions. Damage is fixed management-only: malformed journal fragment; filename/content wrong sequence; two pending INTENTs; canonical unpublished checkpoint; original request with an extra newline. The changed-artifact fixture deliberately modifies only its retained-copy request, retaining no-follow/regular/single-link checks and fsync. No host RPC/root/clock/fixture parameter is introduced.

The core verifies complete before protocol/business/frozen seed/file closure, derives the exact before+damage file map, checks every corrupt/recovered/after file map against it, then invokes the actual production store parser with recover=False. Worker bootstrap exercises the production recovery parser in two fresh child attempts and retains process records; the core separately verifies production parser rejection. Malformed fragment requires ValueError; the other four require ArtifactIntegrityError. A generic OSError or a handwritten REJECTED result cannot satisfy this predicate.

Independent functional test run: **5 passed /13.79sec**,36 unrelated cases deselected. Independently ran all five native-business-input components without execution: each original physical crash/recovery/recovery has exits73/74/74; all five production parser/core positives pass. Wrong error type with recomputed result hash, wrong parent waitpid exit and self-consistent extra damage bytes are rejected for every case. All original file and actual directory paths remain unchanged during these positive/negative verification calls. This demonstrates current observed read-only behavior on genuine fixtures, while the P1 above shows the verifier fails to enforce that claim against wrong directory facts.

Manager finite Q05 registry and shared origin gate select the fixed corruption worker/profile/module marker and retained prelaunch/kernel/completion records. The corruption subset still does not dispatch a full Q05 PASS. No actual installed kernel/source qualification was independently run here; native component bootstrap inputs are synthetic fixtures using production store/business logic, not live model evidence.

Evidence: `/tmp/hm-q05-corruption-independent-functional.log` SHA `35b97df331b84221d1db0035dbbc2410d9eff4404084c3eecc8b30cc0ef30578`; directory canary `/tmp/hm_q05_corruption_directory_canary.py` SHA `bc5a3099467434f15023898f951b38c71eed67c61f56aa899f529464c670c9fd`, log `/tmp/hm-q05-corruption-directory-canary01.log` SHA `051e1a15b68411a0dbbbefa772ba33c89fee4e7332fc56d8656e591059c48571`; five-window script `/tmp/hm_q05_corruption_all_native_independent.py` SHA `cd819fa0d7c16f422981eb2f24576486db5b2b199aeb3b7c83b39fe44c877541`, log `/tmp/hm-q05-corruption-all-native-independent01.log` SHA `42b6f90ab47457749292ef7f9e2bc3a9e02b2d27a1490ad4c2d3a35205c0b386`.

Parent-reported first fixture EXHAUSTED-receipt confusion and first native driver KeyError are preserved failures, not passed qualification. Parent later component positives do not override this original directory counterexample. Later source changes are excluded from the exact original scope above and will have their own closure report.
