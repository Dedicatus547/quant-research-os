# Atomic snapshot overlap successor closure

Assigned model: gpt-6.1-sol; effort: high; independent successor attempt: 1; observed usage: unavailable. The overlap P1 in [the original snapshot/probe review](hm-q05-atomic-snapshot-probe-narrow-review.md) is **CLOSED for these bytes and the fixed existing-channel use**. **NOT_QUALIFIED** remains in force. Manager/source wiring and installed production bootstrap acceptance are outside this review.

Baseline HEAD is `cf9b2d4d776da1b9a67180b88b844d4cbcd0dc35`.

| Source | SHA-256 |
| --- | --- |
| hosted_atomic_snapshot.py | 9457d1ab57c2b5763888d02fc71ea2b96cef43fc16a5a2a69183f13da3aa8aeb |
| hosted_atomic_probe.py | 77b506943ccab8edc561ef324457976fdfb8d6d99ad57dbec037977dae62799f |
| hosted_atomic_forensics.py | eb7734e9d259a2bb01be519dcbe51fa5e5a6462269b2b77d0654073cba0e6396 |
| hosted_fault_cases.py | d6550d49fc969ca07cecd2f55a7504443c0fb5cb1953abcb655d86c68ee6020f |
| test_hosted_atomic_probe.py | 7b952aae73e2aaabfc9609740bc9241ed4e765ec51e28431df06b6bbac894909 |
| test_hosted_atomic_forensics.py | a4b67b5853e5dfb0e413a73594baa205770b6862df20da4ab8647aae60095e9d |

The helper now checks authority, channel, copied authority and both sidecar directories before any output creation. It rejects lexical containment, traverses existing components with O_NOFOLLOW and compares pinned device/inode ancestry to reject physical containment/aliases. The fixed probe already supplies a pre-existing empty disjoint channel. A nonexistent sibling channel whose nearest existing ancestor also contains authority is conservatively rejected; this closure does not promise support for arbitrary fresh channel paths.

The original canary was rerun unchanged. It now rejects with zero added files/directories, file count one before and after, and full original forensic facts unchanged. Log `/tmp/hm-atomic-snapshot-overlap-independent-fixed01.log`, SHA-256 `ec6756e1d33ced4fdb104e55009b47f92061bc3d363bb282f2f5bce4208eaf15`. Independent repository controls: **43 passed in 26.80s**, including same/inside/parent/sidecar-symlink rejection and all twelve physical probe windows. Log `/tmp/hm-atomic-snapshot-probe-independent-fixed01.log`, SHA-256 `828e56f5b7e28dbb96e123fcf3c8e9b83127faeaaabe4620f703ec0a8de01756`.

A separate real native spec `file_linked` canary confirmed the original two names retain their one inode and nlink2; canonical raw_inventory still rejects that original state. Snapshot copies have two distinct independent inodes, each nlink1, exact original bytes and a separately retained original physical-facts sidecar. Full original facts remain unchanged. Script `/tmp/hm_atomic_snapshot_physical_independent.py`, SHA-256 `97c9db99ed1ca7ebbe3b6731818675d8b280c41eba87e7397cde47039cdb4fd5`; passing log `/tmp/hm-atomic-snapshot-physical-independent03.log`, SHA-256 `a0d803c0230e25a47ec85ac54548d97aaf4b4d46ce4eec97cec48e78dbbf0daf`. Attempts01/02 are retained: the driver caught ArtifactIntegrityError rather than the raw reader's HostedQualificationError; attempt02 also encountered an unavailable unqualified python command. Neither is a product failure or passing control.

The enumeration-only move into hosted_fault_cases.py does not change fixed case behavior. Standalone schema correction and reader resource limits remain intact. Actual source binding, full production-loader restart immutability and formally installed observations are not established by these functional tests. No historical authority, frozen worktree, implementation, authentication or provider/model was modified or used by the reviewer. The original report remains unchanged, SHA-256 `5ac99a425ed5327bebb81213e430f4797fa342c6874921f11613b2ed4f2ed3b5`.
