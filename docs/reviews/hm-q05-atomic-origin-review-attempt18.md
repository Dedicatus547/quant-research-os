# HM Q05 atomic original-source narrow review — attempt18

Status: **VERIFIED_ATOMIC_SUBSET / NOT_QUALIFIED**. No blocking P1 was observed in this bounded original-source review. This is not full Q05, Q06, Q11, HM09 or MVP acceptance.

Assigned model: `gpt-6.1-sol`; reasoning effort: `high`; independent review attempt: 1; observed usage: unavailable. The failed independent-driver invocations described below are retained separately.

## Exact observation identity

All imports and source reads for recomputation used the clean worktree `/tmp/hm-q05-atomic-installed-worktree`, HEAD `93fef2875bcf10386badb921f6ede112cf2704c5`. `git status --porcelain` was empty before and after. The imported atomic verifier's `__file__` was inside that worktree. The ordinary root workspace's dirty Q06 successor code was not used. Repository AGENTS.md was read; no implementation, frozen worktree, original evidence, authentication or provider was changed or invoked.

| Binding | Observed SHA-256 / identity |
| --- | --- |
| Original manager | `/tmp/hm-stage-93fef28-attempt18` |
| D / installed profile | `8af66253b6f052821ab4d8a9f4caca1d78e348311e4e98ca439f4ec89f54580b` |
| Frozen B | `aa03f815f0c5701c676fd6ae943ab68bd8493720b53db46545e84089b19471ef` |
| Installed wheel | `de30b64fce57fbe49d50e25e2fe1594e405d53e21fc9f0e2992c5ff0246fe217` |
| Native `python-seeded` image | `e22006d8367f4ddd15cf90877f2de5a67b369ccce47f872d7bee778e438f94e5` |
| Mount policy v2 | `8d1b9175f41626fbd33eed6c6d350a0fbb6003dbe59536fba29e8d8a00fd2d4d` |
| Campaign | `dab81ad199fd4fb2b38add47a45c8c722a440aa6cb23b260c0ada24f9bf64f26` |
| Diagnostic bundle | `/tmp/hm-attempt18-atomic-diagnostic02` |
| Qualification manifest bytes | `418ec5c9b108d4d44fd17d5d3e8ad0a1484697958ab4d12c2586bcd9b2cf8d1e` |
| Original manager export bytes | `0dbb89f3b1b6769942c2b91ac317b216144364302a17a4b7faa935be3ae6621d` |
| External atomic result bytes | `35973fc6ca4c5505724df560fd3dd42d9fa3672047756ef3a0b662a4c1129a08` |
| Formal verifier result bytes | `06655d8ce193c5912b82b601ce0f9f6e63ad332f7761c8988a1a9d2ca0bce404` |

The export contains **565 original-file mappings**; the manifest contains **567 files**, including `manager-export.json` and `verifier-result.json`. The diagnostic case index is `diagnostic/q05-atomic-case-index.json`; its 48 roots cover exactly spec/journal/object × four fsync windows × four snapshots.

## Independent original-source recomputation

`verify_manager_export`, `verify_q05_atomic_subset` and `verify_staging` were rerun from the frozen source. The 124 checked artifact hashes matched the external atomic result's complete ordered list. `verify_staging` reproduced the saved formal result's exact canonical bytes: all twelve gates are `NOT_EVALUATED`, eligibility is `NOT_QUALIFIED`, and every formal case index, including Q05, has empty roots/evidence. The separately indexed atomic subset is deliberately outside that formal qualification dispatch.

The original retained export, each mapped original file and each exported file were reread. The frozen verifier rechecked the exact full installation inventory and provenance inventory, D/commit/lock bindings and the precise mapping set. Independently, all **160 installed QuantOS `.py` files** matched both their wheel members and `git show 93fef287…:src/...` bytes. The diagnostic source descriptor's 160 source hashes and producer-driver hash also matched the frozen worktree and retained driver.

