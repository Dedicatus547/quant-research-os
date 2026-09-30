# Q05 completed-publication fsync P1 successor review

Assigned model: gpt-6.1-sol; effort: high; independent review attempt: 1; observed usage: unavailable. The specific missing-completed-object P1 is CLOSED for the reviewed successor bytes. Overall status remains NOT_QUALIFIED. This is a bounded code/component review, not Q05, HM09 or deployment acceptance.

The original report `/tmp/hm-q05-fsync-recovery-narrow-review.md` remains unchanged (SHA-256 `b33257bfa13e52886f74b1019993eca78a1a2cb6566e6c3d5bb4075ead48d888`). Its original counterexample and failing log remain preserved. No original authority, attempt16 worktree/installation, authentication, implementation or repository file was changed; no provider or model was called.

## Reviewed source identity

Baseline HEAD: `379bc4d327afcbc71c64166b645ee883c2e479f5`, with uncommitted successor changes. Source copies and the bounded two-file diff were saved in `/tmp/hm-q05-required-complete-review-source`.

| File | SHA-256 |
| --- | --- |
| hosted_store.py | 278b1c1be69e738edc030073014282aeed2490c3f444fde802017c4cd3562979 |
| test_hosted_atomic_fault_windows.py | 04aa357b37169ca5d3b51be55f62fb3d19c6c894618b18567778f6e674577ddf |
| review.diff | 56688671a20c21aacaef6389bf1486b06259da01c7737a87e4f4eedd820ef922 |

The new `required` set comes from every earlier COMPLETE's `artifact_hashes`. The production `_journal` parser first validates each COMPLETE tuple against its adjacent INTENT's publication hashes, operation identity/kind and timestamp. Thus the set represents completed publications rather than an unvalidated arbitrary list. Existing objects still undergo regular-file/single-link/name/hash/exact-journal-byte checks. `required ⊆ existing` is then checked before the pending-entry verification callback and `_finish`. Only publications exclusive to the final pending INTENT may remain missing; a shared hash remains required. Complete-only histories continue through the existing full snapshot validation without recovery writes. This implements the minimum correction from the original review without silently repairing damage.

## Independent observations

The original reviewer script was rerun unchanged against these successor bytes: the real fork exited 73 with pending native SUBMIT, the disposable tree's old REGISTER object was deleted, and fresh recovery rejected with `hosted completed publication is missing`. The same twelve files remained; no additions or changes occurred. Log `/tmp/hm-q05-prior-complete-missing-independent02.log`, SHA-256 `371177b16bf41b65cce32a84ecd4e62323c08969a1838ddcef00f1bbb50efd13`.

A separate successor canary strengthened that reproduction to compare all directory/file paths, device/inode/link counts and file hashes. It installed callbacks that fail if either pending-entry verification or publication fault hooks are reached. Rejection occurred before either callback, all seventeen directory/file entries stayed unchanged, and the process exited successfully. Script `/tmp/hm_q05_required_complete_directory_independent.py` SHA-256 `5ce30df15887ad5378504dbfe9ce7dfc3d11cce32f605f2a1341d1335de6c522`; log `/tmp/hm-q05-required-complete-directory-independent01.log` SHA-256 `b79b44a8509e3b88d4bd2c141bec6edca9291a718b29bc58881305d2895452ec`.

Independent repository controls: 19 passed in 12.91 seconds (`/tmp/hm-q05-required-complete-independent-tests01.log`, SHA-256 `4988fb04934fe2ef1480292cbbda00ef9266811bed6a18ac5052f950b984a2c6`). The two added fork tests cover a genuine pending protocol SUBMIT missing an earlier REGISTER object and a controlled store-only BUSINESS INTENT sharing that same missing earlier hash. Both reject before any file-byte mutation. The latter is correctly described as a store negative, not native BUSINESS qualification. Existing physical journal/object publication-boundary positives still permit and complete legitimate partial publication; repetition is idempotent. Existing spec and unfinished temporary/hardlink negatives remain covered.

These synthetic-input/component observations close the reported recovery-order defect only. The previously reported full49 Qlib/native run loaded an earlier store identity and is not reassigned to this correction. Frozen 1122922/attempt16 is not retrospectively qualified; formal source-bound Q05 and the remaining acceptance work remain outside this review.
