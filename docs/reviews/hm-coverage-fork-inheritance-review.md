# Coverage fork inheritance — independent narrow review

Date: 2026-10-01. Reviewer: independent `gpt-6.1-sol`, high reasoning. Baseline `5026a64171eb95180ffeffc2f27fd74d397ebc8e`, with the reviewed uncommitted coverage configuration change.

**CLOSED only for removing the optional fork-reset patch that loses the tested inline child paths. NOT_QUALIFIED remains.** This report does not claim complete offline CI, coverage ≥85%, a qualified deployment, HM09 or MVP completion. No implementation or historical failed deployment root was changed; no authentication/model/provider call or full CI was performed.

## Exact configuration and supporting bytes

The complete `pyproject.toml` diff changes only `patch = ["subprocess", "fork", "_exit"]` to `patch = ["subprocess", "_exit"]`. `source=["quantos"]`, `branch=true`, `concurrency=["thread", "multiprocessing"]` and `fail_under=85` remain. No omissions, exclusions or path aliases were added.

| File | SHA256 |
| --- | --- |
| `pyproject.toml` | `a243e6038acdfbdf58b3623082e37a516da9c698ac54b53d9d1af38eccfef972` |
| `uv.lock` | `0f5cd349fb32eed64a0cb907242f0ddd333f69efdc77461bdff90602e5bed7ca` |
| `src/quantos/infrastructure/hosted_atomic_probe.py` | `77b506943ccab8edc561ef324457976fdfb8d6d99ad57dbec037977dae62799f` |
| `tests/unit/test_hosted_atomic_probe.py` | `db7fef31603503aa95276ca63e84568835576dce0be65222fa41334407d5c1b8` |
| `tests/conftest.py` | `0e07213a815bab2c9c1fe5f32773d7031810f4d6e4ea6a7fc64d8e208e19d31f` |

The installed local tool versions are coverage.py **7.16.0** and pytest-cov **7.1.0**. The following hashes describe the actual local files inspected; they are not an attestation of a new frozen deployment prefix.

| Local tool file, relative to `.venv/lib/python3.11/site-packages/` | SHA256 |
| --- | --- |
| `coverage/patch.py` | `8ff2e34b1bdf499aedd619ecda2590a1d2a82b5970686740fcc4ddfc54886abf` |
| `coverage/control.py` | `7a69bee219345fa87f6fe561e0940122963f777898ca5d646b461134130b3f91` |
| `coverage/collector.py` | `7b13f8125ec97d5654ccba76f374baed272a9333a2258bf481f0c2e4227b24e1` |
| `coverage/multiproc.py` | `63501e623721f290f865be478e85b9d48573e7278b0d8e7e8a920e3a4f807729` |
| `a1_coverage.pth` | `ef2ed06d19867ec669c09a804060666a9cd5e383af0a9d11aa2de79b77d448e8` |
| `coverage-7.16.0.dist-info/RECORD` | `1f3b0f6c2a194a3ff4ba6c78f7a67aa4edada37329287979f73e6ef4f62b9efd` |

The 205-byte installed `a1_coverage.pth` independently matches its RECORD SHA256/base64 and size entry. It calls `coverage.process_startup` when the coverage startup/configuration variable exists. Both measured configurations resolve `parallel=true`; no manual enablement or replacement startup hook was needed.

## Official behavior and mechanism boundary

