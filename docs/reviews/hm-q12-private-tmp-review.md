# Q12 private temporary filesystem independent narrow review

Date: 2026-10-01. Assigned reviewer: gpt-6.1-sol, high effort. Baseline: `5026a64171eb95180ffeffc2f27fd74d397ebc8e`. Outcome: **OPEN: the persistent pytest source directory can alias a protected prefix and obtain a writable mount. Q12/MVP remain NOT_QUALIFIED.** The initial mount-point basetemp also fails natively; the later short child-path revision addresses its configuration, but does not close the writable-alias finding.

Scope covers `hosted_regression_runtime.py`, `hosted_regression_verification.py`, the two affected regression/native-Python test files, and existing source predicates relevant to those changes. Independent controls and source copies are retained under `/tmp/hm-q12-private-tmp-independent-review01`. The reviewer did not edit production implementation, run full CI, read authentication/model material, execute providers, modify or rerun installation 23, or change the 85% coverage requirement. The management Q06 timeout change is outside this review.

## Exact source identity

| Observed source | SHA-256 |
| --- | --- |
| `hosted_regression_runtime.py`, first revision binding and basetemp both `/tmp/pt` | `3273906275d42a4b3e0def5d483b90ebd11fe0df855de73010a23880a26d911b` |
| `hosted_regression_runtime.py`, next revision binding `/tmp/pt`, basetemp `/tmp/pt/b` | `105f964ed18b764644efa8a54b9e7568a0fffe99d00f7dc334927aea394d8451` |
| `hosted_regression_verification.py`, both observations | `d89ae02f69a01722d07709eb63b6757e970ebf0dec4c284a7a4413d1b6c11f67` |
| `tests/unit/test_hosted_regression_capture.py` | `55ba4dbcc8b31ca7d30a50847deb3f52864a685509344712fd11c13fdb7c5a89` |
| `tests/unit/test_hosted_python.py` | `d3b30140fa4925af4b2c5966841f6ba8f257e58cf33588c30fd1e40fd0ad9c00` |
| `hosted_regression_capture.py`, unchanged original parent/kernel capture | `6decb0f415315b57ebdcf33caf4dd0e7b824d6cf83deaa88d99c5f98a3f6d381` |

The second runtime revision and reviewed test/verifier bytes were copied to the independent root. The first runtime revision is also retained as `initial-runtime-reconstructed.py`, reconstructed from the second revision by reverting only the two observed short-path edits; its complete SHA-256 exactly equals the originally observed `32739062…`. This explicitly distinguishes reconstructed source retention from the native outputs collected while that first revision was active.

## Blocking writable source alias

The wrapper still read-only binds `/`, the complete derived `.venv` and frozen Node, then adds a writable bind from `target/pytest-root` to `/tmp/pt`. Preparation creates that directory once in the pinned private child, but neither the command builder nor runtime/declaration verifier validates or pins that source directory when later commands mount it.

In a new component root, the reviewer set `target/pytest-root` to a symlink to `target/.venv`, retained the fixed wrapper and native bridge checks, and executed a program writing only `/tmp/pt/protected-marker`. The actual subprocess returned **0**, its original kernel bridge passed, and the marker appeared in **`target/.venv/protected-marker`**. The target prefix is a small component directory, not a real installation, and no protected repository or old deployment was altered. The control proves that a writable alias mount bypasses the `.venv` read-only mount at its ordinary path.

The same mechanism can target Node. All fixed CI commands receive the writable `target` bind; a preceding command can replace its `pytest-root` pathname before a later wrapper mounts it. Final prefix inventory equality would reject changed bytes and therefore prevent qualification, but it does not prevent the forbidden write or subsequent execution through an altered prefix. Fixed argv equality and network/PID namespace checks do not establish the source directory's identity.

Required closure: require the prepared source to remain a no-follow directory independent of `.venv`/Node and bind the validated source identity through actual wrapper execution. A check only during preparation does not close the later alias. A path check during command building also needs a source pin or equivalent mechanism if the source can change before bwrap resolves it. Builder/verifier checks must remain read-only and must not create a missing source. Preserve the exact fixed command/mount policy and original observations rather than weakening post-verification predicates.

