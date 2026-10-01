# Launcher nonzero exit — independent narrow review

Date: 2026-10-01. Reviewer: independent `gpt-6.1-sol`, high reasoning. Baseline `5026a64171eb95180ffeffc2f27fd74d397ebc8e`, with the uncommitted two-line launcher correction.

**CLOSED only for publishing a contract-invalid CAPTURED record after a nonzero process exit. Qualification remains NOT_QUALIFIED.** No live model, authentication source or provider endpoint was used. No implementation, original failed root or original log was modified; no full CI ran. This is not acceptance of HM09, Q09/Q10/Q12 or the MVP.

## Exact source bytes

| File | SHA256 |
| --- | --- |
| `src/quantos/infrastructure/hosted_launcher.py` | `5e836caf93c9c3219411f13efc2c6299737d65ee78625af434853e3226aaef9a` |
| `src/quantos/contracts/hosted_deployment.py` | `d278cc3ad43d92e3dd61fe470bb6c8fcec4816f25bf4bbd8ce52c53d47c80111` |
| `tests/unit/test_hosted_launcher_capture.py` | `ee285c73bbe66d868a6840d9561eff206d54808921f5bb5e9e55a72ff806b3be` |
| `tests/unit/test_hosted_launcher.py` | `21f5ae8be58e8395c02beeeace5367d1fd96a3152c01c5ce3e27a331c6b70323` |

The launcher and new capture-test hashes were observed before the bounded runs and unchanged afterward. The independent diagnostic additionally records unchanged launcher hashes before/after its nine controls. Local source bytes and fixture imports do not attest an installed deployment module or frozen OS prefix.

## Preserved original failure

`/tmp/hm-manager-launcher-capture-unit03.txt` retains **1 failed, 29 passed in 11.92 seconds**. Its nonzero-exit control reached `HostedLauncherRecord` validation with outcome CAPTURED, no proposal and an unsuccessful exit. The contract rejected it with `captured source requires successful exit and proposal`, preventing the intended failure record from being retained.

Earlier fixture failures also remain intact:

| Original log | Result | SHA256 |
| --- | --- | --- |
| `/tmp/hm-manager-launcher-capture-unit03.txt` | 1 failed, 29 passed | `990703df9139bdff1fa6850a588576de5445f07a12a3542d6cddb230bd6cfb29` |
| `/tmp/hm-launcher-capture-unit01.txt` | 8 failed, 3 passed; schema fixture issue | `91868495776749375957eb508f090f47eb25e3d407e93bc323b7100d4658bbe9` |
| `/tmp/hm-launcher-capture-unit02.txt` | 11 failed; projection ordering fixture issue | `fe0bf29852c6546501e17aae5f13001fd8a3f0609b4bf5d521e4b2cbed3355ac` |

These logs are historical failures, not accepted evidence or repaired roots.

## Correction and boundaries

The process primitive's CAPTURED result means its pipes finished; it can accompany a nonzero exit code. The launcher now converts that result to REJECTED when it takes the existing `CLI_PROCESS_NOT_COMPLETED` branch. Successful exit-zero capture still requires extraction of a valid proposal. TIMED_OUT, OUTPUT_LIMIT and existing REJECTED classifications are preserved rather than overwritten by this correction.

The change neither weakens the `HostedLauncherRecord` contract nor manufactures a proposal. Safe captured bytes and diagnostics are still scanned and published before the terminal record; unsafe output still has its existing rejection path. The seccomp filter descriptor is closed in the unchanged capture `finally`. The trusted response-source verifier still requires CAPTURED plus request/profile/configuration/proposal/output bindings and a complete raw capture; a retained rejected record cannot satisfy that predicate.

The correction does not change process deadlines, byte limits, mounts, fixed argv, model identity checks, incoming proposals or authentication handling. This review checks the listed failure paths; it does not certify all process-tree cleanup, prelaunch failure cases or operating-system isolation.

## Independent controls

