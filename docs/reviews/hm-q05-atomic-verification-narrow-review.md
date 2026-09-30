# Atomic predicate and Q05 dispatch original narrow review

Assigned model: gpt-6.1-sol; effort: high; independent attempt: 1; observed usage: unavailable. **NOT_QUALIFIED.** This preserves the original exit-record P1, independently of its subsequent correction. No complete installed atomic source wrapper or full Q05/HM09 qualification has been demonstrated.

Baseline HEAD is `cf9b2d4d776da1b9a67180b88b844d4cbcd0dc35`. Original hosted_atomic_verification.py SHA-256: `ef6ec3e7e3026a5a6fc84419222bd52e092528227ef8feef464a3dddcc03ea9f`. The source was reviewed at this hash before the producer correction. After the shared file changed during the first canary, its original exact bytes were reconstructed by reversing only the reported branch correction and checking this same full-file SHA-256; retained copy `/tmp/hm-atomic-verification-exit-closure-original-ef6ec3.py`. The canary's first shared-source run failed with NameError after encountering the newly introduced source variable; that log remains at `/tmp/hm-atomic-exit-record-closure-independent01.log` and is not a passing control.

| Additional source reviewed | SHA-256 |
| --- | --- |
| hosted_manager.py | 76af3ba10dc0d428d5144cdab0a37f37a1820e1e977c8a0b83c4306b6d4cec2a |
| hosted_negative_origin.py | 01d665a5997cdfda7c72e2e958131b38305255f14806486b3ba107ceb356b21d |
| hosted_fault_verification.py | 09609cd51963bd9caf744327ae423a3432576f917549e1d069f355c5a97c7021 |
| hosted_verification.py | 2fc9aed35e6ad9083f399ed6d0b09cafdeac125cade5dcfa87943f0443af6e3b |
| hosted_fault_cases.py | d6550d49fc969ca07cecd2f55a7504443c0fb5cb1953abcb655d86c68ee6020f |
| test_hosted_atomic_verification.py | f819960d288c0c54a8302121294bf29625c0a7544027f63a811550efee86134f |

## P1: exit files are not bound to their own phase

`verify_q05_atomic_subset` originally accepted each named `*-exit.json` if its payload occurred anywhere in observation.process_exits. It counted all three filenames, but did not require the file's phase to match payload.phase. All three named exit files could therefore contain the same valid crash tuple. `verify_atomic_recovery_scenario` validates the observation's three tuples, not those separately loaded exit files, so it does not close the missing file-to-phase binding. The necessary correction is exact native tuple equality for the phase named by the source file.

The independent bounded canary executes the exact AST expression from the original source against a retained real-fork component observation: crash-exit, recovery-1-exit and recovery-2-exit all accept the identical crash tuple. Script `/tmp/hm_atomic_exit_record_closure_independent02.py`, SHA-256 `9c49e78d579b168791492d1ffb9019ddc56b5bef7b2411bd7eb9629f56997085`; log `/tmp/hm-atomic-exit-record-closure-independent02.log`, SHA-256 `a8c149cda74af93a59fc5cfaa3e56e69600e6740e208fef8fb44971c3c6bc191`. This isolates the precise omitted predicate. It does not claim that fabricated bytes passed an external original-manager export or that any installed producer emitted those duplicated tuples.

## Other bounded observations

The checkpoint derives exact native spec/first REGISTER/object publication bytes, frozen Ledger seed hashes, the one frozen selection-plan path, and the exact parent-directory set. It checks finite temporary geometry and original native same-inode nlink2 facts while treating copied files as byte views only. Published recovery enters the existing pure native business/protocol verifiers, requires initial events/Ledger, one initial budget, one issued request and zero submissions/trials/reports, verifies total native file closure, and projects the expected native status. Rejected intermediate windows require full crash/recovered/after forensic equality.

The source wrapper separately recomputes current original authority physical facts and compares them with both manager and worker after records. It binds exported phase bytes/directories to their original copied snapshot locations, exact installed worker/native binary, durable prelaunch, fixed finite command, actual kernel namespace/credential facts and retained completion. This is a reviewed boundary design, not an observed installed atomic-source success. Copies do not replace the original physical authority.

Full dispatch requires all 44 durable, five corruption and twelve atomic scenarios, each with four roots, before evaluating the three subsets. A missing group cannot receive full Q05 PASS. The manager accepts only those finite cases and selects the fixed atomic module for the twelve atomic cases. Research RPC receives no case/clock/root selector through this change.

Independent deployment/checkpoint controls under the management environment: **38 passed in 16.95s**, log `/tmp/hm-mount-atomic-verification-independent02.log`, SHA-256 `1b0cec80f8233666f35a44d18c5a86626c0a05d93caee6bbdaa45f2b510fbe88`. This process loaded the original atomic predicate before correction. Its predecessor default-sandbox run had 33 passes and five Unix-socket bind PermissionError failures; that failed log remains and is not represented as a product/source-gate success. Native checkpoint geometry and partial-matrix negatives are component controls; complete source-bound installed fork records remain unavailable.

No implementation, original retained roots, frozen worktree, authentication or provider/model was modified or used by this reviewer. Successor closure requires a separate report; this original report remains an account of the defect at its original bytes.
