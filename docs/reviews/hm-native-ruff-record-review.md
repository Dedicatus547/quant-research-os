# Native Ruff freeze independent narrow review

Date: 2026-10-01. Assigned reviewer: gpt-6.1-sol, high effort. Baseline: `5026a64171eb95180ffeffc2f27fd74d397ebc8e`. Outcome: **OPEN: the copied Ruff executable is not bound to the RECORD actually retained in the frozen prefix. Q12/MVP remain NOT_QUALIFIED.**

Scope is the new private `_freeze_ruff_executable` and its call after dependency copying in `freeze_python_install`, plus the new native audit tool unit tests. This reviewer did not edit implementation, execute external/provider/auth/model services, run full CI, alter attempt 23 or any previous failed root, or revise an old review. Source copies and bounded diagnostics are retained in `/tmp/hm-native-ruff-independent-review01`.

## Reviewed source identity

| File | SHA-256 |
| --- | --- |
| `src/quantos/infrastructure/hosted_deployment.py` | `9649ca2ea634a9c7581d260808f9935685919e60021f7a05cdf280c73e72f377` |
| `tests/unit/test_hosted_native_audit_tool.py` | `6a4fd609c60be30caeaf43da90800f5aa828a12284d513d50f581ec3c9120d2e` |
| `src/quantos/artifacts/store.py`, unchanged primitives | `a01b07d546bb6f3ebf24f36a5677f32bd62e77a3723b90ca4095cca4a6055da8` |

## Blocking source-closure finding

The complete freeze first copies `dependency_site` entries into `python_root/lib/python3.11/site-packages`, then the new helper reads Ruff's RECORD from the **original dependency site**. If the original metadata and binary change together between these steps, the helper authenticates the new binary against the new external RECORD while the frozen prefix still contains the previously copied RECORD. `install_inventory` records both files but does not detect their disagreement. The later Q12 tool version is obtained from installed metadata; inventory equality does not independently reconcile the Ruff RECORD with the executable.

The independent full-function control starts with an old RECORD/binary, performs the real dependency `copytree`, and uses a test hook immediately after metadata copying to replace only the original RECORD and binary. It then calls the real `freeze_python_install` to completion with a minimal component wheel and base prefix. The function **returns an install inventory** containing the old frozen RECORD and a new `python/bin/ruff`. The returned inventory hash is `85af4232dae4facbb30fb77ac00942522604036763faa02e97fcf0fcb522b87d`. The old and new executable hashes are respectively `cd5857b1dec5b707e9633e14c62f985ad616b0ad243b9b94d61b130837e28177` and `0ebab4d0fe69f7c3a6c11890415af4f483b45fc080aee832ace54c4f1f927763`.

The control uses small fixed component bytes with the ELF magic and executes neither binary. It demonstrates a deterministic copy/read boundary defect, not an actual attempted provider call or a timing-dependent exploit. A separate direct helper control confirms the same disagreement when a copied prefix already contains the old RECORD. A previously lock-verified dependency installation does not ensure the later external RECORD equals the bytes already retained in the prefix.

Required closure: authenticate the source executable against the unique Ruff metadata/RECORD **already copied into the new Python prefix**, or require exact source/frozen RECORD equivalence before publication. The fixed `../../../bin/ruff` record, full SHA-256, exact encoded size, anchored source read and cap should remain. The control must then reject the changed-source binary rather than return a mismatched inventory. No host CLI fallback, mutable external execution or CI source predicate relaxation is needed.

## Other observations and bounded checks

The new helper's source path derives the dependency prefix's `bin/ruff` from the fixed `lib/python3.11/site-packages` layout. Metadata and source bytes are read through the existing no-follow pinned-directory primitives; the executable must be a single-link regular file. The RECORD cap is 1 MiB and the executable cap is 64 MiB. The helper requires exactly one matching metadata directory and exactly one three-column fixed executable record, canonical URL-safe unpadded SHA-256 encoding, exact decimal byte size and ELF magic. It publishes immutable bytes with the expected full SHA-256 and mode `0500`; no executable or tool subprocess is run during freezing. Absence of optional Ruff metadata returns without adding an external tool. The original install inventory includes the new file and mode on successful freeze.

The independent new unit command passed **7 tests in 1.25 seconds**: positive copy, optional absence, and hash/size/script/duplicate-record/symlink rejection. Failed identity checks do not publish `bin/ruff`. These tests do not cover a copied RECORD/source change and therefore do not close the finding above. No actual new frozen native Ruff execution or complete CI was independently reviewed here. The parent-reported actual attempt 23 `RuffNotFound` logs remain failed provenance; their continued pytest execution cannot retroactively fix Ruff or grant acceptance.

## Evidence hashes

The files below are relative to `/tmp/hm-native-ruff-independent-review01/`.

| Evidence | SHA-256 |
| --- | --- |
| `unit01.txt`, 7 passing bounded tests | `bc31853adddcfd7e3b826cc8e22c29e765f6642a421859dbd18f6658469180a2` |
| `record_binding_probe.py` | `756f3091228f2022070d88f1370a7629f030a1d0c04b9d14bf1c9b757fe444e6` |
| `record-binding.txt` | `34752583d723b8097128817b11072303b5f8bd8df103b5b5cb0ff8d3789b381b` |
| `freeze_record_binding_probe.py` | `6fd0d722aec4a6849cec64f83b8aae4cbf989ae620401266b27ba7d1c7189570` |
| `freeze-record-binding.txt` | `373a6badca775132ea88a30bd19ad0d5531996f78dc1708b3e09cd88b90414ab` |

This report records the initial source bytes and remains OPEN even if a later source revision fixes the defect. Closure requires a new report tied to that revision and new evidence. Complete offline CI with coverage at least 85% and the applicable new exact-source frozen deployment/matrix remain required for Q12/MVP qualification.
