# Manager private FD ownership — independent closure review

Date: 2026-10-01. Reviewer: independent `gpt-6.1-sol`, high reasoning. Baseline `236955448d4e7683836d8b527625a371dcfed6e5`, with the final uncommitted manager correction.

**CLOSED for the two reported private-FD/returned-process ownership defects on the exact bytes below. NOT_QUALIFIED.** Seven independent real-FD failure controls, two actual local child-process controls, and the current two unit files pass. No new blocker was observed within this scope. This review grants no HM09, Q12, D24, D25 or MVP acceptance.

## Exact source and historical findings

| Reviewed file | SHA256 |
| --- | --- |
| `src/quantos/infrastructure/hosted_manager.py` | `f3fe45e45127454561ee76d2e04a6df95278e5ad62d24c989e7c0510b7e381b9` |
| `tests/unit/test_hosted_manager_start_capture.py` | `6a191f1b7b24c91fff9b341d9d331243dda09c7f750e54c49092297c1067bb5c` |
| `tests/unit/test_hosted_capability_hydration.py` | `02139db88a8597a495ad2a7156cc080126d270e0cf848f30460528b583b1d9cb` |
| `tests/unit/test_hosted_manager_client_capture.py`, supporting fixture read | `eccadbd07057dbb2f5d408f493a2a141d98a710fe09696dd3502a0a135bf5699` |

The three primary source/test hashes match before and after all new controls. Both standalone diagnostics also bind the manager hash before/after. A read-only copy of the reviewed manager file is retained. These are local source-byte observations, not installed-module or deployment provenance attestations.

Both historical reports and their failed diagnostics remain unchanged:

| Historical report | Preserved SHA256 | Closure on final manager bytes |
| --- | --- | --- |
| `hm-manager-private-fd-cleanup-open-review.md`, original `0ff8c99f…` | `15d8ef2341b9a8a3c6dd9a9dccf4b893c34f3e98c36142c55d8cae6c76c8a683` | Listener-close errors no longer skip closing the information memfd. |
| `hm-manager-private-fd-lifecycle-open-review.md`, intermediate `8a66a929…` | `bb8f92806f7630a7363d840f999089708c0ddb29ec4fb903291b2cadf4da0fa5` | A cleanup error after successful readiness now enters the launched-process terminate/wait handler rather than cancelling its return while leaving an unreturned live child. |

Those reports remain OPEN descriptions of their original bytes; this separate review closes their specific findings for the final source only.

## Independent observations

New root: `/tmp/hm-manager-private-fd-independent-review03`. No implementation/test change, old failed-root repair, native authority-root borrowing, authentication/provider/model call, or full CI occurred.

The existing `_memory` correction checks the whole write length, rejects an actual short write, seeks to zero only after a complete write, and closes the descriptor on write/short-write/seek exceptions. Startup allocates the information fd and listener inside its cleanup boundary. Each listener cleanup uses a nested `finally`, making information-fd close independent of listener-close success. The final post-readiness cleanup is inside the existing process-reaping exception boundary. The fixed service argv, minimal child environment, private pass-fds, normal successful return and existing terminate/wait/kill policy remain unchanged in the reviewed diff.

The seven independent controls use actual private memfds with explicit socket/process/readiness/configuration doubles. All recorded FD sets are closed, checked with real `os.fstat`:

| Control | Observed result |
| --- | --- |
| Second information-fd allocation fails | Previously allocated capability fd closed. |
| Actual partial capability write | Incomplete write rejected; capability fd closed. |
| getsockname fails | Both allocated memfds closed. |
| accept fails | Both allocated memfds closed. |
| bind fails and listener.close raises | Both allocated memfds closed despite close error. |
| Readiness fails and listener.close raises | Both memfds closed; process double receives terminate and wait. |
| Readiness returns and listener.close raises | Both memfds closed; process double receives terminate and wait. |

