# Nested CI Python prefix — independent closure review

Date: 2026-10-01. Independent reviewer: `gpt-6.1-sol`, high reasoning. Current source baseline `98e6f2f04e86f9b1a2a3a6bb6e185bb88609ed19` with the three-line uncommitted runtime correction.

**CLOSED for the missing Python-prefix mount under nested private /tmp on these bytes. NOT_QUALIFIED.** An actual kernel counterfactual fails with ENOENT when only the new three mount arguments are omitted; the fixed command succeeds with the prefix still read-only. A separate independent outer/inner namespace run completes all ten current capture tests. No new blocker was observed within this narrow scope. This does not grant Q12, HM09, deployment or MVP qualification.

## Source identity

| Reviewed source/test/configuration | SHA256 |
| --- | --- |
| `src/quantos/infrastructure/hosted_regression_runtime.py` | `8432333df6f22de31f77335d7f08dd968445aba4436799b7bf18655b2460ae27` |
| `src/quantos/infrastructure/hosted_regression_capture.py` | `17dec4839260c5a873dedce4853402740210f03ba640da3a109fd36a5e86e025` |
| `src/quantos/infrastructure/hosted_regression_verification.py` | `d89ae02f69a01722d07709eb63b6757e970ebf0dec4c284a7a4413d1b6c11f67` |
| `tests/unit/test_hosted_regression_capture.py` | `b7dcbd234f020ba1b4029238efbe9d8731ad926f3323a3b6faa7d358a97c4c1f` |
| `pyproject.toml` | `a243e6038acdfbdf58b3623082e37a516da9c698ac54b53d9d1af38eccfef972` |

All five source/test/configuration hashes remained unchanged before and after the independent controls. The runtime source is also preserved as a read-only copy. These observations identify local file bytes; they are not an installed-source or wheel provenance attestation.

The only production change in the reviewed diff adds `--ro-bind python.parent.parent python.parent.parent` immediately after private `--tmpfs /tmp` and `--dir /tmp/pt`. It restores access to the exact selected interpreter's prefix when that prefix is under /tmp. It does not restore the surrounding host /tmp. The existing workspace/target mounts and later read-only target/.venv and node-bin mounts remain. In a qualified run the verifier still requires the Python path to equal the fixed deployment Q12 prefix, so this is not a new research caller-selected tool source. The ordinary deployment target/.venv mount remains the last protection over that prefix after the writable target mount.

## Original failure retained

The original D24 `/tmp/hm-stage-2369554-attempt24/qualification-checks/Q12/pytest.txt` was read only. It records **5 failed, 1757 passed in 7170.77 seconds**, with **84.55%** coverage. Its five failures are the frozen/wrong-hash kernel bridge pair and detached-descendant timeout, EOF-timeout and success controls in `test_hosted_regression_capture.py`. The log hash is bound below; its summary and node names are retained separately in `old-ci-facts.json`. This failing original run is not repaired, replaced or used as a passing CI result. No conclusion about the in-progress D25 result is made here.

## Actual independent controls

New diagnostic root: `/tmp/hm-q12-nested-python-prefix-independent-review01`. No implementation or test change, old-root modification, authentication/model/provider call, or complete CI occurred.

For the mount comparison, a new private component-only Python prefix was copied from the local interpreter/standard library, with no frozen deployment claim. Workspace and persistent output are distinct sibling directories. The negative argv is the positive fixed argv with **only the new `--ro-bind` and its two prefix operands removed**; both go through the actual current `_check`, bwrap, kernel namespaces and real native wait/reap.

| Native mount control | Prefix mount omitted | Exact prefix restored read-only |
| --- | --- | --- |
| Actual result | bwrap exec Python: No such file or directory | command executes successfully |
| Return code / failure | `1` / `CHECK_BRIDGE_INVALID` | `0` / null |
| Original-parent kernel bridge observations | absent | executable hash, ancestry, different net/PID namespace inodes, and namespace exit observed |
| Persistent report | not created | retained under writable target after namespace exit |

The successful native probe verifies `sys.prefix` is the selected private copied prefix. It attempts truncating writes to five existing owner-writable canaries: the interpreter prefix directly, through a workspace symlink, through a symlink created in private /tmp, the separately protected target/.venv, and the protected node-bin. **All five attempts return EROFS (errno 30)**. The three actual canary files retain their original hashes. These canaries live only in the new root; no write attempt targets an old frozen deployment.

The same probe writes private /tmp scratch bytes and creates/listens on a short actual AF_UNIX socket under /tmp/pt. It writes a private /tmp marker that remains absent from host /tmp after the run. Its persistent target report survives and is byte-identical to captured stdout. Together these observations show that restoring the Python prefix did not remove private scratch isolation, change the short-path behavior or make the tested prefix/link paths writable.

A second independent component uses the original D24 interpreter bytes **read-only** solely as a tool runtime, current root/src via explicit PYTHONPATH, and the actual current namespace wrapper. The outer wrapper creates private /tmp and mounts that old interpreter prefix read-only. Inside it, pytest executes `tests/unit/test_hosted_regression_capture.py`; the five kernel tests create their own inner wrappers using the outer interpreter path. The result is **10 passed in 12.86 seconds**, exit 0, without coverage. This includes the executable frozen/wrong-hash barrier pair, real native timeout/output/EOF capture/reap, and real detached descendants for timeout, EOF-timeout and success. The outer kernel record also requires executable-hash equality and actual namespace exit. The borrowed Python executable hash is unchanged before/after. No old installation/source identity is represented as a new frozen CI or qualification record.

