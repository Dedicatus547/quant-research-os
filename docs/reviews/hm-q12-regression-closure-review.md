# Q12 regression successor independent closure review

Date: 2026-10-01. Assigned model: gpt-6.1-sol; effort: high. Review attempt: 2. Outcome for the exact successor bytes below: **OPEN / NOT_QUALIFIED**. Three original defects are closed within their stated code scope; the interpreter-path part of the fourth is corrected, but actual manager import-isolation flags remain unbound. A new native descendant-cleanup defect blocks acceptance.

The baseline remains `359338d35e880a93f06ff5bcffb005bdd7de5368`, with uncommitted implementation. This report does not alter [the initial OPEN review](hm-q12-regression-narrow-review.md), qualify Q12 or the MVP, or apply to later edits. The initial report retains SHA-256 `36a94cf6b025b755ad63f41bd721877848fc3c673ee6e8cbb0de977ce206e621`.

The reviewer made no implementation changes, credential/provider/authentication requests, full-CI run, or commit. Native checks used authorized `/proc` and bubblewrap access, disposable roots under `/tmp/hm-q12-independent-review02`, and private network namespaces. The four reviewed implementation files were copied to `reviewed-source/` before any further successor changes.

## Exact source identity

| File | SHA-256 |
| --- | --- |
| `src/quantos/infrastructure/hosted_regression_capture.py` | `6d83332631807199a173a6baed65ded1f8edb3cc4c76e0b85c622b25a8408ff3` |
| `src/quantos/infrastructure/hosted_regression_verification.py` | `f5545f5960e5bd84176feb2a790d0dcbf37af8411432ad6c73fbcde44383f703` |
| `src/quantos/infrastructure/hosted_regression_runtime.py` | `cf6838d887467a073e24da5811e3f3ed088876894e1b7d1d55d3c8e9b12b224c` |
| `src/quantos/infrastructure/hosted_budget_staging_paths.py` | `9abdc6401ef2ecabd4be6e822bf69e71c22a876f5071dd6311260940c552a3c4` |
| `tests/unit/test_hosted_regression_capture.py` | `d5ae4d5186985b3f2c10f5d6b3b8966c7b8d09cf6d6ff6ffabe65f1e287c7b89` |
| `tests/unit/test_hosted_regression_verification.py` | `69a7923e82915c5e595205ff80254ad87f82b63ee7eb88c6b9ce4f280893e5bd` |
| `tests/unit/test_hosted_regression_origin.py` | `4cd6a6975f8716388b9099a5edc515f4ef64fdb0fe1f7fac048060812b119cc9` |
| `tests/unit/test_hosted_budget_staging_paths.py` | `2855ca624bbf751850e064a9fbfa0626c5f9ba82824dd351b4d93251b01280bd` |
| `tests/unit/test_hosted_regression_preparation.py` (read-only supplemental review) | `5088543d82d3e5e6971249d25281b09906a28dc20324cf15e080049ab5720c66` |
| `tests/conftest.py` | `0e07213a815bab2c9c1fe5f32773d7031810f4d6e4ea6a7fc64d8e208e19d31f` |
| `tests/integration/test_hosted_business_e2e.py` (additional marker) | `0108bb0ef38c91bd376feed4517a7b642b44a443ea4fc48713e4c4db61a569eb` |
| `tests/unit/test_hosted_offline_origin.py` (frozen mount-policy fixture binding) | `5adc4cd55e85e4aedc6dede968bcea9413f8a3a5896b701082cba674b08a6dbd` |
| `pyproject.toml` | `0243ff6735d14024305476e70ca099710e1537218df7dd1e96cee3a97bd620fd` |

## Closure of the initial four findings

