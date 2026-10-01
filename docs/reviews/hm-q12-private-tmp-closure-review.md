# Q12 private temporary filesystem independent closure review

Date: 2026-10-01. Assigned reviewer: gpt-6.1-sol, high effort. Baseline: `5026a64171eb95180ffeffc2f27fd74d397ebc8e`. Outcome: **the reviewed temporary-write, mount-point basetemp and writable pytest-source-alias defects are CLOSED for the exact source bytes below. Q12/MVP/HM09 remain NOT_QUALIFIED.** No further substantive blocker was found within this narrow change.

This is a new report. The initial [OPEN report](hm-q12-private-tmp-review.md), SHA-256 `5e22e0c5e5592c123161f1f1188c912b79f7cef3e8bf3caffdf711177dc48ce2`, remains unchanged and OPEN for its reviewed revisions. New independent source copies, bounded native controls and original logs are retained in `/tmp/hm-q12-private-tmp-independent-review02`. The reviewer did not change implementation, commit, run full CI, touch installation 23 or old failed roots, invoke authentication/providers/models, or lower the 85% gate. The separate Q06 timeout change is outside scope.

## Exact source identity

| File | SHA-256 |
| --- | --- |
| `src/quantos/infrastructure/hosted_regression_runtime.py` | `160956a192da2b945e1dc1e90497eda56adc26f03086eaadf5784ad6033ee174` |
| `src/quantos/infrastructure/hosted_regression_verification.py` | `d89ae02f69a01722d07709eb63b6757e970ebf0dec4c284a7a4413d1b6c11f67` |
| `tests/unit/test_hosted_regression_capture.py` | `b7dcbd234f020ba1b4029238efbe9d8731ad926f3323a3b6faa7d358a97c4c1f` |
| `tests/unit/test_hosted_python.py` | `d3b30140fa4925af4b2c5966841f6ba8f257e58cf33588c30fd1e40fd0ad9c00` |
| `src/quantos/infrastructure/hosted_regression_capture.py`, unchanged kernel capture | `6decb0f415315b57ebdcf33caf4dd0e7b824d6cf83deaa88d99c5f98a3f6d381` |

## Final boundary and source predicates

The final fixed wrapper creates a namespace-private tmpfs `/tmp` and an internal directory `/tmp/pt`. The fixed pytest argv uses `--basetemp=/tmp/pt/b`, a removable child directory rather than a mount point. Both the external `pytest-root` writable bind and its preparation mkdir have been removed. Therefore there is no new external temporary source to alias `.venv` or Node and no temporary-source check/bind race to authenticate. Builder/verifier execution does not create management filesystem directories: `--dir` is an argv instruction executed by bwrap inside the private tmpfs.

The existing read-only root, complete derived Python prefix and frozen Node mounts remain. Only the existing workspace and management output target retain their external writable binds. A link inside private `/tmp` resolving to a protected guest prefix still traverses the read-only mount. The new temporary directory and its contents disappear with the actual namespace. Temporary pytest fixtures are not authority inputs to the Q12 predicate; original stdout, coverage XML/data, JUnit, tracked-source inventories, durable prelaunch/exit facts and kernel observations remain at the bound original management target. This preserves the original qualification file registry and source mappings without promoting temporary fixture files to authority.

The verifier continues to recompute all five exact CLI argv and complete namespace argv from frozen source, including the new fixed tmpfs/directory instructions and basetemp. It still requires actual code 0/no capture failure, original prelaunch/completion equality, fixed network/PID isolation and ancestry/executable observations, namespace exit, full frozen prefix/Node provenance, unchanged original authority/directory closure, complete installed project source coverage, valid original reports and coverage at least 85%. No additional caller-selected path/command, accepted failure/skip, reduced denominator or predicate bypass was added.

The real stale-cache fixture remains a meaningful control: it explicitly writes timestamp-valid stale bytes to the standard `__pycache__/<stem>.<cache_tag>.pyc`, retains equal source size and timestamp, demonstrates an ordinary isolated interpreter reading the stale marker and the native source-only interpreter reading frozen source. Its inherited-cache test evidence from the original narrow review remains valid for the unchanged fixture bytes. The final capture tests no longer create an unused external pytest-root directory.

## Independent native closure controls

The new driver records the runtime source bytes before importing QuantOS, requires equality immediately after imports and after the run, retains the actual generated namespace argv and invokes the existing native `_check` barrier. Its wrapper completed with code 0/no capture failure, independent net/PID namespaces and `namespace_exit_observed=true`. Source bytes remained at the exact hash above. This is bounded source/control-flow evidence, not a complete installed-module or exact-D attestation.

