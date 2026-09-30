# Attempt17 corruption original-source independent review

Assigned model: gpt-6.1-sol; effort: high; independent review attempt: 1; observed usage: unavailable. The five recorded corruption windows were independently reverified as a **corruption subset only**. Overall status remains **NOT_QUALIFIED**, with all twelve formal gates NOT_EVALUATED. No full Q05, HM09 or deployment acceptance is granted.

## Distinct installed and verifier identities

| Identity | Value |
| --- | --- |
| original manager root | `/tmp/hm-stage-77c129f-attempt17` |
| original installed commit | `77c129f11e9fc65f76a64fa978cc6d06e9164554` |
| original deployment profile D | `077b62211806f06319cd2ec0a9dd42d6155620bd30371779efe0aae931a9ec9d` |
| frozen business bundle B | `8037d0010807ee7958aeed52de3154c3a1bcd5d763a6bcca42dc65e797d29dc7` |
| clean successor verifier commit | `cf9b2d4d776da1b9a67180b88b844d4cbcd0dc35` |
| successor worktree | `/tmp/hm-q05-successor-diagnostic-worktree` |
| diagnostic export | `/tmp/hm-attempt17-corruption-diagnostic03` |
| qualification manifest hash | `141995a97a6f7f25f2a53773b1f0a56198211e89b6e04475a47283211d583d51` |
| original manager export hash | `4b7320b9c7f27035e4fc01865ca83a00fbf41e4bdaad2f06fb552a3c7519ba87` |
| external subset-result hash | `50c7f4a1c761b2fb8e592b81bc712f3a68312c73b65612e251827107ca2564d2` |

The reviewer checked clean successor HEAD/status and all 156 source hashes against the exported successor code-identity record. All loaded QuantOS module origins in the mechanical run were under that worktree's source tree; bytecode reading/writing was redirected to a nonexistent private prefix. Independently, all 155 installed QuantOS Python source files matched `git show` of the original installed77 commit exactly. The installed worker hash is `1090d3f7e0e5e308d3b64fbbc69470d91312fddb1cfaa4d8a58f798a8e22d427`; the native executable hash bound by every original invocation is `e22006d8367f4ddd15cf90877f2de5a67b369ccce47f872d7bee778e438f94e5`.

The successor frozen-plan attribution is a verifier correction described in [the preceding narrow review](hm-q05-frozen-selection-plan-attribution-review.md). It was not installed into or retrospectively attributed to installed77. Diagnostic01/02 remain failed preserved exports; their original authorities and failure records were not rewritten.

## Mechanical original-source recomputation

The independent process read the existing case index at `diagnostic/q05-corruption-case-index.json`, called `verify_manager_export` with the separately supplied original manager root, then called the clean successor's `verify_q05_corruption_subset`. No diagnostic producer or fixture worker was rerun.

All 483 exported file mappings were tied to the retained original manager export, with exact bytes/hash/length under both original and exported paths. The installation and original provenance inventories matched the frozen profile. The five corruption windows produced the same ordered 55 checked artifact hashes as the retained external subset result.

The source predicate rechecked durable prelaunch/completion binding, initially fresh private authority, fixed finite case and namespace argv, worker-program and native-executable hashes, actual saved wrapper/init/service kernel process chain, bwrap child-pid and namespace inode correspondence, distinct service/manager namespaces, zero effective capabilities and exact frozen principal credentials. These conclusions use original fixed-program/kernel records, not an uploaded trust label, producer PASS or UID equality alone. This was revalidation of saved kernel observations, not a new `/proc` observation of processes that have exited.

| Window | Original wrapper/init/service PIDs | Three guest child PIDs | Literal exits |
| --- | --- | --- | --- |
| journal fragment | 1428889 / 1428890 / 1428891 | 50 / 84 / 112 | 73 / 74 / 74 |
| wrong sequence | 1429272 / 1429273 / 1429274 | 50 / 84 / 112 | 73 / 74 / 74 |
| double pending | 1429928 / 1429929 / 1429930 | 50 / 84 / 112 | 73 / 74 / 74 |
| orphan artifact | 1430208 / 1430209 / 1430210 | 50 / 84 / 112 | 73 / 74 / 74 |
| changed artifact | 1430450 / 1430451 / 1430452 | 50 / 84 / 112 | 73 / 74 / 74 |

Guest PID reuse across these cases is within separate freshly recorded PID namespaces. Within each case the three children are distinct and bound to the saved native parent PID and original parent waitpid records. The crash record corresponds to the fixed damage point; both subsequent fresh bootstraps reject with the exact expected parser error and exit74.

For each case, the before/crashed/recovered/after roots and sidecars mapped to the exact original fixed phase paths. Exported and original directory inventories matched, including empty directories. The core rederived the damage from the verified native starting protocol/business facts, rather than accepting arbitrary differences. Every later raw inventory equalled that exact damage plan; both recovery records retained the same files/directories and zero execution/Workflow/network attempts. The production read-only parser independently rejected each damaged authority without recovery writes. Native seed file attribution included only the exact frozen selection plan, not arbitrary plan files.

`verify_staging` was also mechanically recomputed and its canonical bytes matched the saved formal result (`06655d8ce193c5912b82b601ce0f9f6e63ad332f7761c8988a1a9d2ca0bce404`). All twelve gates remain NOT_EVALUATED; the formal Q05 record is empty, while the separate diagnostic index contains this five-window subset. The reviewer denied execute, Workflow and network operations: zero calls occurred. Full file and directory inventories of every original phase/channel and the diagnostic bundle stayed unchanged; the successor worktree stayed clean.

## Disposable negative controls

An extra empty directory in a copied recovered phase passed the unchanged file-only manager mapping gate, then was rejected by the Q05 original-directory comparison. Changing a copied recovery exit record from literal74 to zero was rejected by the original manager byte mapping. Both rejections left their tested copies unchanged during verification; the original bundle was unchanged. These controls confirm directory and original-byte binding independently of the producer's diagnostic verdict.

## Reproduction artifacts and limits

Independent positive script `/tmp/hm_attempt17_corruption_independent_reverify.py` SHA-256 `05d77eaec2aef6b0a413206a0a364771a647267e0c36c5897ae47172c3961954`; successful log `/tmp/hm-attempt17-corruption-independent-reverify01.log` SHA-256 `451110eb2ebb8f7f1abe6d906a1e453de6424c1be41cc0b028a0c566246400cf`.

Negative script `/tmp/hm_attempt17_corruption_independent_negatives.py` SHA-256 `eabe3043f134c2af4e6fe29e50715da8be8d25d0c83610b40cd7f0763d905d79`; log `/tmp/hm-attempt17-corruption-independent-negatives01.log` SHA-256 `ea3b451d9f9e46aa34edbe7eb002301eaf3e3df9733432655e76e9173552751b`. Installed-source comparison script and log are retained at `/tmp/hm_attempt17_installed_sources_check.py` and `/tmp/hm-attempt17-installed-sources-independent01.log`.

The diagnostic driver itself has SHA-256 `7f7d60ac3a6c05e61d35b6ae71014251d9fabdf7faf629484d90115d6b067e65`; successor code-identity bytes have SHA-256 `495bf7fb407b00bb0a4a0ce4cead5249aac7da48d94db9ebafb441a5cc153613`. The reviewer did not execute that producer or append manager evidence. No original implementation, frozen worktree, historical attempt, authentication or provider/model was touched. The only repository write was this requested report. This narrow original-source diagnosis does not supply the other durable/fsync windows or live/full-matrix qualification evidence.