For all twelve fixed workers, the source predicate checked the original prelaunch/completion pairing, fresh authority, fixed installed module hash, full service namespace argv including profile-selected mount policy v2, and the manager's original kernel observation. It compared the native executable hash, wrapper/init/service process chain, command, container child PID, net/pid/mnt inode identities and distinct manager/user namespaces, plus actual UID/GID and zero effective capabilities. Those records originate from the frozen manager's `/proc` reads of the launched child; an uploaded producer PASS or same-UID claim is not the proof. Departed processes were not resampled by PID.

The fixed service argv includes the v2 `/bin` alias and telemetry opt-out. Native interpreter flags and executable matched the installed probe's records. Each worker forked three distinct children under its observed namespace parent; the two recovery children called the production bootstrap independently against the same retained disk authority. All **36 parent waitpid exit records** had their exact source phase and tuple: six unsafe intermediate windows yielded literal `73/74/74`; six published windows yielded `73/0/0`. The verifier also rederived native seed/selection-plan/REGISTER bytes, temporary publication geometry, copied byte/directory sets, original physical facts, recovery status, native protocol/business events, budgets and Ledger closure. No trial or execution was manufactured by these registration-only windows.

Before and after independent recomputation, all twelve original complete case trees—including authority, channel, sidecars, snapshots, files and empty directories—had identical file bytes and physical facts: device/inode, mode, UID/GID, link count, size, mtime and ctime. Original authority forensic inventories and channel file/directory inventories also matched. Atime is intentionally excluded. The diagnostic bundle's file/directory inventories were unchanged. Execute, Qlib Workflow and socket-connect entry points were denied during rereading; observed calls were **zero**. The unrelated long-running `execution-prepared` case and shared growing management evidence were not operated on or included in an assertion that the whole manager root was immutable.

The three original `file_linked` authorities have the native two-name/same-inode/link-count-two intermediate. Each was independently **rejected by canonical `raw_inventory`**. Safe forensic copies contain independent single-link files; their byte views do not confer canonical status on the original temporary authority.

## Disposable negative controls

New copies were created only under `/tmp/hm-atomic-origin-attempt18-negative-copy01`. Nine checks rejected:

| Control | Observed rejection |
| --- | --- |
| All three phase exit files replaced by the valid crash tuple | Original-byte export gate rejects; direct atomic gate also rejects `Q05 atomic parent waitpid record differs` |
| Valid typed forensic sidecar with root inode incremented | Original-byte export gate rejects; atomic gate recomputes actual original authority and rejects the physical mismatch |
| Extra empty directory in a copied crashed authority | File-based manager export remains valid; atomic directory gate rejects |
| Missing empty directory in a copied crashed authority | File-based manager export remains valid; atomic directory gate rejects |
| Equal-byte crashed root redirected to the recovered phase | Exact original root-origin gate rejects |
| Forensic mapping redirected to the wrong original phase | Sidecar origin/uniqueness gate rejects |
| Same retained export bytes supplied under a different external manager root | Missing frozen authority/configuration rejects without creating or repairing directories |

For the byte-changing controls, the direct atomic checks intentionally reused the previously verified original-source context to exercise the inner gate after separately proving the export gate rejected the mutation. They are not claims that a modified export passed the full entry point. The root/mapping controls supplied altered in-memory indices/context solely as negative inputs; they do not replace the retained original index. The original twelve whole-case physical inventories and original bundle inventories stayed unchanged across all controls; execute/Workflow/network calls remained zero.

## Producer and retained attempts

Producer driver02 `/tmp/hm_stage_attempt18_atomic_diagnostic02.py` SHA-256 is `c1e28758806a05ea97a2f9e71ee8d7c9c1703dd69d0b4fc2afe5b0b297e83e76`; its log is `0ff5f1e2e9fa577898b4187c9071da5da9890063bbde8f1e0dd6c22c6c15a46d`. Its installed and management producer/verifier commit descriptors both name frozen 93fef287. The standalone producer script is separate from the installed wheel.

