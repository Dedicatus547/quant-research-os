# Atomic production restart side-effect corrections

Assigned model: gpt-6.1-sol; effort: high; independent attempt: 1; observed usage: unavailable. **No new P1 found within these two corrections. NOT_QUALIFIED.** This is an additional scope after [the functional snapshot/probe review](hm-q05-atomic-snapshot-probe-narrow-review.md) and [overlap closure](hm-q05-atomic-snapshot-source-closure-review.md). It does not review the new manager/verifier wiring or grant Q05/HM09/deployment acceptance.

Baseline HEAD: `cf9b2d4d776da1b9a67180b88b844d4cbcd0dc35`. Exact five-file diff retained at `/tmp/hm-atomic-restart-source-independent01.diff`, SHA-256 `08c38ec1e4e4870f2816851b691b84d42505ea9decb86dbe9268960b4c69d132`.

| Source | SHA-256 |
| --- | --- |
| infrastructure/hosted_store.py | 066739311039db6e2df1e67aabace2d688ba689eaaaa391c18f3a609e556ca0c |
| infrastructure/hosted_service.py | c0eb6996dd6f8ecb3f1270d462aefcfc7dc4a2987ff75dca50155320d0e5b530 |
| application/hosted_inputs.py | 62ad160d8bf589b9c74712e0faffa71971b671217ce77702acb7906e889f59a0 |
| artifacts/store.py (existing primitive, unchanged in this diff) | a01b07d546bb6f3ebf24f36a5677f32bd62e77a3723b90ca4095cca4a6055da8 |
| test_hosted_atomic_fault_windows.py | b4ecb45467d41b3bd4056269fade9966d7a4cc5908dbd9680ca83b84a58a8a2b |
| test_hosted_inputs.py | fca3328b4fae0e14eeec921329170bdd453a83bda6114bc62e98136e42d2e350 |

`verify_spec_registration(expected)` holds the existing spec flock, checks safe single-link file names, permits an empty fresh registration, otherwise requires the one exact frozen spec basename and exact canonical bytes. It performs no publication or recovery. Production bootstrap invokes it before any campaign recovery and before `load_hosted_campaign_application`, so unfinished spec temp files, aliases, unrelated registrations and changed spec bytes cannot first trigger business materialization. Existing Store construction retains its creation behavior; this check does not claim to provide a generally read-only bootstrap on arbitrary damaged/missing roots.

`_publish_seed_file` validates source size and hash against the frozen input before destination handling, traverses the destination parent with the existing O_NOFOLLOW primitive, and reuses `atomic_write_bytes_at`. The primitive reads an existing exact single-link target and returns without allocating or unlinking a temporary publication. Existing conflicting bytes and aliases reject before publication. This preserves native create-if-absent behavior for genuinely new seed files, while repeated identical materialization does not change file or parent-directory inode, mode, ownership, mtime or ctime. Atime is excluded from immutable forensic facts and is not asserted unchanged.

Independent controls: **25 passed in 12.16s**, including physical fsync rejection and seed alias/idempotence cases. Log `/tmp/hm-atomic-restart-source-independent01.log`, SHA-256 `51712d10bcb821e9a071d6d89f3bbaf081795dff0614777e7c98bc20f2124cab`.

An additional independent canary used a real native spec `file_fsynced` exit73 and required complete forensic equality after the new preflight rejection, including all directory metadata. It also verified exact registered-spec idempotence, wrong canonical bytes under the correct name and an additional safe hash-named spec, each rejected without changing retained files/directories or physical facts. Seed controls separately verified identical republication and a different already-existing target: the latter raised ArtifactConflictError without changing retained metadata or files. Script `/tmp/hm_atomic_restart_preflight_independent.py`, SHA-256 `4081d6e7f9b28d21e4386cdee80ef760622ca238faed1bd6551cd64d24491ee9`; passing log `/tmp/hm-atomic-restart-preflight-independent01.log`, SHA-256 `2c33cadbd5e00615aa60cfe47da70bc2500d070c600ce0a50500993e3d78d122`.

The reviewer neither ran a complete installed bootstrap nor called an authenticated provider/model. Actual fixed-production factory execution, full before/after physical observations and external manager/source binding remain necessary for any subsequent formal acceptance. Functional bootstrap substitutions are not provenance evidence. These successor bytes do not retrospectively qualify any prior installation, corruption/durable attempt or failure. Original review reports, historical evidence and frozen worktrees remain unchanged; the reviewer wrote only new reports and disposable /tmp controls.
