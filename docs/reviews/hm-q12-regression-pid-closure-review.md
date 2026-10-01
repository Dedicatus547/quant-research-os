# Q12 PID namespace and interpreter flags independent closure review

Date: 2026-10-01. Assigned model: gpt-6.1-sol; effort: high. Review attempt: 3. Outcome: **the two remaining reviewed code defects are CLOSED for the exact bytes below; Q12 and MVP remain NOT_QUALIFIED**. No additional substantive blocker was found within this narrow scope.

The baseline remains `359338d35e880a93f06ff5bcffb005bdd7de5368`, with uncommitted implementation. This assessment applies to the final PID/flag successor, not to the preceding source identities. [The initial OPEN review](hm-q12-regression-narrow-review.md) and [the second OPEN review](hm-q12-regression-closure-review.md) remain unchanged, with respective SHA-256 `36a94cf6b025b755ad63f41bd721877848fc3c673ee6e8cbb0de977ce206e621` and `318214e13aea00e913a0f0c77091fd94da3159eee2b8ccb446734a75b46e28f6`.

The reviewer did not modify implementation, access authentication/provider services, use credentials, run full CI, commit changes, or alter old evidence. All independent writable diagnostics use the new `/tmp/hm-q12-independent-review03` root. Native checks used authorized real `/proc`, bubblewrap and Linux pidfd syscalls. Reviewed source/test copies are retained in that root's `reviewed-source/` directory, and the production source hashes were rechecked after execution.

## Exact reviewed bytes

| File | SHA-256 |
| --- | --- |
| `src/quantos/infrastructure/hosted_regression_capture.py` | `6decb0f415315b57ebdcf33caf4dd0e7b824d6cf83deaa88d99c5f98a3f6d381` |
| `src/quantos/infrastructure/hosted_regression_runtime.py` | `aa3652720a1fb418a8781d1a6c1827e311d102c0b39568f82d4d7c8f2eafbe81` |
| `src/quantos/infrastructure/hosted_regression_verification.py` | `c3810bb00b6d3c776bca3b647a75039161584c0046bda800a4fe961b01f36f4d` |
| `src/quantos/infrastructure/hosted_budget_staging_paths.py` | `9abdc6401ef2ecabd4be6e822bf69e71c22a876f5071dd6311260940c552a3c4` |
| `tests/unit/test_hosted_regression_capture.py` | `b7dcbd234f020ba1b4029238efbe9d8731ad926f3323a3b6faa7d358a97c4c1f` |
| `tests/unit/test_hosted_regression_origin.py` | `893e282e5ea904b0e3e0ca685c0915a0ea5036671109888a2765b7bb1fd5742c` |
| `tests/unit/test_hosted_regression_verification.py` | `69a7923e82915c5e595205ff80254ad87f82b63ee7eb88c6b9ce4f280893e5bd` |
| `tests/unit/test_hosted_budget_staging_paths.py` | `2855ca624bbf751850e064a9fbfa0626c5f9ba82824dd351b4d93251b01280bd` |
| `tests/unit/test_hosted_regression_preparation.py` | `5088543d82d3e5e6971249d25281b09906a28dc20324cf15e080049ab5720c66` |

## CLOSED: complete namespace descendant cleanup

The fixed bubblewrap command now adds `--unshare-pid`. Before permitting tool exec, the original management parent traverses only the fixed wrapper's real `/proc/.../children` tree, with process-count and input-size bounds. It finds the original namespace PID 1 from the kernel's NSpid mapping, opens a real pidfd for that init, and maps the bridge's guest PID to the actual PID visible to the management parent. The bridge remains blocked on its stdin barrier during these observations.

The parent verifies the actual executable hash, ancestry through the fixed wrapper and namespace init, the bridge's guest parent PID 1, and distinct actual PID and network namespace identities. It releases the barrier only after those checks. The resulting original record keeps both the guest namespace PID/parent and the parent-visible PID/ancestry; the verifier requires their structure and bindings. The bridge's guest numeric PID is not treated as a global or parent-visible PID.