Driver01 SHA-256 `5ae4b79198f9627593202080bafa94280c501f0d7aa9dfd3425b0c89aa6868ed` and its import-failure log `6cdd9a081f2821f1523388045740635448e866874cef8dcd6fb32f0638140d64` remain intact. The exact driver diff is one import: `hosted_fault_verification` → `hosted_atomic_verification`. Failure occurred before output-root creation; `/tmp/hm-attempt18-atomic-diagnostic01` does not exist. This correction did not change installed source or rewrite a failed installed run.

Independent review invocation01 failed because it incorrectly applied the original-authority-only forensic reader to the entire case tree containing copied temporary names; invocation02 failed because its temporary driver had not been created after an unavailable bare `python` command. Both logs remain. Invocation03 used a separate physical-tree comparison for the whole case and the strict forensic reader for original authority, then completed successfully. These are review-driver failures, not silently converted evidence passes.

| Independent evidence | SHA-256 |
| --- | --- |
| `/tmp/hm_atomic_origin_attempt18_independent03.py` | `8fbe8d91421fd29a2ea1d275d5a9ec879e8b9bcfb58d1bcf3e9b8ca15b526112` |
| `/tmp/hm-atomic-origin-attempt18-independent03.log` | `36b2191be320c7503e65b7160d679e54925e2420daf7fe759a564dc80b139db0` |
| `/tmp/hm-atomic-origin-attempt18-independent03-summary.json` | `5b303a1a3abd60107b49f9122243616ce2c150c78e17f799e60c8df374f7713f` |
| `/tmp/hm_atomic_origin_attempt18_negatives01.py` | `95d7857da563a217723694fe9e099215348a171548f10f7bf88426730ec7ca68` |
| `/tmp/hm-atomic-origin-attempt18-negatives01.log` | `bb3a40063c0d1c9f0e189771835f899f17ff9570bbcabf9c69d857c73ed3329c` |
| Negative-copy summary | `52ffe34488422594cd8827e44ba10b34a88c03fa01db7a55122bf17f1831abac` |

## Reviewed frozen source hashes

Paths below are relative to `/tmp/hm-q05-atomic-installed-worktree/src/quantos/infrastructure/`.

| Source | SHA-256 |
| --- | --- |
| `hosted_atomic_verification.py` | `e0fab97342613a3cefc0d5e5d3cbe6bc4359ebf0dfeb24e41bcfa8331e4f23e2` |
| `hosted_atomic_probe.py` | `77b506943ccab8edc561ef324457976fdfb8d6d99ad57dbec037977dae62799f` |
| `hosted_atomic_snapshot.py` | `9457d1ab57c2b5763888d02fc71ea2b96cef43fc16a5a2a69183f13da3aa8aeb` |
| `hosted_atomic_forensics.py` | `eb7734e9d259a2bb01be519dcbe51fa5e5a6462269b2b77d0654073cba0e6396` |
| `hosted_manager.py` | `e8c052cc5cc3cff459569cad8eac2cba0816700522b72ac0529947a8b0ebe005` |
| `hosted_negative_origin.py` | `01d665a5997cdfda7c72e2e958131b38305255f14806486b3ba107ceb356b21d` |
| `hosted_qualification_sources.py` | `a994d871288204458ed0ad2b5ca1c12bdd00609bd6c6f4709c51f140b007642b` |
| `hosted_deployment.py` | `54adc50f1d57aeef5a7f9713f9d4780dbcdcfd214dcd997c0eff97f71dc9d95b` |
| `hosted_verification.py` | `2fc9aed35e6ad9083f399ed6d0b09cafdeac125cade5dcfa87943f0443af6e3b` |

This closes the bounded actual-original-source question for twelve atomic windows, including the earlier exit-source counterexample under frozen `e0fab973…`. It does not establish the remaining 44 durable and five corruption windows as one complete source-bound Q05 matrix, live/model evidence, full budget lifecycle coverage, Q11 success, or a complete failed-attempt ledger. The original manifest's diagnostic-only, incomplete-ledger and NOT_QUALIFIED limitations remain in force.
