# Q05 fsync recovery independent narrow review

Assigned model: gpt-6.1-sol. Effort: high. Review attempt: 1. Observed usage: unavailable. Outcome: NOT_QUALIFIED; one recovery mutation P1 remains in the reviewed successor bytes. No implementation, original installation/evidence, authentication or provider was changed or invoked.

## Exact scope

Repository baseline: `379bc4d327afcbc71c64166b645ee883c2e479f5`; uncommitted store/fsync-test differences only. Reviewed source copies are under `/tmp/hm-q05-fsync-review-source`.

| Artifact | SHA-256 |
| --- | --- |
| reviewed hosted_store.py | 9ebdef159ef94613bf72b6b7bcf56b95ff3f28efdf88dd337042a76aa64b79df |
| reviewed test_hosted_atomic_fault_windows.py | 2b4c5371d07f81ee04637ec1c607f178aa8b7d5db4a7f944c532534128654145 |
| two-file diff /tmp/hm-q05-fsync-review-current.diff | 673ddaa2d352463f28ff5744d87d0ba718501e8285019fc5fe2828e1c408a19c |

This is separate from the preserved corruption-directory reports. It does not qualify Q05, HM09 or a deployment, and does not retrospectively apply to frozen 1122922/attempt16.

## Spec temporary-file correction

The earlier spec fix (`6800861ba0b7d3c79b79da1f412857eed41905bf7c4108a36ca31c65d59e9d85`) added `_require_spec_names` within the existing spec flock before either register or spec read. It uses the existing single-link regular-file checks and restricts names to exact hash-addressed `.json` paths. A leftover `.publish-*` cannot cause a new target to be published before rejection. It neither deletes failures nor relaxes the immutable writer.

Independent execution: nine atomic/spec controls passed in 9.70 seconds (`/tmp/hm-q05-spec-fsync-independent-controls.log`, SHA-256 `b2d4af3b85911ca72ffd647fa8fe25866bda10b925b2c0dfa4f77247c8e00409`). A separate disposable-tree canary placed a single-link temporary file alongside an already valid spec; both fresh register and spec read rejected without changing file inode/link count/hash or directory inventory, followed by the unchanged valid-spec positive control. Script `/tmp/hm_q05_spec_orphan_independent.py` SHA-256 `9b39956026d69840f9ee9e41173994bdf93723310fb6f63f08ba529a1452d199`; log `/tmp/hm-q05-spec-orphan-independent.log` SHA-256 `49d0f719898ccdc618b139e774cd2dabdd77a0f12cf3c29bff5451b2fd01beed`.

The parent's earlier 2-failure log represents one genuine spec temporary-file defect; the other file-linked case already rejected a two-link file and its test expected the wrong error wording. These facts remain distinct.

## Remaining P1: missing completed object permits writes before rejection

`recover_locked` now validates every existing object against the journal publication map before `_finish`. This closes the observed object-temporary/unknown/changed-file path. However, its subset check does not require the objects of previously completed operations to exist. Consequently, a damaged completed history can be mutated while recovering a newer pending operation.

Independent reproduction used a fresh synthetic component fixture in a disposable `/tmp` directory. Native REGISTER and ISSUE completed. A real fork submitted the response and exited 73 at `intent_published`, leaving a valid pending native SUBMIT. The reviewer then deleted only the older REGISTER spec object from that disposable authority (the separate registered spec remained). A fresh production `HostedProtocolStore.snapshot(..., recover=True)` eventually raised `hosted published artifact is missing`, but first published five SUBMIT objects and sequence-6 COMPLETE. File count increased from 12 to 18; no pre-existing file changed. This is rejection after mutation, not a successful recovery of intact history.

Script `/tmp/hm_q05_prior_complete_missing_independent.py` SHA-256 `b9a21b04ce43b270cee3543022f3e46fe6323a48b27ca2dd9656a6886b870da5`; retained failing log `/tmp/hm-q05-prior-complete-missing-independent01.log` SHA-256 `5174eda3a375ffbf44e38d3c1ba1d16570a78de554f008170ce960a005fae58e`. The assertion intentionally fails when the production recovery mutates the tree.

Minimum correction: before any completion writes, require the full publication set of every earlier completed INTENT to exist with exact bytes. Existing objects must still be a subset of the full journal publication set. Only the final pending INTENT may have missing publications; hashes also referenced by earlier completed operations remain mandatory. Preserve a positive test for a valid partially published final INTENT and negatives for missing earlier completed objects, including a hash shared with the final pending publication set. Assert exact files and directories remain unchanged on each rejection.

## Test identity limits

The reviewer independently ran the reviewed seventeen atomic/spec/journal/object controls: 17 passed in 10.56 seconds. Log `/tmp/hm-q05-all-fsync-independent01.log`, SHA-256 `fbf648f466be4ce658830ff544fc70ca8e69b4357504200ef1f40ce7a7ad3382`. They cover initial REGISTER boundaries and do not cover the completed-history-plus-pending counterexample above.

The parent reports 83 protocol/spec regressions passed (`/tmp/hm-q05-spec-fsync-after-fix01.txt`) and a complete 49-window native/Qlib business run passed in 659.51 seconds (`/tmp/hm-q05-native-corruption-full-regression01.txt`, SHA-256 `826bbb35b0ed810014b0ffb437a011b1e1f647277a563f0145830feabdd8502a`). That native process loaded the spec-name correction before the partial-object precheck was added. It is compatibility evidence for that earlier source identity, not a native positive qualification of the reviewed partial-object code. The review does not re-execute Qlib, repair retained roots, or convert synthetic/component fixtures into live-source evidence.
