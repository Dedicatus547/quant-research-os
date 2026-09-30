# Independent Q05 durable P1 successor review

**NOT_QUALIFIED. P1-2 and P1-3's original reproductions are closed at the reviewed implementation boundary. P1-1 is only partially closed: two independent, self-consistent native-copy negatives still passed the first successor.** No whole Q05/deployment/HM09 acceptance is granted. The parent's later in-progress response to these findings has not been independently closed by this report.

Assigned model `gpt-6.1-sol`; reasoning effort `high`; review attempt 1; observed usage unavailable. Repository base HEAD remains `81638bbd1abb53123a3da30010c2b8064dbd0657`. Original review `/tmp/hm-q05-durable-implementation-review.md` remains unchanged. No repository implementation, original actual15/diagnostic, frozen worktree or deployment evidence was changed. No authentication/model-provider invocation, credential read, commit or build was performed. Independent canaries create only disposable `/tmp` synthetic native component roots, using existing factory/orchestration and physical process recovery.

## Reviewed exact identities and changing successor boundary

At review start, tracked `git diff --binary` SHA-256 was `bd90becb1cf5fd1fd6b85bcba16006b4931d93ab88fdbbbbe813a546754c7872`; untracked file identities must be recorded separately. First targeted canary imported:

| File | Reviewed SHA-256 |
| --- | --- |
| `hosted_business_file_closure.py`, initial successor, execution-result `/v1` literal | `bb259b2a16217d5cad2a150ee944df2cf0dc55b397095403db7a644fd527a842` |
| `hosted_fault_verification.py` | `ebb0b83d81b257f80385ff0cc1174c4e97d329a02ec4445abbdc4fd75dd2800f` |
| `hosted_business_verification.py` | `39b54f80432cda4a6fd27d4d86c407115550c31fed06a95f2bd0ed5cea8d735a` |
| `application/hosted_campaign.py` | `877bd1b61ca2d4e400a266fb1897ede609bca24223ee929994e6eb06ba269406` |
| `application/hosted_protocol.py`, initial successor | `c04578355a5c0a79219f25d0f02c2b4d58ad708fbd7b77a65ab4db765edfbf43` |
| `hosted_admission_checkpoint.py` | `e52c25dfe3bb3a7d5ff0a7f3df7986ef89d7a76b0c61b69ff5c375493d015256` |
| `hosted_negative_origin.py` | `fe9f0e9cef3f940b9944638ff995396d212fe9c5ba5b12da7159006e221bb2cf` |

The parent corrected the `/v1` literal to the actual native `/v2` schema while review ran. The typed-Ledger canary imported closure SHA-256 `23827dde1fbd0a647adde6bd492d030be6c21f145833c63b8cca19656771dbb5` and the same fault verifier hash above; tracked diff was then `2693a90061bb59dfbad6c6fd49386ee5075edc63bbf03d1ea4a456525960b7fa`. The second canary uses schema-invalid admission and no execution-result schema, so its finding is independent of that literal correction. Further protocol/Ledger closure edits began after these findings; their apparent presence in the shared working directory is not a reviewed closure result.

## Original P1-2: canonical result now binds native authority

The core derives the fixed-clock protocol status from verified recovered state using `HostedProtocolService.project_status`; business status uses `HostedCampaignApplicationService.project_status`. The static projection does not recover or create state. The business projection reuses pure `verify_research_facts`, including accepted-receipt→exchange and reservation/request checks. Submission/rejection compares against exactly one matching native receipt bound to request, exact fixture bytes and principal; cancellation compares the native terminal; expiry compares the entire native protocol status. Equality checks all canonical fields, including nested budget/request/head/report references.

Independent first-register physical positive control passed. Changing both recovery results to the legitimate state RECOVERY_REQUIRED, recomputing their canonical hashes, leaves native authority unchanged and is now rejected: `Q05 recovered business status differs from native authority`. The same component remains a positive control after the mutations. This closes the reproduced result-agreement P1 at this implementation boundary; it does not establish all installed positive windows.