## Native mount-point basetemp failure

The original revision used `--basetemp=/tmp/pt`, where `/tmp/pt` was itself a bind mount. The installed pytest `TempPathFactory.getbasetemp` deletes an existing basetemp and then creates it. In the independent one-test native wrapper control, pytest emitted a real `EBUSY` warning while trying to remove the mount point and then raised `FileExistsError` recreating it. The actual command returned **1** and the fixture never ran.

The next runtime revision changes `CI_PYTEST_TEMP` to `/tmp/pt/b` and binds the source to its parent `/tmp/pt`. That resolves the static mount-point conflict while retaining a short path, but this initial report does not claim a completed positive native pytest control for that later revision. It remains affected by the writable source alias above.

## Other assessed boundaries and fixture evidence

Creating a private tmpfs `/tmp` and then explicitly restoring only the workspace, management target and short persistent pytest directory is consistent with the intended temporary-write correction. Ordinary symlinks created *inside* that temporary filesystem resolving to the guest's protected prefix path encounter the read-only mount; the observed bypass comes from the host source used to create a separate writable mount. The original network/PID unsharing, capability drop, real bridge barrier, executable hash, process ancestry, deadline and namespace cleanup remain unchanged.

The verifier still derives `regression_commands` from frozen source and compares all five exact CLI argv and namespace argv, including the short basetemp. It still requires code 0/no capture failure, original prelaunch/completion equality, the complete installation/runtime derivation, all project source coverage, exact before/after authority and directory closure, valid original reports and coverage at least 85%. No whitelist or caller-selected mount/command was added. Changed source requires a new freeze/installation; installation 23's argv and failures cannot be relabeled as belonging to this revision.

The stale-cache test correction explicitly sends `py_compile.compile` to the real standard `__pycache__/<stem>.<cache_tag>.pyc`. It retains equal source lengths, timestamp invalidation, the original timestamp, an ordinary isolated interpreter observing the stale marker and the native source-only interpreter observing frozen source. Independent execution under an actually inherited `PYTHONPYCACHEPREFIX` with bytecode writing disabled passed **all 7 native-Python tests in 2.45 seconds**. The new fixture therefore exercises the intended real stale cache rather than an environment-relocated file.

The parent component log reports **64 passes in 46.61 seconds**; those passes do not include the mount-point or source-alias counterexamples and cannot close them. No complete new installed-source Q12 run was executed by this reviewer.

## Evidence hashes

Files below are relative to `/tmp/hm-q12-private-tmp-independent-review01/`.

| Evidence | SHA-256 |
| --- | --- |
| `mount_basetemp_probe.py` | `19ccde04dd002ab2689a802cd25567d6f6ebf49913530503435520cf405db4c3` |
| `mount-basetemp/original-output.txt` | `da27b35e45e550d518d82b5302aa7192c6737687bb163549270ab25bfb5c1a2b` |
| `mount-basetemp/result.json` | `4f82b1002c730a03e005823d6b1cf50e035c1c759effc9d2e1e402fa53d5b02f` |
| `alias_mount_probe.py` | `8a315aa08e6d3cbdb79eb57c1039ccd9e740eb474c51b44c7285a5231b12efe3` |
| `alias-mount/original-output.txt` | `f1413c059c19675e8b79a3609c56fdd689b2e09a917c79a1f01b7234ea3d12df` |
| `alias-mount/result.json` | `9c19571ef7a63bc2383d51c5513d0d88c1272546382a80e62a342055c03643c7` |
| `python-fixture-inherited-cache.txt` | `59d7714cefba8492e07a27cc2338f2b9b9d551686c5061175e5211073171cd76` |

Installation 23 remains the parent's retained failed original: D `031f62c214fb8f4b88d6b0c9cfbcdc09e810e2f95ed6972788a81937e20f884e`, 7 failures/1495 passes and 78.46% coverage, NOT_QUALIFIED. These reported numbers are context rather than independently rerun evidence. No old root was repaired, and this review grants neither Q12 nor MVP acceptance. This OPEN report must remain tied to its reviewed bytes; any later closure requires separate exact-source evidence and a new report.
