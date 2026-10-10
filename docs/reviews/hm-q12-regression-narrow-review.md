# Q12 regression capture independent narrow review

Date: 2026-10-01. Assigned model: gpt-6.1-sol; effort: high. Review attempt: 1. Outcome for the source bytes below: **OPEN / NOT_QUALIFIED**. Four capture/source defects remain open in those bytes. This report does not award Q12, HM-09, or MVP qualification.

The baseline is `359338d35e880a93f06ff5bcffb005bdd7de5368`. The reviewed implementation consists of uncommitted differences. The reviewer did not modify implementation, use credentials or model services, run full CI, commit changes, or overwrite retained failing evidence. Diagnostics use a new `/tmp/hm-q12-independent-review01` root. The original capture and verifier were copied to its `reviewed-source/` directory before successor edits; their hashes match the table below. A successor must receive its own closure assessment.

## Exact reviewed scope

Frozen criteria: `docs/hosted/hosted-acceptance-v1.md` Q12 and supplemental Q12 require the applicable complete offline repository CI, coverage at least 85%, existing strict/import/contract regressions, and original immutable source evidence. Old CI and component tests cannot qualify a new implementation.

| File | SHA-256 |
| --- | --- |
| `AGENTS.md` | `a0b0cbbc4ab9615e933b6ceca391b2d6dfaeecfdc9323a6ea561119c9fa114c7` |
| `docs/hosted/hosted-acceptance-v1.md` | `e5877b503259f6e758f22a6feb9307efdc45397155a9229527b2a8ae5dbfc55e` |
| `src/quantos/infrastructure/hosted_regression_capture.py` | `da277b3b6b8e73838332bd4c65ce35b3335fc63e998eef433c969f66d4c73a26` |
| `src/quantos/infrastructure/hosted_regression_verification.py` | `3938f5f5c5646c04d7bf7a85cfeedb18a15dbc049215ce692b97d6c00b19a3ea` |
| `src/quantos/infrastructure/hosted_verification.py` | `ff13dd485c1f5e610f02e171141771665f59b57443a94f5967a3993fa0d851d3` |
| `tests/conftest.py` | `0e07213a815bab2c9c1fe5f32773d7031810f4d6e4ea6a7fc64d8e208e19d31f` |
| `tests/unit/test_hosted_regression_capture.py` | `b23df2d037b1cf66ee4bba0cd36635cb1549261907035ea2c1612698524bd198` |
| `tests/unit/test_hosted_regression_verification.py` | `69a7923e82915c5e595205ff80254ad87f82b63ee7eb88c6b9ce4f280893e5bd` |
| `tests/unit/test_hosted_regression_origin.py` | `b62be6d5a9636b19aefc859166253ac2d1b6cbebc8d43eec7da99d2365dfaaf6` |
| `tests/integration/test_hosted_lifecycle_e2e.py` | `05787a4c1a81b62f70deb48dcabbe9412f54baf431576d748628b2d849037cbb` |
| `tests/unit/test_hosted_atomic_probe.py` | `3506c1c19a4dd61d2fe6f1af2c2f7d005a17443c85599d77ca2c4502671b9bbe` |
| `tests/unit/test_hosted_duplicate_probe.py` | `61f420d0d8d0cfcaf6e6a84ddb9512d366d7a54d9c651b3002ffdee427bb55cb` |
| `tests/unit/test_hosted_fault_probe.py` | `131ec57703a6e1b19bf9c7ecb9ebb838a70f24a630a16d6fedcc5296ff8a6001` |
| `tests/unit/test_hosted_lifecycle_probe.py` | `a16ef98ce0c74e91ce7e4ddac1e86b6588af4fb2471256762536917fe593357c` |
| `pyproject.toml` | `0243ff6735d14024305476e70ca099710e1537218df7dd1e96cee3a97bd620fd` |

## OPEN P1: default pyright transport is not offline

