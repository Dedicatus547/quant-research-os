# Independent Q04 publication-closure follow-up

**Narrow implementation finding: the remaining extra-publication P1 is closed by the reviewed successor diff. Overall status remains NOT_QUALIFIED.** This does not qualify the frozen abe install, attempt13, Q04/Q08 original matrix, or HM09.

Assigned reviewer model `gpt-6.1-sol`; reasoning effort `high`; follow-up review attempt 1; observed usage unavailable. No repository implementation/documentation, original deployment root, credential, vendor call, model invocation, commit or push was performed by the reviewer. Tests and canaries wrote only disposable copies/fixtures and reports under `/tmp`.

## Exact reviewed bytes

Base HEAD `/tmp/hm-negative-followup-worktree`: `abe5a9db5e542eb09caba9fc868c35fa56207e2a`. The uncommitted diff has exactly three tracked files, 162 insertions and 6 deletions; `git diff --check` passes. SHA-256 of `git diff --binary` at beginning and completion: `4182ce9ffb22174c11a684bf9b05b862085c9cf27730ac475b9a308b1fdeaab3`.

| File | SHA-256 of reviewed working-tree bytes |
| --- | --- |
| `src/quantos/application/hosted_campaign.py` | `32c8d9d779db9d1bec7d075d33fafbfa152bfd435eac27c8e686ffc5d3a5a36e` |
| `src/quantos/infrastructure/hosted_admission_checkpoint.py` | `138780a8b9314ec3fb46a92db63df16adab79f4efe1e004aa780521bccba5cb4` |
| `tests/integration/test_hosted_business_e2e.py` | `a060a7e71ce2f2738bebe040986fe8c28565686ff419e5837ec6cabbb95e42c7` |

The frozen contract/acceptance/deployment record are outside the diff. This successor does not change abe's installed source inventory or rewrite previous review findings.

## Why the remaining P1 is closed

The previous verifier authorized every new file merely because it appeared in a valid journal publication. The native checkpoint selected its one trial/budget/step and ignored an additional published trial with no corresponding event/Ledger node. This produced a genuine false acceptance in the prior independent native canary.

The successor requires the complete ordered INTENT shape for this fixed negative fixture: REGISTER, native INITIAL, first ISSUE, one SUBMIT, native PREPARED, native COMPLETED, native STEP_COMPLETED, and, when present, the second ISSUE followed by its TERMINATE cancellation. Each operation has an exact ordered schema tuple. This excludes additional pairs, repeated existing publications, foreign operation kinds, extra objects within a permitted operation, and attempts to place a trial inside a transport operation.

All **four** BUSINESS intents additionally compare exact native operation ID, logical recorded time, and the full ordered `(artifact_hash, canonical_bytes)` publication tuple:

- INITIAL: native `RESEARCH_INITIAL(spec_hash)` at spec start with the verified initial research budget.
- PREPARED: native `PREPARED(request_hash)` at native event time with exactly the verified reservation and prepared step.
- COMPLETED: native `COMPLETED(request_hash)` at native event time with exactly the native trial, settled budget and completed step.
- STEP_COMPLETED: native `STEP_COMPLETED(request_hash)` at native event time with exactly the verified terminal receipt.

The embedded INITIAL/RESERVE/SETTLE budget operation IDs are bound independently to the existing native hash function. The prepared step must have no previous intent. Existing complete budget, step, exchange, terminal, governor/event and Ledger checks remain in place. The public operation-ID helper is a rename of the same pure canonical hash function; its generated identities and production callers retain their existing semantics. No host RPC surface or mutable testing hook was added.

Only INTENT entries carry publications: `HostedJournalEntry` forbids publications on COMPLETE, and existing journal verification binds every COMPLETE's ID/kind/time/artifact tuple and hash-chain predecessor to its INTENT. Therefore inspecting the exact INTENT sequence does not leave an alternate COMPLETE publication path. The protocol-root verifier also requires every object to match its publication and exact raw file set. Transport operation bindings remain under the existing protocol/receipt/source predicates; the successor's exact schema shape prevents those operations from admitting unrelated business artifact types.

No additional concrete P1 or missing BUSINESS phase was established in this narrow follow-up. The change is intentionally limited to this fixed one-invalid-trial checkpoint and is not a replacement for complete campaign verification or the production full-denominator DQ finalization rule.

## Independently executed checks

1. Re-ran the original extra-journal-trial native canary under the successor diff. The unmodified native checkpoint passed. A plain unpublished file still failed with `business admission has an unattributed raw file delta`. The valid additional BUSINESS pair publishing an unreferenced trial now failed with `admission checkpoint publication chronology differs`. The verification left complete before/after raw inventories unchanged. The canary invokes the existing integration fixture's actual Qlib research/native orchestration with explicitly synthetic frozen component inputs; it stops after the first invalid-case canary and is not a complete installed/live qualification run.
2. Rechecked actual a6 attempt12's original known-invalid partial checkpoint with the successor component helper: **26 hashes verified**, complete original before/after inventories unchanged. This is **POSTDATES_INSTALLED_COMMIT / NOT_QUALIFIED**. It neither creates a worker completion nor changes the preserved a6 failed attempt.
3. Created disposable copies of that after-root and changed an existing PREPARED BUSINESS operation's ID, then its recorded time, separately. For each mutation, rebuilt both INTENT/COMPLETE canonical records and the full subsequent journal hash chain. Generic protocol integrity still passed, and both copies were rejected specifically with `admission checkpoint contains an unrelated business publication`. Thus the new native identity/time check was reached; rejection was not merely due to a broken journal hash. Verification remained read-only, and original inventories were unchanged.

| Evidence | SHA-256 |
| --- | --- |
| `/tmp/hm-admission-journal-canary-followup.log` | `9837d87ecf7498a14604eddcf7c3b2cd40c3dae9d316a325cd6ed505143f9195` |
| `/tmp/hm_admission_existing_operation_canary_followup.py` | `6ca0ffbe37deef3f6da8e810081b1cbfe78775c685401963ce4564116ae37e93` |
| `/tmp/hm-admission-existing-operation-canary-followup.log` | `3589cd17d0a18bae3c97c042a30aa9c862e860e7ed8d53edaac0f1c40c2c1be6` |

The parent-supplied complete native regression log `/tmp/hm-admission-journal-closure-native02.txt` reports **1 passed / 145.24 sec**, including extra trial, a new pair re-publishing the original trial, a new pair re-publishing settled budget, and a TERMINATE pair carrying a trial; its tests require read-only rejection. `/tmp/hm-admission-journal-closure-pyright02.txt` reports 0 errors. These complete-run/static results were inspected, not relabeled as independently rerun.

## Qualification boundary

The prior a6 stale-bytecode P1 and plain unknown-file hole were already closed in abe implementation. This successor diff closes the remaining journal-wrapped extra-trial hole in implementation. The previous abe review remains accurate for its exact commit; this follow-up postdates that install. Actual attempt13 continues to use abe's installed predicate bytes and cannot inherit this fix's acceptance status. A clean successor commit, newly bound installation/profile, actual source-bound completed matrix and formal verification remain necessary where required. No full Q04/Q08 PASS, HM09 readiness or hosted qualification is granted here.