The following real native controls passed:

- `tempfile.TemporaryDirectory()` can create/read private default `/tmp` files; pytest's actual `tmp_path` fixture runs under `/tmp/pt/b`.
- A real AF_UNIX listener binds/listens at the short fixture pathname; its path is below the 108-byte limit.
- Direct writes to a component protected prefix file and a component Node file both fail with **`errno=30` (`EROFS`)**. Symlinks in private `/tmp` pointing to each protected file fail with the same errno.
- The original counterexample is retained: `target/pytest-root` is a symlink to `.venv`. Because it is no longer a mount source, writing `/tmp/pt/alias-marker` does not create any prefix marker. Both protected prefix and Node inventories remain identical before/after.
- A namespace program writes an independent `/tmp` canary outside the restored workspace/target mounts. The host pathname is absent before and after the run.
- The program creates a persistent report in the bound original target, writes the workspace, and launches an actual isolated two-test pytest subprocess with `--basetemp=/tmp/pt/b` and JUnit directed to the original target. **Both tests pass in 0.24 seconds**, and original stdout/JUnit/report bytes remain readable after the namespace exits.

The protected `.venv` and Node paths in this diagnostic are small component sentinel trees, and the executable is the existing repository interpreter. No real installation or Node binary was mutated; no full scientific or Q12 qualification workload was run. The control verifies the actual mount/write/temporary/socket boundary rather than claiming complete frozen-runtime qualification.

The independent capture/verifier/preparation/native-Python component command passed **59 tests in 15.62 seconds**. This exercises fixed argv/source/identity negative controls, native barrier and namespace descendant cleanup and source-only Python fixtures; it is component coverage, not an 85% complete CI result.

## Preserved failed controls and limitations

The first independent boundary driver tried to create `/tmp/pt` without `exist_ok` after the final wrapper's new `--dir` had already created it. It failed with `FileExistsError`; its script, native original output and root remain unchanged. The successor driver uses a new root and asserts the fixed parent already exists. Production bytes did not change between those two controls. This diagnostic-fixture failure is not represented as a passing run.

The parent's earlier seven-node temporary-filesystem component without `--dir /tmp/pt` reportedly had seven setup errors because pytest does not create a missing basetemp parent. Its failed root remains separate. The independent positive control here executes the corrected fixed parent, removable child and native pytest fixture; it does not reinterpret that earlier failed record.

Installation 23 remains a failed original with the reported 7 failures/1495 passes and 78.46% coverage, D `031f62c214fb8f4b88d6b0c9cfbcdc09e810e2f95ed6972788a81937e20f884e`. Nothing in this closure repairs its root or turns its Ruff, pytest or coverage result into PASS. New source must be frozen into a new D and run through complete offline CI and the required native acceptance matrix. Formal HM09 still requires a separate independent exact-bundle/source review after all originals are ready.

## Evidence hashes

Files below are relative to `/tmp/hm-q12-private-tmp-independent-review02/`.

| Evidence | SHA-256 |
| --- | --- |
| `native_boundary_probe.py`, retained initial diagnostic | `ae4a9566abf6acf3b0430877793b6266b233e6f1d25c49472bee70cfce8f5bf2` |
| `native-boundary.txt`, retained initial failure | `5b388f1c4b42feba9bca9ecba4955d050b0bd25dd3a03759f1af71bcf0bd048f` |
| `native_boundary_probe02.py` | `fe5e1480978e2f4b233d53d2a3b53526604c0a6407c9645f953de364eb5a8616` |
| `native-boundary02.txt` | `a21a0db5d52617cc46755d31d5b161efef9c23f5407e5da8666735be8e7a4c2b` |
| `native-boundary02/result.json`, original argv/kernel/source observations | `b1cbb48354474ebd3aa2407d752bb41a9ed71b2f1b5f531cb2529273f0084bb9` |
| `native-boundary02/original-output.txt` | `1b33c47bf4870e9188ba4a7894da873d51784465f7a95c54815626ffc8f65976` |
| `native-boundary02/ci/pytest-component-output.txt` | `79631db54198e4b091de9920305ff1747a7145831b5ec8cfe4ce531cc1419f22` |
| `native-boundary02/ci/pytest-component.xml` | `2428a225df3ec0c20e4c8abd824ccccf565601e060e8b51f10bb0436479367b7` |
| `components01.txt`, 59 passing bounded components | `30e6dc7a5ec9063234c471bd0fe0d6328f70de9c4a88b5aa2e92c84f9f367f02` |