The separately supplied root-agent component `/tmp/hm-nested-ci-capture-attempt26-01` was read only and reports ten passes in 13.21 seconds. Its script/log/result hashes are bound as supplemental original evidence, independently of the new run.

## Source and fixed-command predicates

Capture and verifier still import the identical `ci_namespace_command` factory. An independent bounded binding check confirms this object identity for all five fixed CI commands and records their exact generated argv. Removing the new mount tuple changes each required argv; the verifier's exact recorded namespace-argv equality therefore still rejects the older omitted-mount form. The source inspection confirms the original prelaunch and exit records retain full argv, actual kernel observations, original stdout hashes and wait/completion facts.

The verifier retains exact frozen-prefix derivation, runtime/declaration inventory checks, fixed Python/capture module paths and hashes, isolated-management flags, tracked-source equality and original export bindings. Its complete installed-source coverage set and recomputed numerical >=85% check are unchanged. The bound pyproject retains source=[quantos], branch=true, thread/multiprocessing concurrency, subprocess/_exit patches and fail_under=85, without new omission or path alias. This review neither lowers the gate nor assumes that fixing five failures will make a future full run exceed it.

## Evidence hashes

Relative paths below are under the new diagnostic root; absolute paths denote existing originals read only. `evidence-sha256.json` contains and was rechecked against all twenty entries. Its SHA256 is `ddba5e97e2c6533073643dad0101ebab8e3202d210df632940a4b366102239fe`.

| Evidence | SHA256 |
| --- | --- |
| `source-before.json` | `344210b79d2f8767882810a9798a4840b5c976b2fd69372ec3c7532fbf8b685f` |
| `source-after.json` | `344210b79d2f8767882810a9798a4840b5c976b2fd69372ec3c7532fbf8b685f` |
| `reviewed-runtime.py` | `8432333df6f22de31f77335d7f08dd968445aba4436799b7bf18655b2460ae27` |
| `independent.py` | `a75f6d3b42da9dec643c27063836ff78b19b825f95c34520b01c30f65d8e9b21` |
| `independent.txt` | `0e2cf2d55fba495496295cf9dd0fa8b1b899d01a405a54dc50c4313b24d77ff5` |
| `independent-result.json` | `9409839e6daba8de3f7e742e454e439c1cb50892c5f8553d81ace959def7ecf2` |
| `missing-prefix.txt` | `07e08c9b3a4e0807482eaa60c868fe44ad9a24043a2542a1154b6250461f4524` |
| `explicit-ro-prefix.txt` | `2ba1ec45de826fbdf20f05847ec3014f9ffb9eb3140998c1fc203a4c6173d09b` |
| `target/persistent-probe.json` | `2ba1ec45de826fbdf20f05847ec3014f9ffb9eb3140998c1fc203a4c6173d09b` |
| `nested_capture.py` | `1289732d9eeb860b8e2a392ed5d56b37535cdd991bc44239f9590f6d6b35d8a7` |
| `nested-driver.txt` | `d9263dc24e1b39956e77337d2e6bb40334ae2c6215a647b30a3cca1d14cdcddb` |
| `nested-tests.txt` | `9d6a668d1940b9b1d3fcecffc5a6db3429615a59632f4f31d8fd86d26476921a` |
| `nested-result.json` | `796aeae991955ce7a85f4a3e44922795803a84e2cbed6b548d298bf20851b976` |
| `argv-binding-driver.txt` | `d04767456a7440e5b8c07d02a3ab934fbf9b41e30e14230db0d715439b5c947d` |
| `argv-binding.json` | `2f8da95aec2bdaa91785469660a7aa12307c7b3c62dd93ef50c5a3c0d39993db` |
| `old-ci-facts.json` | `3f2e0bd4300a322c7b994ebbc4b225e68f3daae9325917907d1b4103500eb658` |
| `/tmp/hm_nested_ci_capture_probe_attempt26.py` | `defe20d3d2f2009a425b4cf608420cbeaff35d1c40cb74d352d78e393c6cbc9c` |
| `/tmp/hm-nested-ci-capture-attempt26-01/output.txt` | `0036540803bbaf01913e42f42362026033708bc547153096681bafda3b944c41` |
| `/tmp/hm-nested-ci-capture-attempt26-01/result.json` | `1161fdefd90fb0be07a3d2648c5bb5f035ab173e7ab3c69995e8ce26a0a22e36` |
| `/tmp/hm-stage-2369554-attempt24/qualification-checks/Q12/pytest.txt` | `c76186630bbec968c808d6cdc53ed016045860e201567d61be615aaf357a15e4` |

This closure applies only to the runtime mount defect and tested boundary behavior. The newly frozen source/wheel/deployment must still produce original full CI with the unchanged 85% gate and the complete matrix, followed by the separate required qualification review. Older failed CI, borrowed runtime bytes and these passing components cannot supply that acceptance.
