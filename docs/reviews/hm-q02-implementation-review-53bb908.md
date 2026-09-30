# Independent Q02 implementation review — 53bb908

**NOT_QUALIFIED. One open P1 prevents the real fresh-bootstrap resume path from completing.** The new accounting/source predicate has substantive checks, but the functional fork tests do not exercise the production capability-descriptor lifecycle.

Assigned model: `gpt-6.1-sol`; reasoning effort: `high`; review attempt: 1; observed usage unavailable. Reviewed clean `/tmp/hm-negative-followup-worktree`, exact HEAD `53bb908ed45388dee05e0df6952997246f9b9aca`. The root workspace/abe install and original deployment evidence were not changed. No authentication/model credential read, provider/model invocation, implementation edit, commit or push was performed. Reports/scripts and disposable test fixtures are under `/tmp` only.

## Scope and independently observed tests

Read the two new duplicate probe/verifier modules and finite management dispatch, shared fixture recipes, full original-source/kernel namespace predicate, strict native admission closure, cap transition helper and associated tests. Frozen Q02 requires real cross-process barrier/flock, exact receipt reuse, a single accepted exchange/intent/event/trial, unchanged Qlib call count, rejected-byte idempotence, and retained seen receipt after cap/TTL. Accepted here deliberately resolves to SCHEMA_INVALID with execution=false; it is not successful execution, live model evidence or Q11 success.

Independently ran `tests/unit/test_hosted_duplicate_probe.py`: **2 passed / 17.96 sec**. The tests run real `fork`, barrier and `waitpid`, both accepted/rejected paths and cap/TTL reuse, but replace `bootstrap_hosted_service`, hydration and frozen configuration loading with component fixtures. That substitution is exactly why these passing tests do not establish the capability lifecycle below. Log `/tmp/hm-q02-independent-functional-53bb908.log`, SHA-256 `48ef4c79fd0f5a413318982f7a9033cf4bff1e8ffb38d2584a8c585a84773115`.

## Open P1: capability FD consumed before fresh child boot

The parent agent first identified this lifecycle issue during the review. Independent code inspection confirms it:

1. `hosted_duplicate_probe.py:132–133` hydrates fixed service capability slots, then performs the initial real boot.
2. `hosted_service.py:541–578` moves the one-use namespace tmpfs staging values into fixed private descriptors (100+index), resets position, and unlinks the staging files.
3. Initial `bootstrap_hosted_service` calls `consume_capability_fd` for every configured principal (`hosted_service.py:490–492`). `hosted_client.py:36–49` reads the descriptor and unconditionally closes it.
4. After concurrent submissions and one repeat, `spawn(..., action="resume")` forks from that parent and calls `boot()` again (`hosted_duplicate_probe.py:161`). It inherits the already-closed slots, and no descriptor reconstruction occurs. Re-hydration from the old staging files would also be invalid because they were unlinked.

Thus the actual fresh resume bootstrap cannot consume the frozen grant as written. An accidental reuse of the numeric slot would not restore authorization and must not be accepted. This is not a merely hypothetical missing test: the code's one-use descriptor consumption and child inheritance conflict directly.

Independent nonsecret lifecycle canary used the actual `private_memory_fd`/`consume_capability_fd`, fixed slot100, a synthetic 32-byte value held only in memory, real `fork` and `waitpid`: initial consumption passed, the slot was closed, and child reconsumption rejected. It did not read a real capability or model credential. Script `/tmp/hm_q02_capability_lifecycle_canary_53bb908.py`, SHA-256 `58d63fdfadfb4a9f609810e96088756a4c9b883e68aeb6eea043be7fbfe7fbbd`; log `/tmp/hm-q02-capability-lifecycle-canary-53bb908.log`, SHA-256 `b3b4b2e2b854d8cd39b05f12e3006da218fc25967062af36a9b656fa8a2467c2`.

Minimum successor correction: after the single legitimate hydrate, capture each exact 32-byte grant from its frozen configured slot into the management process RAM before initial consumption, without moving the descriptor's read offset. Before each new fixed child/bootstrap, create a private memory FD, write the same grant, set offset0 and restore only its frozen slot with close-on-exec. Keep values out of argv/environment/disk/logs, keep the grant scanner active, and accept no host-supplied substitute or old staging-file fallback. Existing retained failures and the 53bb install must stay unchanged. A successor test must exercise the real capability consumption path across the two fresh boots; the functional monkeypatch cannot prove closure. Actual installed successor execution remains necessary for source-bound acceptance.

## Probe and predicate findings outside the open P1