## Original P1-3: before completeness precedes creating constructor

The core verifies a nonempty before root with `verify_protocol_root` before any `HostedProtocolStore` constructor. Both expire and admission-resume branches therefore fail before a creating constructor can rebuild missing protocol structure. Empty REGISTER/start roots bypass store construction on before; original management freshness and exact empty-sidecar source binding remain prerequisites to the source wrapper.

Independent physical `expire-intent_published-1` positive control passed. Removing the disposable before `protocol/specs` directory and original spec file is now rejected as `hosted protocol authority is incomplete`; the directory stays absent. The verifier does not rebuild it. This closes the exact read-only/completeness reproduction. Missing/corrupt complete before roots still require rejection with unchanged file and directory topology.

## P1-1: actual unknown files are rejected, but semantic publication closure remains incomplete

The new helper derives frozen initial Ledger bytes, journal/object files, native campaign events/trials/proposals, verified execution identity/trial indices, ResearchResult/source artifacts, Validation/robustness files, selection, failure evidence and Ledger object nodes. It compares the full expected file map against actual raw inventory. Runtime bytes remain inventoried; only fixed `mlflow-runtime/` prefixes under already verified execution identities receive the runtime exclusion. `offline-observation.json` is rejected for this physical fixture. This is a substantial improvement over before→after preservation alone.

Independent first-register physical positive control passed. All of these mutations, with exact matching recovery inventory observations, were rejected read-only as `native authority has an unattributed raw file delta`:

- Original plain `unpublished-q05-review.json` addition.
- A misplaced native-shaped `execution-records/identities/<hash>.json` file.
- A file beneath an unverified execution identity's fixed-looking `qlib-workflow/mlflow-runtime/` prefix.

These component negatives have no verified execution identity; they prove that a pathname alone cannot acquire exclusion. Acceptance of genuine verified recorder bytes is covered by the implementation's strict derived identity list, and still needs the succeeding full native execution positive matrix.

### Remaining P1-1a: legal orphan REGISTER pair is accepted

The initial successor checks non-BUSINESS publication schema shape, but does not derive all native protocol operations/chronology. An allowed shape alone authorizes extra journal files.

Independent reproduction uses disposable copies of the passing first-register physical component. Append a complete REGISTER INTENT/COMPLETE pair to recovered and after using the original three canonical spec/budget/receipt artifacts and a different unique operation ID. `HostedProtocolStore.commit_locked` publishes the pair; generic `verify_protocol_root` passes. Recompute the actual pure native status (including changed journal head) and exact recovery inventories. The full scenario core **passes read-only**, followed by a successful restored original positive control. No unknown raw file or unmatched result was used; the added journal operation itself has no native role in the fixed transition.

Minimum correction: enforce unique initial REGISTER and native protocol operation IDs, recorded time and exact canonical publication tuples for ISSUE/SUBMIT/TERMINATE, with valid chronological prior budgets/request/receipt/terminal inputs. Tie the fixed scenario's journal delta to the intended recovery, rather than merely blessing every operation appearing in final source. Keep authentic repeated submission deduplication and seen-byte/no-refund semantics. Add legal orphan pairs and repeated existing canonical artifacts, not only invalid-schema unknown publications. A source-bound producer observation cannot authorize a logically unrelated extra native operation.

### Remaining P1-1b: canonical trial object can receive the wrong legal Ledger type

The closure attributes added Ledger events by object hash and checks object reference/domain/campaign/media/access/path/duplicates. The underlying Ledger verifies canonical bytes, deterministic UUID, predecessor/parent existence and enum/provenance compatibility. Neither check, at the reviewed successor, binds each added node's full metadata to the exact native object/event that caused it.

Independent reproduction uses the real physical `business-prepared` schema-invalid admission component, with two fresh application recoveries and no execution. The unmodified full core passed. In disposable recovered and after roots:

1. Change the sole added native trial Ledger event from CAMPAIGN_TRIAL to the legitimate EXPERIMENT kind, keeping the canonical trial object itself unchanged.
2. Recompute event UUID via the existing `ResearchLedgerService._event_identity` and the canonical Ledger predecessor chain. Both kinds are legal under DETERMINISTIC_EVIDENCE, so this is not an invalid-schema test.
3. Verify the changed native Ledger; replace the exact STEP_COMPLETED terminal snapshot reference with its new snapshot hash. Recompute affected protocol object/journal hashes and exact returned native status/inventories.
4. Generic protocol and native Ledger verification both pass. The **full Q05 scenario core also passes read-only**. The unmodified final positive control passes again.

This changes a typed native fact's role without adding an unknown object, breaking a hash or relying on a handwritten producer PASS. The next request object was retained unchanged; no model/provider call or authority repair occurred.

Minimum correction: derive each expected added Ledger event tuple from the exact native trial/proposal/ResearchResult/Validation/selection/failure publication. Check node_kind, assertion authority, deterministic node_id, occurred_at, parents, agent/human/verdict provenance and the exact object reference. Verify/reuse the existing native identity construction rather than writing a Ledger engine. In particular, trial must be CAMPAIGN_TRIAL with the expected native campaign event/node/time; ValidationReport must remain DETERMINISTIC_VERDICT with its report/parents; proposal must remain AGENT_PROPOSAL with its exact agent/context references. Add self-consistent legal alternate kinds and wrong node/time/parent negatives. Do not widen metadata just to make a positive fixture pass.

## Independent scripts, logs and positive-run limits

| Artifact | SHA-256 |
| --- | --- |
| `/tmp/hm_q05_successor_independent_canary.py` | `4c660c210e9fad7a7dca38c9df0938b33cc20fdb2b58ab5bb700465da964869c` |
| `/tmp/hm-q05-successor-independent-canary01.log` | `9116ccb76010e3e49e4761f66c6d113a006e692e4e855732a565dcc88d814ab5` |
| `/tmp/hm_q05_successor_readonly_canary.py` | `b069cfae9aa3fb7e1638b98da5cedede908494c1acc752bc8fc038af6193229e` |
| `/tmp/hm-q05-successor-readonly-canary01.log` | `6d60b42ed556213bde4cce180264cb66697bcb553c6f47e61a15aad9bb304fcf` |
| `/tmp/hm_q05_typed_ledger_successor_canary.py`, corrected import | `83351ec3baeac62728ecba818f5e98488e8b80a719d9746da06073861ac4de43` |
| `/tmp/hm-q05-typed-ledger-successor-canary01.log`, preserved reviewer setup failure | `51021cab1f5c08b78f734cf4d54d39242f2c43eeb37610e62918656ed2042a11` |
| `/tmp/hm-q05-typed-ledger-successor-canary02.log`, completed native reproduction | `d9609ab1903de3ec28cd3fa2938aa369e5d09b68db1f54b057a341b12b6359e6` |
| `/tmp/hm-q05-native-closure-regression07.txt`, parent full positive failure | `77338f63f39ed4dfccaca658f4b3f0187029d192c4be86ac79f1343a94685288` |

The typed-Ledger first script imported an incorrectly named publication class and exited before executing the test; the failure is retained and is not counted as a verifier rejection. The corrected script imports the existing HostedPublication type and completes the reproduction.

The parent full44 regression07 failed in148.23 sec at execution-prepared because COMPLETED's allowed schema incorrectly used autonomous-execution-result/v1 instead of the native /v2. The log and roots are retained. The narrow literal correction is appropriate, but this review has no later full positive PASS proving the corrected execution paths. Passing our targeted nonexecution positive controls does not mask that matrix failure. The next positive run and any subsequent protocol/Ledger repairs must be assessed against the bytes they actually loaded.

Overall: the result and read-only fixes reject their original independent counterexamples. File membership now rejects arbitrary unknown paths, but native journal and typed Ledger attribution still accepted the two self-consistent wrong transitions described above. Q05's source-bound fsync/corruption matrix and full qualification wiring also remain incomplete. No successor is retroactively applied to frozen816 actual15; no full Q05, deployment or HM09 qualification follows from this review.