| Initial finding | Assessment of these successor bytes |
| --- | --- |
| Default pyright version transport | **CLOSED, code scope.** Fixed child environment sets `PYRIGHT_PYTHON_IGNORE_WARNINGS=1` and bundled-tool selection. Every fixed CLI enters `--unshare-net` with cleared environment and capabilities dropped. The manager observes the still-blocked bridge's actual network namespace, ancestry and Python executable before releasing its exec barrier. Native positive and incorrect-executable controls passed independently. |
| External/cache Node | **CLOSED, code scope.** Preparation copies explicit native Node bytes into private `node-bin/node`, sets mode 0500, and creates an original declaration with node hash/size. Runtime verification recomputes the exact directory inventory and declaration. Node is first in fixed PATH; NodeJS-wheel selection is disabled. The namespace mounts the private Node root read-only. No cache fallback is selected while that verified private executable exists. |
| External Python prefix and capture path | **PARTIALLY CLOSED.** The actual executable path, `sys.prefix`, capture module path, complete derived prefix inventory and declaration are now checked and independently exercised by source-mutation controls. Actual manager isolation flags are still not enforced; see the remaining P1 below. |
| EOF deadline bypass and escaping wait/output loss | **CLOSED for the original EOF defect.** `_check` waits after EOF using the remaining original deadline, kills/reaps the wrapper on timeout, and returns its retained output and actual exit instead of the former escaping `TimeoutExpired`. The native closed-output control passed independently. This does not establish termination of all namespace descendants; the separate P1 below remains. |

The verifier retains the full fixed argv, namespace argv, original prelaunch/exit records and actual kernel observations, reconstructs their bindings, and requires the original runtime-install/declaration exports. It continues to recompute the line/branch 85% gate and reject omitted source, failed/error/skipped testcases or a selected test command. None of these controls reduces the frozen gate.

## OPEN P1: a timed-out namespace leaves a live tool descendant

`ci_namespace_command` in the reviewed runtime, lines 157–163, uses `--new-session` without a PID namespace. `_check` in the reviewed capture kills the wrapper process group and waits for that wrapper, lines 147–156. The sandbox tool's session and process group are separate, and the wrapper's death does not terminate every descendant.

The independent native diagnostic invoked the real namespace command and real bridge gate. After the manager verified the private network namespace and matching Python hash, the tool spawned a Python child sleeping for 30 seconds, printed that child's actual PID, and slept. `_check(timeout=1)` returned `CHECK_TIMEOUT` and wrapper exit `-9`. The child remained a live sleeping process. A second control waited 0.3 seconds after `_check` returned: the tool had exited, but its child remained `State: S (sleeping)` and had been reparented. This establishes a surviving descendant, rather than merely a short signal-delivery delay. The reviewer matched and killed only the disposable diagnostic children; the follow-up tool-cleanup check confirmed the first tool had already exited.

First diagnostic: wrapper `1508744`, bridge/tool `1508745`, descendant `1508746`. Grace control: wrapper `1509044`, bridge/tool `1509045`, surviving descendant `1509046`. The grace log records actual bridge ancestry, executable hash, different network namespace, denied network-probe errno, original printed output, failure, and cleanup. These process IDs identify disposable diagnostics, not qualification sources.

A live descendant can continue writing the writable CI workspace/output root after the manager claims completed capture. Wrapper wait/reap alone cannot establish complete execution termination or stable raw evidence. Minimum closure: use a kernel mechanism that terminates the entire fixed namespace/process tree, capture its actual identity before releasing exec, and mechanically require observed namespace termination. Keep native controls for timeout, closed-output timeout, and a successful tool that detaches a still-live descendant. Host and guest PID identities must remain explicitly cross-checked if a PID namespace is added.

## OPEN P1: actual manager import-isolation flags are not enforced

`prepare_managed_regression` returns a fixed `-I -B` management launch, but `run_managed_regression` does not verify the actual interpreter's `isolated`, `ignore_environment`, `no_user_site`, or `safe_path` flags. It records neither those actual flags nor a checked manager launch identity. The source verifier checks the correct prefix/path/cache facts but has no corresponding flag assertion.

Launching the same frozen prefix without `-I` can retain the same executable, `sys.prefix`, and capture-module path while accepting external PYTHONPATH or user-site dependencies. A fixed returned argv does not establish the actual launch when the callable preflight accepts weaker flags. This is a static source/guard finding; no unsafe real management launch or full CI was executed by the reviewer.

Minimum closure: hard-require the actual four flags before any capture writes, save those facts in the original run record, and require them in the verifier. Add a native or bounded preflight negative for the same frozen prefix without isolation, preserving the normal fixed-launch positive.

## Staging and derived-prefix assessment