The executable accepts only frozen profile hash and finite accepted/rejected cases; authority/channel root overrides are Python management-test parameters, not CLI/RPC options. Management allocates retained fresh case roots, uses the installed module/native inventory hashes, fixed namespace argv and durable prelaunch/completion records. No live service authority or model-auth descriptor is passed into these fixed fixture roots. Production host-channel operations do not control the fixture, clock or monkeypatch guards.

The first two submission children take authority inventories and lock-directory `(device,inode)` before signaling readiness. The parent waits for both readiness bytes and releases both together. They use the existing protocol service and its cross-process flock; they do not replace it with a thread lock. Six child phases use distinct PIDs with actual waitpid exit accounting. Both resume children invoke a new application factory in separate processes. Each child's record checks its before/after lock inode, request/frame hash, outcome and raw inventory. The original fixed parent program is externally bound to actual `/proc` executable/argv/credentials/namespaces and NSpid, so the child's parent PID and fixed-program observations are checked in that context; a producer PASS or same UID alone is insufficient. The capability defect currently prevents completion of that intended proof.

The existing full manager-source gate binds original file bytes, raw roots, deployment/profile, program inventory, prelaunch, completion, exact mount argv, actual kernel process chain, bwrap container namespace information, user/net/pid/mount namespace separation, principal credentials and zero capabilities. The Q02 helper requires the complete two-case/six-phase-root registry and six process records per case with the exact original source paths. All exported phase inventories are verified against original roots and protocol structure before constructing stores; stores use `recover=False`. It does not repair missing authority directories.

The phase accounting checks cover the complete file delta:

- before→after-submit: exactly one SUBMIT operation/unique charge, exact response/receipt/exchange bindings for accepted bytes, or schema-invalid rejection with no accepted exchange. The second simultaneous call and immediate repeat must return the identical original receipt and final raw state.
- accepted after-submit→native checkpoint: the existing native admission verifier binds one SCHEMA_INVALID trial, one prepared/completed step, budget reservation/settlement, event and Ledger object, strict BUSINESS IDs/times/publication tuples and zero execution. The second fresh resume must return the same status and preserve the full first-resume raw inventory.
- first-resume→after-business: accepted case may add only the next-request authorized cancellation receipt and its exact TERMINATE pair; native prefix and budget stay unchanged. Rejected case must preserve all raw business/authority bytes through both resumes and create no trial.
- after-business→before-cap: exact raw equality. before-cap→final: one unique conflict/rejection operation closes the cap2 accounting. Unseen exhausted bytes add no files; a late child repeats the original seen bytes after expiry and still returns the same original receipt with identical cap inventory.

Execution, Qlib Workflow and socket calls are denied and counted in each child as well as the parent. Child list checks matter because mutations of forked lists do not propagate back to the parent. A nonzero child count/failure, missing record, altered phase inventory, extra file or invalid operation closure prevents acceptance. The native artifact checks substantiate the zero-execution claim; empty producer counters alone do not prove it.

No separate concrete accounting/publication or host-RPC boundary P1 was established in this narrow code review. Direct Q02 predicate positive/negative cases were not independently run with source-bound completed installed evidence in this review; the two current tests are functional producer tests. Actual originals should exercise the complete predicate and retain tampered disposable-copy rejection checks for missing phase/child, changed receipt/clock/inode/parent, extra phase file and native budget/step bindings.

## Original evidence and qualification boundary

Attempt14 was still pending when this code review was prepared; no unfinished deployment directory was inspected as acceptance evidence. Its completion/failure, full source export, diagnostic manifest and formal result require a separate original-evidence verification. The reproduced descriptor lifecycle means no Q02 PASS is granted for this exact implementation merely because two functional tests passed.

The supplied attempt13 diagnostic was not independently reverified in this Q02-only turn. Its reported Q03/Q04/Q08 PASS retains the explicit abe stale-publication limitation, incomplete failure ledger and overall NOT_QUALIFIED; no successor repair is applied retroactively. The parent's 167 affected regression results, pyright/ruff/format checks and installation work are not relabeled as independently rerun here.

Reviewed primary file SHA-256: duplicate probe `1314ea9ce992ef33c3fa8f64dc9b88494309721b8226e22016d65ff64ad4725d`; duplicate verification `7187e1d61661314c6e595e48c9790c5cab83e05ef178c566c0f4f6bde48a9ff9`; shared negative origin `8fb23f0a0382528797e0df3cb2f2732f6273f2a0d3cdfe259e74787f60202c90`. Worktree remained clean at review completion. No overall hosted qualification or HM09 readiness is granted.