`_check` now observes the original init pidfd after command completion or failure. Timeout handling kills the wrapper and, when available, the original init via its pidfd; cleanup also ensures a still-live init is killed and observed. Successful completion requires the namespace to have ended without an unresolved cleanup failure. `namespace_exit_observed` is saved in the original kernel observation, and the verifier requires it to be exactly true. Termination of namespace PID 1 provides the kernel boundary that the previous wrapper process-group cleanup lacked.

The runtime calls the real Linux pidfd syscalls through libc, resolving their syscall names with the existing libseccomp facility. It does not substitute a synthetic PID or hardcode syscall numbers. Independent execution exercised these actual calls on the available Python/libc environment.

The reviewer independently executed the updated native component tests, including timeout, stdout-EOF timeout and success, each spawning a real 60-second descendant with `start_new_session=True`. The original parent opened that descendant's pidfd while it was alive and verified readiness after `_check` returned. All three controls passed.

A separate independent diagnostic retained the raw native observations for the same three completion modes. It confirmed:

| Mode | Wrapper result | Original namespace exit | Detached descendant pidfd exit | Wrapper reaped |
| --- | --- | --- | --- | --- |
| Timeout | `-9 / CHECK_TIMEOUT` | true | true | true |
| EOF timeout | `-9 / CHECK_TIMEOUT` | true | true | true |
| Success | `0 / failure=null` | true | true | true |

Every record shows bridge guest PID 2, guest parent PID 1, a different actual PID namespace and network namespace, a parent-observed four-process ancestry, the expected Python executable hash, and denied network-probe errno 101. The independent diagnostic's actual detached descendant PIDs were `1512960`, `1512968`, and `1512997`; their original pidfds were opened before exit, so the readiness assertion does not rely on later PID lookup or reuse. The previous review's surviving-child counterexample is closed for this successor.

## CLOSED: actual management interpreter flags

`run_managed_regression` now rejects before capture writes unless actual `sys.flags.isolated`, `ignore_environment`, `no_user_site`, and `safe_path` are enabled, in addition to the already required frozen executable/prefix/module path, bytecode setting and empty private cache prefix. This enforcement is inside the executing manager, rather than inferred solely from the preparer's returned launch argv.

The original run record contains the actual four flag facts, and the verifier requires each corresponding field to be exactly true. The prefix, Node, source inventories, fixed tool argv and original export bindings remain required. The frozen complete prefix plus these actual flags closes the reviewed external-import startup gap without changing the production installation.

Beyond the existing `manager-non-isolated` source-fixture negative, an independent bounded synthetic predicate control set each of the four original-record flag fields false separately. All four were rejected specifically with `Q12 capture runtime differs from frozen source-only management`. These controls construct synthetic original-source fixtures and exercise the predicate; they are not actual deployed manager or qualification records. The production preflight's four flag reads and placement before writes were independently reviewed in source.

## Independent checks and source/export assessment

Independent execution covered the three regression files, staging-path tests, and forked prefix-preparation tests: **127 passed in 65.84 seconds**. This was a bounded component command without coverage, not full CI. It includes real PID/network bridge positives and incorrect-executable rejection, detached descendant cleanup, source/namespace mutations, coverage/JUnit tampering, finite staging families, protected alias rejection, pinned-root identity, valid preparation and retained failed preparation. The parent separately reports **161 component passes in 45.15 seconds**, zero source pyright errors, all ruff checks passed, and 525 files already formatted.

