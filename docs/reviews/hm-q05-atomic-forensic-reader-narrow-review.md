# Atomic forensic reader independent original narrow review

Assigned model: gpt-6.1-sol; effort: high; independent attempt: 1; observed usage: unavailable. This report preserves the original reviewed bytes and their resource-boundary P1. **NOT_QUALIFIED**. It does not grant Q05, HM09, deployment acceptance, or canonical authority to forensic facts. Subsequent repairs require their own source identity and observations.

## Original scope and identity

Baseline HEAD: `cf9b2d4d776da1b9a67180b88b844d4cbcd0dc35`; newly untracked `hosted_atomic_forensics.py` and its tests. The contemporaneous failure-location changes in the fault worker were outside this scope. Original source copies are preserved under `/tmp/hm-atomic-forensic-review-original-source`.

| Artifact | SHA-256 |
| --- | --- |
| original hosted_atomic_forensics.py | 0de6b4fd716291cc0653e42dff0e2afd00dbd33d929d127e85407e0f50fdf535 |
| original test_hosted_atomic_forensics.py | d2dc574e206a47835bcdbd2433651518a0b4223fdbf3631d595bb37b52cd9d59 |

No implementation, historical authority, installed root, frozen worktree, authentication or provider/model was changed or invoked by the reviewer. The only repository write was this requested report; independent controls used new disposable `/tmp` trees. The reader was not wired to a worker or qualification/source gate in this reviewed scope.

## Alias, path and race behavior

The pure expected-publication helper derives native spec bytes, the first REGISTER INTENT, or the first REGISTER object from the supplied frozen spec, native operation identity and exhaustion-receipt projection. It constructs no Store and touches no authority. The twelve native physical controls corroborated its path/byte derivation.

The reader anchors traversal in directory descriptors, uses no-follow directory/file opens and nonblocking file opens, validates logical paths, and compares complete stat identities around opening and reading. It rejects unsafe object types and unrelated `.publish-*` names. The two-link exception is limited to the exact supplied publication target and one same-parent `.publish-<32 lowercase hex>` name, exact publication bytes/hash, same device/inode and nlink2; third/outer aliases or different inodes are rejected. This is an observation over the caller-supplied expected publication, not independent proof that an uploaded path/value came from frozen management inputs.

Two captures include root and descendant directory metadata and file hash/size/device/inode/link/mode/uid/gid/mtime/ctime. An independent original-source canary deterministically changed metadata before reading, during reading and between captures; all three races rejected respectively as file-changed-before-read, file-changed-during-read and tree-changed-between-captures. This demonstrates those detection points, not a guarantee that two observations exclude every possible transient filesystem change.

The canonical Store, raw inventory and read-relative primitives did not acquire the forensic hardlink exception. Native pair controls confirmed their existing rejection. Facts remain explicitly FORENSIC_ONLY_NOT_CANONICAL_AUTHORITY / NOT_QUALIFIED. No alias/path escape acceptance was observed in these bounded controls.

## P1: advertised resource caps are enforced after excessive enumeration/read

Both directory scans first evaluate `sorted(item.name for item in os.scandir(...))`. The 10k entry cap is checked only while processing that already materialized list; the closing-name scan is also unbounded. Therefore a directory of arbitrary fanout can consume arbitrary enumeration time/memory before the cap rejects it. Independent physical fixture: configured cap4, sixty-five root entries, and all sixty-five names consumed before the expected entry-cap error. The original canary intentionally fails its maximum-five-enumerations assertion.

Script `/tmp/hm_atomic_forensic_entry_cap_independent.py` SHA-256 `c443bfcf03ea6c5e2bbba7423a8a5d60d0750a199da0fd16b8dd946a13f8acb4`; original failing log `/tmp/hm-atomic-forensic-entry-cap-independent01.log` SHA-256 `a71d82d3b5f9d145ae25e4da8e5121ba520bfb7a4f7264fc66f5f0dcd432d57a`.

The aggregate byte cap is checked only after consuming an entire current file. With an aggregate cap8, two regular six-byte files consumed twelve bytes before rejection. At production constants the aggregate reader may consume up to another file beyond 64MiB; file growth may consume the next chunk before its own cap check. These do not falsely accept an oversized inventory, but they violate the advertised read-resource boundary and should not be confused with a strict bounded reader.

Minimum repair: bound name collection inside scandir iteration, reserve all immediate sibling entries before descending so recursion cannot repeatedly spend their quota, and bound the closing scan to the original name count plus one. Before opening/reading a file, check its declared size against remaining aggregate capacity; bound each read by the declared remaining size plus at most one byte for growth detection. Add controls that observe enumeration/read calls, rather than only asserting the eventual cap error.

## Independent results and limits

The existing forensic and canonical atomic controls passed independently: 39 passed in 15.71 seconds. Log `/tmp/hm-atomic-forensic-independent-controls01.log`, SHA-256 `f29e1c83b8ebbd31a49e637b0c146f9094612aa51edba9d404501f9182b2eb8e`. This includes twelve physical exits, seven alias/object negatives, existing cap-error checks and nineteen canonical controls; it does not close the resource P1 above.

Combined aggregate/race script `/tmp/hm_atomic_forensic_race_and_total_independent.py` SHA-256 `bf1fd818b0e1ae759914bdbb909cb5ae4857e49b59f07f4b7cc70d1cc9d53cb1`; log `/tmp/hm-atomic-forensic-race-total-independent01.log` SHA-256 `51bdf8e31b7c8216efa0558801e09fef2657dbbe39bf977cc3fd3929fa9893b3`. It explicitly loads the preserved original source copy, avoiding attribution to in-progress repairs.

The author's earlier missing-directory-schema test failures remain failures; this review did not edit those roots/logs. A repaired standalone reader still would not establish fixed worker/source-origin or full qualification integration. No historical installation or diagnostic is retrospectively changed by this report.