`run_managed_regression` lines 152–160 supplies a minimal environment but does not disable pyright's update check, and `_check` launches without a kernel network boundary. The installed locked pyright's `_utils.install_pyright` calls `_should_warn_version`, which defaults to `utils.get_latest_version`; that function attempts HTTPS to `https://pypi.org/pypi/pyright/json`, even when bundled pyright is available. The absence of credentials and pytest's socket plugin do not block this separate pyright process.

The reviewer invoked this existing startup path in a child with the capture's fixed environment. A replacement transport recorded the attempted URL and raised before any actual network access. Output confirmed the URL and `bundled_pyright_exists=true`. The diagnostic did not execute a model or send an external request.

Minimum closure: disable version discovery explicitly, use frozen bundled tool bytes, and establish and record a real kernel network denial for every fixed CI command and its descendants. The verifier must require that captured isolation identity rather than accept the environment-policy label alone. Keep a native network-denial negative and an attempted-update control.

## OPEN P1: Node runtime escapes the frozen installation

The same fixed environment resolves pyright's Node through its `nodeenv` fallback. This machine has no Node at `/usr/bin/node` or `/bin/node`; its fallback chooses `/home/zjw/.cache/pyright-python/nodeenv/bin/node`. That executable is outside the deployment install and outside `SYSTEM_RUNTIME_PATHS`. The verifier checks the pyright package version and frozen METADATA, but neither captures nor verifies the Node bytes actually executing pyright. A missing user cache also permits an attempted download through nodeenv.

The independent diagnostic returned `node_strategy=nodeenv` and that exact external cache path without installing or running Node. Minimum closure: freeze the Node executable and its required runtime, bind its actual path and digest to the installation inventory, reject external/cache fallback before launch, and verify those bindings from original records. A package version alone does not close this source gap.

## OPEN P1: matching Python bytes do not bind the executing prefix

Capture lines 118–122 compare the current Python binary hash and capture-module hash to the install manifest, but do not require `sys.executable`, the effective Python prefix, or the capture module's actual path to belong to the frozen prefix. Verifier lines 225–249 accept any absolute recorded Python path with the expected binary hash. The recorded package versions and inspection of frozen METADATA do not establish that those frozen dependency files were the ones imported by the actual interpreter.

A copied identical Python binary can run from another prefix with mutable dependencies; an unchanged capture file can be loaded from that other runtime. The existing source fixture already supplies an external `.venv/bin/python` with a matching binary hash. An independent invocation of the saved original predicate confirmed `synthetic_predicate_accepted=true` and `python_outside_frozen_install=true`. This is a synthetic predicate counterexample, not a claim that a complete source-bound qualification bundle passed.

Minimum closure: bind the actual interpreter path and effective prefix, capture module path, and tool import roots to the frozen installation; verify the fixed original paths mechanically. If an independently installed management interpreter is intended, freeze and bind that complete prefix and its dependencies explicitly. Include a rejection test for an identical executable copied to an external mutable prefix.

## OPEN P2: EOF bypasses the configured deadline and loses failure output

`_check` lines 91–102 leaves its deadline loop when stdout reaches EOF and calls `process.wait(timeout=10)` independently of the configured deadline. A child can close its output descriptors while continuing execution. This permits a child that outlives the configured timeout to return code 0 and `failure=null`. If it continues beyond the separate ten-second wait, `TimeoutExpired` escapes instead of returning the already captured output and an exit observation. `run_managed_regression` only writes `<name>.txt` and `<name>-exit.json` after `_check` returns, so the failing command's original bytes remain only in RAM and no final run record is written.

Two native controls used disposable children, each printing `original-output`, closing descriptors 1 and 2, then sleeping. With `timeout=0.2`, sleep 1 returned success after 1.046 seconds and retained the output; sleep 20 raised `TimeoutExpired` after 10.028 seconds with `exception_output=null` and no captured tuple returned. Both children were cleaned up by the original function. The initial shorter startup-sensitive control timed out normally and is retained separately; it is not the EOF counterexample.

Minimum closure: keep waiting for native completion after EOF using the remaining original deadline, kill/reap on every timeout, and return a bounded failure observation with the retained raw prefix for publication. Do not invent successful completion when observation is unavailable. Native EOF controls must exercise both over-deadline completion and the former escaping-wait path.

