# Offline protocol raw binding — independent narrow review

Date: 2026-10-01. Reviewer: independent `gpt-6.1-sol`, high reasoning. Baseline: `5026a64171eb95180ffeffc2f27fd74d397ebc8e`, with the reviewed uncommitted runner change.

**CLOSED, limited to the typed-equality/raw-file omission. Qualification remains NOT_QUALIFIED.** This review does not accept Q09, Q10, HM09, Q12 or the MVP. It does not substitute functional fixture receipts or execution/source-gate doubles for an actual frozen deployment and scientific execution.

## Exact reviewed bytes

| File | SHA256 |
| --- | --- |
| `src/quantos/infrastructure/hosted_offline.py` | `d6b3ced855b0faf580e1f8907318f6f0b92d5ddc85142afceb4271a2f9f9ff99` |
| `src/quantos/infrastructure/hosted_manager.py`, final static read | `feb5ad4d1b447b06473883a637e044d6f8caf342fb1b233b52ac75205414d4be` |
| `src/quantos/infrastructure/hosted_offline_verification.py` | `41b1ea41f0a01b7de82426b62ba21edac84117c694a91d537500b39167940e48` |
| `src/quantos/infrastructure/hosted_replay.py` | `8d9b1fbb61107d15f67e22a17bdd9503b2cbc05599f3bf540c4ba89d7d1e8d48` |
| `src/quantos/infrastructure/hosted_verification.py` | `ff13dd485c1f5e610f02e171141771665f59b57443a94f5967a3993fa0d851d3` |
| `tests/unit/test_hosted_offline_runner.py`, final static read | `8f8499f118e823595c8c485d2872a9355e0ad6b7d72a77a840b090d8801078a7` |
| `tests/conftest.py` | `0e07213a815bab2c9c1fe5f32773d7031810f4d6e4ea6a7fc64d8e208e19d31f` |
| `docs/hosted/hosted-acceptance-v1.md` | `e5877b503259f6e758f22a6feb9307efdc45397155a9229527b2a8ae5dbfc55e` |
| `AGENTS.md` | `a0b0cbbc4ab9615e933b6ceca391b2d6dfaeecfdc9323a6ea561119c9fa114c7` |

The runner hash was unchanged before and after the independent six-control diagnostic and at final verification. The test file changed during the separate unit invocation: its preceding observed hash was `366a4d2689791b2fed68a03e49efafef67b41dcd389669feed2deeae015c8080`. Consequently the unit log below is supplemental component evidence, not an assertion that the final test-file hash identifies every imported test byte. None of these source reads or local fixture imports is installed-module qualification evidence.

The initial manager static read had SHA256 `f0acad5b8cfd3ad82c530cf9ca754aae1d4b318615a9f29b03b75c78045619b5`. Concurrent changes elsewhere in that module hardened JSON decoding; the final diff inspection confirmed its offline source export/copy functions remained unchanged. Those unrelated decoder changes are outside this review's closure claim.

## Original failure and correction

The preserved `/tmp/hm-offline-runner-unit02.txt` reports two failures and 17 passes in 373.31 seconds. Both `protocol-RECEIPT_REUSE` and `protocol-REEXECUTE` failed with **DID NOT RAISE** when the imported protocol had an extra file that the typed snapshot ignored. Its SHA256 is `67c91fbe46013fa3e447f1a1c879792c0af73dfee164198a22be47807ef3aca8`. The earlier `/tmp/hm-offline-runner-unit01.txt` remains intact, including its seven failures and fixture issues; SHA256 `08631663bd8d91737b3df42a0b1a06bd4fa116f19816a68eb553d46e406ccf51`.

The runner now requires both `original_protocol.source == saved.source` and `raw_inventory(model_source / "protocol") == source_before`. `source_before` inventories the actual mode-specific imported root: `/authority/protocol` for receipt reuse, `/authority/saved-protocol` for reexecution. The comparison occurs after checking the explicit whole model-source inventory hash and before trusted response verification, bootstrap or execution. Thus matching typed protocol objects cannot authorize omitted, additional or changed raw files.

The comparison uses the existing sorted, unique `(logical_path, sha256, size_bytes)` file inventory without projection or normalization. Its traversal uses directory descriptors and `O_NOFOLLOW`; file hashing requires a unique regular file and checks read-time identity, size and modification stability. The existing limits remain 100,000 files, 16 GiB per file and 128 GiB total. No reader cap, trusted-source predicate, mode restriction, namespace argument or scientific execution path was relaxed. Raw inventories represent files; this change does not introduce a new empty-directory or filesystem-metadata acceptance requirement.

The existing post-run inventory verification of both imported protocol and whole original source remains. The manager already copies every protocol inventory file for REEXECUTE and verifies the imported copy, while RECEIPT_REUSE uses the original saved authority. The acceptance verifier already requires the exported source protocol's raw inventory to match the original live protocol and binds the mode-specific authority and observation inventories. The runner correction makes the immediate execution boundary enforce the same file closure rather than relying solely on later acceptance rejection.

## Independent controls

All new diagnostics are under `/tmp/hm-offline-protocol-raw-independent-review01`; no failed deployment root or original log was altered.

`independent.py` ran six controls in a fresh interpreter. For each of RECEIPT_REUSE and REEXECUTE:

1. Original model protocol contains an extra raw file absent from the imported protocol: rejected.
2. Both contain the same untyped path with different bytes: rejected.
3. Both contain the same explicitly inventoried extra raw bytes: completed normally with NOT_QUALIFIED observation.

Before each invocation the diagnostic independently asserts typed snapshot equality and that the supplied original model-source hash matches its complete inventory. The four negative controls then require the exact `ArtifactIntegrityError: offline imported protocol differs from original model source`, with no offline observation published. The two positive controls exercise the remaining runner composition and source-inventory postconditions. Scientific execution, business result verification and trusted model-source attestation remain explicit fixture doubles; no model call or transport request occurred.

Evidence:

| Diagnostic | SHA256 |
| --- | --- |
| `independent.py` | `0d0eeffe7509bd2b4526110e1b594576f33ea385d812804a136a71e37ecf369c` |
| `independent.txt` | `8577f1a964d6731c268b8d9a6a8a0af44aff7d1f20d74caf220b699426487168` |
| `independent-result.json` | `3942727c5f7b409ca373b46811d4a0905f87980feaa330b8816511f0306d285a` |
| `unit.txt` | `ab418272a23602e7a169152edd848a80c6e40413bf42e1346a45b2ea6890ba89` |

The separate bounded command `.venv/bin/python -m pytest -q tests/unit/test_hosted_offline_runner.py --basetemp /tmp/hm-offline-protocol-raw-independent-review01/pytest` completed **2 passed in 238.84 seconds**. Its combined scenario test covers both modes and nine damage cases each; the other test rejects arbitrary modes before configuration loading. The fresh-process hook executed the marked composition test in a separate interpreter. The test-byte timing limitation above applies; this result is not qualification evidence.

No further blocking defect was found in this narrow correction. A newly frozen source/install and actual immutable manager-origin offline executions remain necessary for formal Q09/Q10/HM09 acceptance; no old failed root gains eligibility from this review.