The staging helper accepts only Q06 and Q12 families. Its default Q06 components and identity check are unchanged; Q12 adds only the fixed `qualification-checks` family. Existing protected authority, input, config, projection, provenance, evidence and install inode closures are inspected before creating a staging ancestor. Child preparation runs after `fchdir` to the newly created pinned directory. Parent reaping is real `waitpid`; post-copy checks compare original parent/root identity and declaration hash, then recompute the complete prefix and private Node inventory. Failure publication uses the pinned evidence fd and retains failed roots.

The prefix consists of the full frozen `python/` file inventory plus exactly the official coverage startup hook. The preparer checks the hook's SHA-256 and length against the frozen coverage wheel RECORD before copying. Actual prefix contents, modes and inventory bytes are compared to this derivation. The production installation is not modified. The read-only supplemental preparation tests cover a valid forked copy, unbound hook, non-native Node and an existing retained root; this reviewer did not independently execute that newly added four-case file.

Independent component execution of the three regression files and staging-path file produced **117 passed in 35.44 seconds**, including real bridge/network, wrong-executable, EOF and alias/path controls. It was a component command without coverage. The parent log separately reports **151 passed in 30.25 seconds** and zero pyright errors/warnings; these are supporting component/type facts, not Q12 qualification.

The parent real-tool component records an actual network-isolated pyright exit 0 using a newly derived tool prefix and private Node. Its original sources are a read-only borrowed baseline-359 installation whose wheel lacks the new Q12 implementation. The original component record explicitly says `NOT_QUALIFIED`. The reviewer inspected its script, raw tool log and result record; this is runtime feasibility evidence for the derivation, not a new source-bound full-CI run or an independent complete matrix.

No new exact-commit frozen installation, complete offline CI record with at least 85% coverage, full original manager export or complete acceptance matrix is available for these bytes. **Q12 and MVP remain NOT_QUALIFIED**, regardless of the limited closures above. Later PID/flag changes need a separate exact-byte closure review.

## Evidence hashes

The first group is relative to `/tmp/hm-q12-independent-review02/`.

| Evidence | SHA-256 |
| --- | --- |
| `components.log` | `31cf1c11e114ef4af251d08da29ab6f6739e05684444f80d057a6cc993a7d267` |
| `descendant_probe.py` | `d15558ece9bc8ae0c29299073cc2eaa95454e8961bd120c2887d136b77e7d276` |
| `descendant_probe.log` | `1e9c5a0575c2868d9c77afd197524cc120593decffe02323e5bf878302d62cff` |
| `descendant_grace_probe.py` | `6ad8248f8dc0d25e6ae12f4383d8f0ee2b5abd66500b50f013a792fa7f523b19` |
| `descendant_grace_probe.log` | `1a7dac86fe5a85f713d4db875488dcce4e9bb913c50a930d630c4a68aa564766` |
| `cleanup_probe.py` | `4fbc97f1c67d9004b0fa5f2675afa80d49063459a0a93c4474f2436b9e09d50a` |
| `cleanup_probe.log` | `4e79e10009d1730c36d97bf2cabbfb61b23c62501db357201b7bc4c54359d105` |
| `/tmp/hm-q12-prefix-components05.txt` | `11c3f7a1b2aedf6f6b03eb26cd3af679241fa29fbb3b3cf1c911499d63aa0115` |
| `/tmp/hm-q12-prefix-type04.txt` | `6d88a1b220adb7a3d62092b6e38431f0b3fe8babe9864fab90e5849766260332` |
| `/tmp/hm_q12_frozen_tools_component01.py` | `986d0183bd2c72e249ae6ce58c04334bb3fb55fd9eb52ac496ca8d2bab76f31f` |
| `/tmp/hm-q12-frozen-tools-component01.log` | `736e52227f1f3ba55a8dc7f9946a3ee875b2e4366d5dcffe548c0c0fa8e57c5a` |
| `/tmp/hm-q12-frozen-tools-component01/qualification-checks/Q12/component-result.json` | `0bf40b5e52bfe56fcf96bbdd4fe31d5cc12c77a6f0517cab32de543a56dfd6f4` |
| `/tmp/hm-q12-frozen-tools-component01/qualification-checks/Q12/pyright-component.txt` | `6d88a1b220adb7a3d62092b6e38431f0b3fe8babe9864fab90e5849766260332` |