## Checks, retention, and acceptance boundaries

The fixed pytest argv contains the complete suite with no `-k`, path selection, or coverage override. The verifier recomputes combined line/branch coverage, checks totals against individual observations, requires all installed project source filenames, checks every JUnit testcase, and rejects failures/errors/skips. It binds the fixed logs, prelaunch/exit records, tracked inventories, runtime identity, and before/after authority snapshots to original manager export paths. Export and relative reads use the existing anchored regular-single-link path checks. Manager evidence directories are created with mode 0700, and published manager JSON/text uses the existing immutable writer; XML and test work files remain under that protected management root. No permission relaxation was added in the reviewed diff. Actual full-run retention and later export acceptability have not been exercised against a new frozen install.

The fresh-process marker hook runs the exact marked node in a new interpreter and keeps the existing native SDK/network rejection checks. Its marker additions are confined to the five requested probe/integration files. Coverage subprocess support remains configured. This addresses inherited SDK imports in collection, but the selective native run cannot replace full CI or source-bound Q12 evidence.

The reviewer independently ran the three requested regression test files: **67 passed in 23.57 seconds**. This was a component command without coverage, not a Q12 run. The parent logs independently inspected here report 41 component passes, 26 source-fixture passes, and 76 passes in a broader combined command. The fresh-probe log reports 27 passing tests but **coverage 29.55%, below 85%, with a failed coverage gate**. It remains failed evidence. The old baseline full-CI process and its retained failures are not reinterpreted as new implementation acceptance.

There is no new frozen-install, complete-CI original `run.json`/manager export qualifying these implementation bytes. The code retains `qualification_eligibility=NOT_QUALIFIED`, and this review keeps Q12 unawarded. None of the synthetic authority/source fixtures proves an actual deployment or changes campaign/validation authority.

## Independent evidence hashes

All names in the first group are relative to `/tmp/hm-q12-independent-review01/`.

| Evidence | SHA-256 |
| --- | --- |
| `components.log` | `47f6fedf7fa6c781cf786036108063549179519c80e1c95265941b591d040a12` |
| `offline_tool_probe.py` | `838b877dd024d2c0992b48a039c5b05899acdfea4b57ca04ce4ba608c5ef81cd` |
| `offline_tool_probe.log` | `798c336a406ca8ba4297ba3a5f0b8d2a4d56361b84f73eace7d5ba9b5c6011f5` |
| `python_origin_probe.py` | `a2e07803ce509951fc854dab95782df92a82dfe5326532d3a9b77264aa86c159` |
| `python_origin_probe.log` | `8f813ac75ce3665e05d22de2fa2b7311c416f9b59af6c4d97239486ca7019317` |
| `eof_timeout_probe.py` | `ddc9e553ba7aa5ac9668f43e38e533abafa59a0b59b571c121a09623d5dd6654` |
| `eof_timeout_probe.log` | `651fb82a16aaadcb4772c4b985921ecde852877e2af723765ebbe9bd4196937f` |
| `retention_probe.py` | `54cd209d89f8a08bc1873a9448c5be76082251d21f705a1142f8d0d0f22cd28b` |
| `retention_probe.log` | `a55ca6cc80908d0eadeb8bd886731eb33210a9d47152354506d16b81e35dd4b5` |
| `/tmp/hm-q12-regression-components01.txt` | `ca176a20756611c5944ed0df6b8f80b233a68f1b95c8ac2b6f50d633e26fcd73` |
| `/tmp/hm-q12-source-components01.txt` | `ff3c4176b9bdba104887669eb4a1cea318f016f71df60c5d692f2bdfe3d80001` |
| `/tmp/hm-q12-regression-components02.txt` | `f958bf99401c6a5250f489c05d03f1cb67350e11a4e35d20738bb7457683d099` |
| `/tmp/hm-q12-fresh-probe-regression02.txt` | `ade735eb06322ec797048606476f97acace467cf3d7c8fd9c7dc3fe8dc15618d` |
