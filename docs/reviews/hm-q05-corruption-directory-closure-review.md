# Independent Q05 corruption directory corrective review

**NOT_QUALIFIED. The specific original directory-attribution P1 is independently closed at the reviewed implementation boundary.** No complete Q05/MVP/deployment qualification is granted, and frozen1122922 attempt16 is not retroactively changed.

Assigned model `gpt-6.1-sol`; effort `high`; independent attempt1; observed usage unavailable. Base HEAD `379bc4d327afcbc71c64166b645ee883c2e479f5`, uncommitted successor. Original report `/tmp/hm-q05-corruption-narrow-review.md` remains unchanged at SHA-256 `6eb9a73384056fd7668e3ec0c4ad56f0e449dd0860c7612673b2f5edb1d79e99`. No source implementation/original evidence/worktree/credential changes or provider/model calls were made by reviewer; all canaries use `/tmp` synthetic native component copies.

| Reviewed directory increment | SHA-256 |
| --- | --- |
| `hosted_verification.py` | `090c66ffcca5ae5dc692fe2ea27e2e0bb93d42bdb255297feb972bb6632e6e04` |
| `hosted_management_runtime.py` | `eb928fdb15046a2d07d5800ec0e29299ae7704e28c5d8d5397b1c7f2d4729ac4` |
| `hosted_fault_probe.py` | `1090d3f7e0e5e308d3b64fbbc69470d91312fddb1cfaa4d8a58f798a8e22d427` |
| `hosted_fault_verification.py` | `181b7fdd0214dc4a9f7889900c93a0340300e2f12497b3cd85310ae783eff032` |
| `test_hosted_directory_inventory.py` | `3f290256bb3d82caa40ae8de52683c31feef73bfe1272b391f9cfd035484c5b4` |
| integration `test_hosted_business_e2e.py` | `c3ad7bf15a88f271ae594f07f15ffa6a49c9ef54f401e1c56ac21670d5d9ade9` |

Source copies are retained under `/tmp/hm-q05-corruption-directory-review-source/`. Tracked diff at initial directory review was `2422802bd87765a3d7bdb6bc0cf12b1ad5fdad3b3c096af846a9850f59b1f7c1`, excluding new untracked files. Later broad diff `dcf83bc95e5f7561223e90e00982f891891bd0a4758a3fcae3ada42a96c31f57` includes separate spec-store changes and is not the narrow scope definition.

`directory_inventory` now includes empty directories with descriptor-anchored no-follow traversal, checks opened-directory identity against lstat, rejects symlink/special/hard-link entries and caps all encountered entries at100000. It does not create state. Snapshotting copies the full directory topology and verifies original/snapshot equality while retaining original raw-file rules.

For these directory-preserving corruption plans, the core derives actual four-phase directory lists, requires exact equality, binds both recovery record lists to those actual lists, and rechecks files plus directories after the production parser. Worker likewise uses the safe list before/after recovery. The Q05 source wrapper compares actual exported and original phase directory topology, so file-only equality cannot authorize an extra exported empty directory.

Independent re-run of the original native journal-fragment canary: false empty recovery directory lists now reject (`Q05 corrupt recovery did not reject without mutation`); adding an actual empty directory only to recovered/after with original records/all file bytes unchanged rejects (`Q05 corruption changed actual directories`). Original physical positive controls pass before and after. No directory is removed/rebuilt to obtain rejection.

Independently repeated all five native-input physical cases: production parser rejects the intended damage, exits73/74/74 are exact, and wrong error/result hash, wrong parent exit and self-consistent extra damage bytes reject for each case. Original complete files and directory paths remain unchanged throughout. Six directory tests pass in1.29sec: empty-directory snapshot preservation, directory/file symlink, hard-link/FIFO rejection and bounded empty fanout. The cap test deliberately lowers the existing constant rather than creating100000 directories.

Dependency boundary: first directory runs imported unchanged baseline store SHA `5ffbe3f32992a17eae9d828ff914d8f4e61b97a5b03ea420e5833bcbb0d099ca`. The parent subsequently introduced the separate spec-name scan, store SHA `6800861ba0b7d3c79b79da1f412857eed41905bf7c4108a36ca31c65d59e9d85`. Reviewer repeated the five native corruption positives/negatives with that new store dependency and they still pass read-only. This is compatibility evidence; the spec-temp corrective logic itself requires its separate review and is not declared accepted by this directory report.

Evidence: directory canary02 `/tmp/hm-q05-corruption-directory-canary02.log` SHA `ffef43d4ef40c99adf3c2c48e8f6cbcca58b74bf652eeddf0f6987c8af43de6f`; native repeat02 and new-store repeat03 `/tmp/hm-q05-corruption-all-native-independent02.log` and `/tmp/hm-q05-corruption-all-native-independent03.log` both SHA `42b6f90ab47457749292ef7f9e2bc3a9e02b2d27a1490ad4c2d3a35205c0b386` (identical printed assertions, separately executed processes); directory unit log `/tmp/hm-q05-directory-inventory-independent-tests.log` SHA `8b91caafd2d4505ad10e772564f6316f3792e6ebea14f07bfe29e6b05299f262`. The unchanged canary script identities are recorded in the original report.

These are synthetic native component checks, not actual installed kernel/source qualification. Full source-bound fsync/corruption matrices, complete formal Q05 dispatch and a new frozen installed actual run remain outside this closure finding. Original failures and attempt16 installation/evidence are preserved.