All diagnostics use the new `/tmp/hm-launcher-nonzero-independent-review01` root. The fixture uses a synthetic install identity and mount observation, real tiny immutable file inventories and functional protocol contracts. No frozen Codex executable or genuine model source was invoked. For native process controls, the fixed process invocation was explicitly replaced with local Python scripts through the actual `_capture_process` primitive; the original prompt/argument composition and fd assertions still ran through the fixture. These substitutions are component controls, not evidence of a deployed launcher or namespace boundary.

Nine independent controls passed:

| Control | Persisted terminal facts |
| --- | --- |
| Native Python success with valid synthetic events | CAPTURED, exit 0, proposal present, complete raw capture |
| Native Python writes valid events and exits 7 | REJECTED / CLI_PROCESS_NOT_COMPLETED, exit 7, no proposal, complete raw capture |
| Native Python writes valid events then exceeds the deadline | TIMED_OUT / CLI_PROCESS_NOT_COMPLETED, exit -9, incomplete raw capture |
| Native Python exceeds the 65,536-byte combined output limit | OUTPUT_LIMIT / CLI_PROCESS_NOT_COMPLETED, exit -9, 65,537 captured bytes, incomplete raw capture |
| Actual missing executable raises OSError | REJECTED / CLI_PROCESS_NOT_COMPLETED, no exit code or proposal |
| Explicit TimeoutExpired exception double | REJECTED / CLI_PROCESS_NOT_COMPLETED, no exit code or proposal |
| Conflicting model identifier | REJECTED / CLI_OUTPUT_UNSAFE_OR_SOURCE_INVALID, no proposal |
| Missing terminal event | REJECTED / CLI_OUTPUT_UNSAFE_OR_SOURCE_INVALID, no proposal |
| Synthetic unsafe output | REJECTED / CLI_OUTPUT_UNSAFE_OR_SOURCE_INVALID, no proposal or unsafe raw/diagnostic hashes |

Every returned record was read back from the evidence store and parsed through the unchanged `HostedLauncherRecord` contract. All passed filter fds were checked closed afterward. For native success/nonzero/timeout/output-limit cases, persisted raw and diagnostic bytes were compared directly with the primitive's actual returned bytes. The unsafe-output control retained only its safe rejected record and prelaunch evidence, without publishing the unsafe body.

The native nonzero record has hash `d7b8ea0938794132d5978fdb9add147f7395012013babb6fe449c8ada0463c37`. Its underlying primitive returned CAPTURED and exit 7; the persisted record is REJECTED, keeps exit 7 and contains no proposal. This directly exercises the repaired mismatch rather than relying solely on a process-result double.

For the launch-error and TimeoutExpired exception paths, the pre-existing implementation synthesizes empty captured streams and leaves `raw_output_complete=true` on the REJECTED record. That observation does not attest a launched process, successful execution or complete provider transcript; the new change does not alter it. In particular, the exception-double control does not prove what a real wait-timeout would have produced before throwing.

The bounded command `.venv/bin/python -m pytest -q tests/unit/test_hosted_launcher_capture.py tests/unit/test_hosted_launcher.py --basetemp /tmp/hm-launcher-nonzero-independent-review01/pytest` completed **22 passed in 13.45 seconds**. Its mount/process fixtures and synthetic memory canaries do not qualify actual model source or isolation.

Evidence paths below are relative to the new diagnostic root:

| Evidence | SHA256 |
| --- | --- |
| `independent.py` | `c399ecf051034e9330c557e96e6d8311e06e568aafeca97a9540352ddfd9982b` |
| `independent.txt` | `660fd1db005f01eb1a908c7029fac316fffc0d1988a65b25b0144d359a2bee50` |
| `independent-result.json` | `32650c77adfbaa24bde923a14d485d92278379f61670c8f78a7b58e8227d7b29` |
| `unit.txt` | `005f99ad575ada60f84af87a516c98db3a371bf800cc89b09fef8c7249b67d60` |

No remaining blocker was found in this nonzero-exit classification correction. New frozen source/install and complete actual manager-origin evidence remain required for formal qualification. No historical failed root gains eligibility from these component results.