A separate paired control substitutes two **actual non-model Python sleep subprocesses** for the service command. The original Popen implementation, `start_new_session=True`, original private `pass_fds`, DEVNULL streams and the fixed minimal environment are retained. Socket operations, readiness, configuration and the tiny deployment inventories remain declared doubles; no actual hosted service, Codex/model process or namespace readiness is claimed.

| Actual child observation while original parent lives | Normal listener close | Listener close raises after readiness |
| --- | --- | --- |
| Caller receives actual Popen | yes | no; OSError propagates |
| Popen.returncode before diagnostic poll/wait | `None` | `-15` |
| Actual child running immediately afterward | yes, with returned caller ownership | no |
| Parent capability/information memfds | both closed | both closed |

The error-path returncode is inspected **before** the independent diagnostic calls poll or wait after `start_managed_service` raises. The already populated `-15` proves that the implementation terminated and waited for this actual child; the diagnostic did not supply the missing reap. The positive case preserves caller ownership. The diagnostic finalizer stops/waits for its positive child and confirms the other has already exited, leaving neither child running.

The independent bounded unit run completes **30 passed in 5.22 seconds**, exit 0, with `--no-cov`. Its controls also cover socket creation/bind/listen/connect failure, preparation/spawn failure, occupied-channel retention, early exit, observation/timeout failure, kill fallback, memory write/seek errors, successful FD hydration, and the new real child pair. The close-success observation component retains its previously sealed truthful `NOT_QUALIFIED` record even though later listener cleanup fails and reaps the child; it does not claim a returned live service. These unit/socket/namespace doubles are not kernel-isolation qualification evidence.

## Preserved evidence

All following paths are relative to the new independent root. `commands.json` records exact bounded commands and their three exit codes; `evidence-sha256.json` binds the complete eleven-file list, verified against preserved bytes before sealing.

| Evidence | SHA256 |
| --- | --- |
| `source-before.json` | `b1bb09fdc930802c5d4e2bfdd8eab6991d26edc0be0af2c8b58fe1bf9ed03ccd` |
| `source-after.json` | `b1bb09fdc930802c5d4e2bfdd8eab6991d26edc0be0af2c8b58fe1bf9ed03ccd` |
| `reviewed-hosted_manager.py` | `f3fe45e45127454561ee76d2e04a6df95278e5ad62d24c989e7c0510b7e381b9` |
| `independent.py` | `e4f37045ee73d6c408bc197ff6eead0e1da980025cf3a9e403b06a1623b5595c` |
| `independent.txt` | `a527f5fa6123b5a9354391124a2218450e33462714303ad4160796195165ecc7` |
| `independent-result.json` | `4d1aa290234e60841af49559276b478ea6b3eb041fcc615bd7077b47b5252c58` |
| `native_lifecycle.py` | `31596027aba3db0b253dcb8a666658769945992526e8bbb9cd09bd232f231843` |
| `native-lifecycle.txt` | `dd71a6fd8749def595eb8673ea7fd565bc83e73c9c88339a4789f2bf1d1f5fb7` |
| `native-lifecycle-result.json` | `519024ce0cbdd45562c9e09df34c2c48860baf1ba0353297dba7123767cfd48c` |
| `unit.txt` | `0a3b176a46d434689d14522dc54d7336b00106d1c02f45e88f5bcb19091fedab` |
| `commands.json` | `a862835ee07fb94ec0c81eef8d56fe11894dcff49ed6c4ca6fab8702d457ee8f` |
| `evidence-sha256.json` | `8eb060414447f229acc77218ae94ad41d98b6fb6a14bf4e1718c79bd04cc72d4` |

The unchanged whole-source ≥85% coverage requirement and full matrix still require a newly frozen commit/wheel/D25. Neither the in-progress original D24 CI nor this component run can qualify the successor source. General deployed namespace/descendant cleanup and live readiness are outside these local ownership controls. All prior failed diagnostics and both original OPEN reports were preserved.
