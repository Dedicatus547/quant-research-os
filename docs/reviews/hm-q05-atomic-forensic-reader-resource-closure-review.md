# Atomic forensic reader resource-boundary successor review

Assigned model: gpt-6.1-sol; effort: high; independent successor attempt: 1; observed usage: unavailable. The resource P1 preserved in [the original narrow review](hm-q05-atomic-forensic-reader-narrow-review.md) is **CLOSED for these successor bytes**. Overall status remains **NOT_QUALIFIED**. No worker/source-gate integration or Q05/HM09/deployment acceptance is granted.

Baseline HEAD remains `cf9b2d4d776da1b9a67180b88b844d4cbcd0dc35`. Successor copies are preserved under `/tmp/hm-atomic-forensic-review-successor-source`:

| Source | SHA-256 |
| --- | --- |
| hosted_atomic_forensics.py | d75a0c12726d1b132c8f6e7b4a48fa6580a2828754175fa6cc52f006813fe189 |
| test_hosted_atomic_forensics.py | e3b0cc80e37b4a4fc89057409f3ecf4777fc8e39e2399074edb935fd86ca0719 |

The original report remains unchanged (SHA-256 `ea5e0202d3ab08f0516db229cbdd7d855787893489a6763bcffd40e478f2f173`), along with its original source snapshots and failure logs. No implementation, historical authority, installed/frozen worktree, authentication or provider/model was changed or invoked by the reviewer. This new report is the only additional repository write.

## Correction and independent closure

`_bounded_names` now limits accumulation during scandir iteration, before sorting. Each directory reserves all immediate sibling names against the shared whole-tree budget before descending. Its closing scan is limited to the original name count; an additional entry immediately rejects. File metadata is checked against the remaining aggregate payload budget before opening or reading, and each read is at most 1MiB or the originally declared remaining size plus one growth-detection byte. A file that grows past its declared size immediately rejects. The 10k-entry, 16MiB-file and 64MiB-aggregate constants were not enlarged; aggregate payload accounting applies per capture, with two captures required by the reader.

The original physical sixty-five-entry/cap4 canary was rerun unchanged: it now consumed five entries before rejection and passed its bound assertion. Log `/tmp/hm-atomic-forensic-entry-cap-independent02.log`, SHA-256 `80ade8dde690e94c2e8ae4e09d4eb21537f9e4ce0ae1bd89664b67250c58584d`.

The aggregate cap8 fixture now consumed only the first six-byte file and rejected the next six-byte file before reading it. The three independent metadata race negatives continued to reject before read, during read and between captures. Script `/tmp/hm_atomic_forensic_successor_race_and_total_independent.py` SHA-256 `e9ca409d57fbed7c8caf85f9e66a69148b059512dcaa8a30752399543d41fee7`; log `/tmp/hm-atomic-forensic-successor-race-total-independent01.log` SHA-256 `059dd50c30940caffd62575a011dbda963916f3197ce8e32b7ab8141b0ee98c2`.

Three additional independent resource controls passed:

- Four immediate siblings consumed their full cap4 quota before recursion; the first child entry rejected after five total enumerations.
- A two-byte file grew to 2MB after its opening stat: exactly one three-byte read occurred, then growth rejected.
- One hundred new child names appeared after reading: the closing scan rejected after just two closing enumerations, four enumerations across the interrupted walk, rather than collecting the expanded directory.

Script `/tmp/hm_atomic_forensic_successor_resource_independent.py` SHA-256 `b67b18d40c92b94036f537a076044bc0dbc175ea6486104fdecdfd540148433e`; log `/tmp/hm-atomic-forensic-successor-resource-independent01.log` SHA-256 `ce4914c3553c0896b5d1d8693f5f2a597ba25d64b694f802e55bb78f79b8b65c`.

Independent repository controls: **41 passed in 14.80 seconds**, including twelve real native publication exits, alias/object negatives, explicit enumeration/read resource controls and the nineteen canonical fsync controls. Log `/tmp/hm-atomic-forensic-independent-controls02.log` SHA-256 `22322791f6b7c4b56a9778be4cc57a8337d6b13ff4fa47b6326943fee7a18c13`.

The native expected-publication derivation, exact finite hardlink pair rules, descriptor/stat race checks and forensic-only labels are unchanged by this resource correction. Canonical Store/inventory/path readers retain their single-link rejection. These observations close only the standalone reader's reported bounds defect; they do not turn caller-supplied expected publications or forensic facts into source-bound canonical authority, and do not retrospectively qualify any installation or failed attempt.