The runtime/source export requirements continue to bind the exact complete derived prefix inventory, private Node declaration, fixed namespace/tool argv, original prelaunch/exit/log bytes, and original authority snapshots. The verifier now also checks distinct PID namespaces, namespace-init membership in the original ancestry and observed namespace termination. The fixed full pytest command, installed-source coverage closure, per-line/branch count recomputation, no-failure/no-error/no-skip JUnit requirements and 85% threshold remain intact. The Q06 staging helper's existing defaults and protected-inode behavior are unchanged by this PID/flag successor.

The parent real-tool component under `/tmp/hm-q12-frozen-tools-component02` completed network/PID-isolated pyright with code 0, `failure=null`, original authority unchanged and `namespace_exit_observed=true`. The reviewer inspected its raw result and log. Its complete derived prefix/Node declaration is bound in that original component result. It still borrows the old baseline-359 installation, whose wheel lacks this new Q12 implementation, and explicitly records `qualification_eligibility=NOT_QUALIFIED`. It demonstrates actual tool-prefix and namespace feasibility, not a new source-bound complete Q12 run. The failed external driver log for its preceding attempt remains separate and was not overwritten.

No new committed exact-source frozen installation, complete offline CI capture with coverage at least 85%, original full manager export or complete Q01–Q12 acceptance matrix has been evaluated here. Closing these two code findings does not grant Q12, HM-09 or MVP eligibility, and does not turn selective component reports or the borrowed old-wheel run into new qualification evidence. **Q12 and MVP continue NOT_QUALIFIED.**

## Retained evidence hashes

The first group is relative to `/tmp/hm-q12-independent-review03/`.

| Evidence | SHA-256 |
| --- | --- |
| `components.log` | `5e65a7f607fe18ab771d6ba244067aa141399699a694265fcfb523c17b19ef36` |
| `pid_cleanup_probe.py` | `497e3446ae8a626b2ff163404709b69ef73984077ff8515c56f6d8e1b4aa0544` |
| `pid_cleanup_probe.log` | `c19f88dfcff5c241cdcea16af3cd1187803ad54caa18c12191bf6b77d1a7da0a` |
| `flag_verifier_probe.py` | `1ea33d8d2d116b04ad12c128de56a7bb10fdc110ab3ff08d84dce906ecff31b6` |
| `flag_verifier_probe.log` | `2f8b2281f792dcde6eb3fef88965cf7de8c150189109afbbf7142bedb5fb06ae` |
| `/tmp/hm-q12-pid-components03.txt` | `8eb9b6c7023c1d3aac5d7518da4814f4d8998943df9bcbfc29a664f8e5ad8971` |
| `/tmp/hm-q12-pid-type02.txt` | `6d88a1b220adb7a3d62092b6e38431f0b3fe8babe9864fab90e5849766260332` |
| `/tmp/hm-q12-pid-ruff01.txt` | `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18` |
| `/tmp/hm-q12-pid-format01.txt` | `db6a7e53ced5545d0f0449fd8d3fb8d3dcfffe50c371df47663526e5b38580b6` |
| `/tmp/hm-q12-frozen-tools-component03.log` | `736e52227f1f3ba55a8dc7f9946a3ee875b2e4366d5dcffe548c0c0fa8e57c5a` |
| `/tmp/hm-q12-frozen-tools-component02/qualification-checks/Q12/component-result.json` | `6dade4145c9e2a90d2f28e522c6b250935fbb690ff77d3d9d2519b8bd3d642fd` |
| `/tmp/hm-q12-frozen-tools-component02/qualification-checks/Q12/pyright-component.txt` | `6d88a1b220adb7a3d62092b6e38431f0b3fe8babe9864fab90e5849766260332` |
| `/tmp/hm-q12-frozen-tools-component02/qualification-checks/Q12/runtime-declaration.json` | `0b54acdca811e11088663971a8e9ad6985cdd3495f26d3863ff885da43906354` |
| `/tmp/hm-q12-frozen-tools-component02/qualification-checks/Q12/runtime-install.json` | `83fd4b9b564a899699183fe05dd7bc13f94cd99f714fc09832a969654a49e075` |