The version-matched official documentation describes normal fork inheritance as the usual working behavior; the optional `fork` patch stops and restarts coverage in the child. It also documents `_exit` saving data, `subprocess` enabling automatic measurement and parallel data, and subsequent combination. These are distinct mechanisms; deleting `fork` does not delete the other patches. [Coverage.py 7.16.0 configuration reference](https://coverage.readthedocs.io/en/7.16.0/config.html#run-patch).

The installed implementation confirms that the fork patch registers an `after_in_child` callback which stops the current coverage and invokes `process_startup(force=True)`. `_exit` still saves before exiting. The multiprocessing wrapper independently starts coverage around the child bootstrap and stops/saves on clean completion. Standard process measurement depends on startup and data-saving hooks, and multiprocessing children must finish cleanly. [Coverage.py 7.16.0 managing processes](https://coverage.readthedocs.io/en/7.16.0/subprocess.html).

The independent child records show that with the reset patch, the global trace object changes while the executing frame retains its previous trace object. With inheritance, both retain the previous object. Those identities and the coverage differences below are observations. The explanation that a stopped old tracer remains attached to the already executing fork frame, while newly invoked frames use the replacement, is **an inference consistent with these observations and the inspected implementation**, not an asserted upstream root-cause proof.

## Direct fork and standard worker controls

The final synthetic controls are in `/tmp/hm-coverage-fork-independent-review03`. They use a separately named `coverage_fork_subject` fixture, never a fake `quantos` package. Their deliberately small source denominator is a measurement diagnostic, not the project denominator or qualification evidence. Both configurations keep branch measurement, thread/multiprocessing concurrency, `_exit`, subprocess startup and the 85 threshold; only the reset patch differs, apart from private data paths.

Every run executes a direct fork, multiprocessing workers using both `fork` and `spawn`, a fresh Python subprocess that calls `_exit`, and a thread. Direct-child marker files establish actual inline execution before `_exit`; a function called after fork also executes. Worker markers and per-PID raw coverage shards are separately checked. No model or business engine executes.

| Direct fixture result | Reset patch | Standard inheritance |
| --- | --- | --- |
| Five inline child markers | all executed, all absent from coverage | all executed, all covered |
| Called function after fork | covered | covered |
| Multiprocessing fork and spawn worker markers | covered in each worker's own PID data | covered in each worker's own PID data |
| Subprocess `_exit` marker | covered in its own PID data | covered in its own PID data |
| Thread worker marker | covered | covered |
| Raw shards retained | 8 | 6 |
| Statements covered / valid | 53 / 58 | 58 / 58 |
| Branches covered / valid | 4 / 6 | 5 / 6 |

All native fixture process runs and combines returned zero. XML generation returned zero for this tiny fixture; that is not project CI acceptance. Each group combined only its own new data. Original shard hashes remained unchanged after combination/reporting. Standard `--keep` and `--keep-combined` retain the raw files; no prior root's data was merged.

Paths in the next table are relative to `/tmp/hm-coverage-fork-independent-review03`:

| Evidence | SHA256 |
| --- | --- |
| `fixture/coverage_fork_subject.py` | `d52009c116c33f3a11b809aaa36ae586d339d57b279236faf10047d97b53c370` |
| `fixture/run_subject.py` | `0d7b25dee98baaf599c7a354b80ab22ef88486a6c6d6ab85b72caaa9f5bdc0cc` |
| `run_toy.py` | `77f73f5d0cf31da02895fcfc0cca06c40ae722c92df39f40ddc311c4ed53068c` |
| `toy-comparison.json`, including every original shard hash | `18080636ce458d7b0f079645ae27eedf698fb97f1b7d22189fc0d5616307ba0c` |
| `worker-data-verification.json` | `454b79eb7951f9ede57c700011ba25f6c337864cb201b17e21b4056d4914ca75` |
| `toy-reset/.coverage` | `4767ee00231d23dff0c124d2731d98af48834e3039a6e56724cfcc8fa062d7f7` |
| `toy-reset/coverage.xml` | `fb4465e5202d0599194c4d43a537e4ee77158b34a2bb01b1f04eec6bdc5fca85` |
| `toy-inherit/.coverage` | `e64175e6406c20e15baf8985d31f5e4874d1617de0d159ab183e72bed5b80135` |
| `toy-inherit/coverage.xml` | `ade4c99ea54d38ac54ed5d50ef6e1ceb69ab21dda53779c94467797346c1174d` |

## Independent actual pytest fresh-child comparison

The final native comparison is in `/tmp/hm-coverage-fork-independent-review04`. Each configuration executed exactly:

`tests/unit/test_hosted_atomic_probe.py::test_native_atomic_exit_and_two_fresh_boots_retain_originals[atomic-spec-file_fsynced]`

The existing `fresh_offline_process` hook invokes that node in a fresh interpreter, preserving automatic subprocess coverage startup. The actual fork/fsync/fresh-boot primitive runs through the repository's functional fixture; this is not a deployed scientific/model-source qualification. Required native permissions were used for this bounded component only.

Both private configurations were derived from the exact project file. The reset control adds back only `fork`; both add their own isolated coverage data path. The command retains `--cov=quantos`, `--cov-fail-under=85`, each explicit config, private basetemp, XML and JUnit paths. No `--cov-append`, source omission, path alias or old-data import occurs.

| Actual single-node result | Reset patch | Standard inheritance |
| --- | --- | --- |
| Native test result | 1 passed, 33.89 s | 1 passed, 32.76 s |
| Pytest exit | 1, coverage gate failed | 1, coverage gate failed |
| Project coverage | 27.01% | 27.07% |
| Entire project statements covered / valid | 9,153 / 27,549 | 9,171 / 27,549 |
| Entire project branches covered / valid | 444 / 7,986 | 449 / 7,986 |
| Atomic module statements covered / valid | 84 / 138 | 102 / 138 |
| Atomic module branches covered / valid | 15 / 36 | 20 / 36 |
| Source files in XML | all 171 | all 171 |

The complete `src/quantos/**/*.py` hash inventory and project file match before and after both runs. Each XML's unique file set equals that full source set. Each statement set equals the official source parser's statement set. Every line hit and branch taken/valid count agrees with that run's own combined coverage data after coverage's ordinary physical-to-logical statement-line translation. XML aggregate counts are recomputed from those entries. The two configurations have identical complete statement and branch denominators. This uses source statement translation, **not a file/path alias or cross-root source merge**.

Paths below are relative to `/tmp/hm-coverage-fork-independent-review04`:

| Evidence | SHA256 |
| --- | --- |
| `source-before.json` and identical `source-after.json`, all 171 source hashes | `2617a8da9456382372b77a67fd2b2e694aa7b56d246afe9a44e4e889fee606f7` |
| `run_pytest.py` | `a52e224fa703d07762af8552ab99f4cecfd4a942e9c49973736d8df1104c3a70` |
| `pytest-comparison.json`, complete per-file statement sets and evidence hashes | `17db1e5912e5f2729b1d9fd1eb57a82c8797019c97c9cd64d38d209deca48cf7` |
| `pytest-reset/config.toml` | `38e06d38b737f734febdcc2b0ac64ed0b79add2a9f9e5bc88c82dd70d2f16957` |
| `pytest-reset/.coverage` | `8d9659e770ea75747ebbb06742ab3a1344b7d95cf9acea2e1a54da2518e52ad2` |
| `pytest-reset/coverage.xml` | `e99fcdbadbaae16af10696bf3228f02edb744ec792e6403327fcfc91165c7887` |
| `pytest-reset/junit.xml` | `37454f9d751ceeeb699224083bbe1f7a4f73002889b8488734e75b7587a356f8` |
| `pytest-reset/pytest.txt` | `734f116ab5d49fd00dc5b376f1b89fc9e86bafcc859c30c45bfa7ec3884b7fd4` |
| `pytest-inherit/config.toml` | `f8b8176bd996ee4faadf15ad4569c7463019cef027cdaecaf7494dc6e7ee5ac6` |
| `pytest-inherit/.coverage` | `79aa4181b9380f3acb5e6dfb4072cf5a10865672f8a212b2961e0bddbde207a9` |
| `pytest-inherit/coverage.xml` | `55d96f04cf10d0805522feb85eb1c39b071786a59df7e9a47b983efc268636dc` |
| `pytest-inherit/junit.xml` | `0ccdaaffa24988f8ff0b0e2ad0ad8d4d7e7c5936f1a734683440ae8c0a28fb5f` |
| `pytest-inherit/pytest.txt` | `3fc47f925b3c4a8c527ea8d55767aa70ad1dc34472c14857d0583ce264e2aaf2` |

## Preserved diagnostic limitations and acceptance boundary

The initial `/tmp/hm-coverage-fork-independent-review01` diagnostic assumed that `coverage combine --keep` alone would retain shards through a subsequent XML command. Coverage 7.16's XML command automatically combined/deleted them unless `--keep-combined` was also specified; its original failure log, combined data and XML remain. Review02's toy measurement passed, but reused a marker filename for a later multiprocessing worker; review03 gives the direct fork its own marker and retains the trace observations.

The first native verifier in review02 compared physical raw line numbers directly with logical XML statement numbers and failed on normal multiline-statement translation. That original assertion/log/data/XML remain unchanged. Review04 uses the official file reporter's statement translation and reruns both groups in entirely new roots. These diagnostic corrections do not modify production configuration beyond the already reviewed patch-list change and do not turn failed runs into qualification evidence.

The root agent's previously named `/tmp/hm-fork-coverage-native-reset-unit01.txt`, `/tmp/hm-fork-coverage-no-reset-unit01.txt`, their XML files and historical full-CI roots were read only or left untouched; no data from them enters the independent results.

No blocking defect remains in the tested configuration correction. Standard inheritance works for the measured direct fork, cooperative multiprocessing fork/spawn, inherited-configuration subprocess, `_exit` and thread paths. This is not a guarantee for every abruptly killed child, environment-scrubbed process or disabled Python startup hook. **A new frozen source/install and complete actual offline CI must still achieve ≥85% with the full source denominator and original manager-origin evidence. Both actual native single-node groups here explicitly failed that threshold and remain NOT_QUALIFIED.**
