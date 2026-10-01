# Native Ruff frozen RECORD independent closure review

Date: 2026-10-01. Assigned reviewer: gpt-6.1-sol, high effort. Baseline: `5026a64171eb95180ffeffc2f27fd74d397ebc8e`. Outcome: **the reviewed missing-native-Ruff freeze fix and copied-RECORD source-closure defect are CLOSED for the exact bytes below. Q12/MVP remain NOT_QUALIFIED.** No further substantive blocker was found in this narrow source change.

This is a new report. The initial [OPEN report](hm-native-ruff-record-review.md), SHA-256 `ff3e101d43e5c0a4adf21e7ba17ea3dcc8a1a0976ed70cb5d63fd73a039ec3b0`, remains unchanged and OPEN for its original source bytes. Independent new evidence and reviewed source copies are retained in `/tmp/hm-native-ruff-independent-review02`. The reviewer did not implement changes, commit, inspect credentials, call providers/auth/model services, run full CI, modify any failed installation/root, or overwrite previous reports or diagnostics.

## Exact source identity

| File | SHA-256 |
| --- | --- |
| `src/quantos/infrastructure/hosted_deployment.py` | `10efdfab9904fb5e0ba9071b79e1235019c9e7bd8e8bf6fd476c180fb324c9a4` |
| `tests/unit/test_hosted_native_audit_tool.py` | `f30f7df5f508be66602b0e6383318fdeb3ea84b6530bef8d75bcc6adc22c0c1d` |
| `src/quantos/artifacts/store.py`, unchanged anchored read/immutable writer | `a01b07d546bb6f3ebf24f36a5677f32bd62e77a3723b90ca4095cca4a6055da8` |

The production diff adds only CSV parsing support, the private `_freeze_ruff_executable` helper and its invocation after dependency copying. The helper now enumerates and reads the Ruff metadata/RECORD **inside the already-copied Python prefix**. The fixed source executable is still read from the dependency installation's `bin/ruff` through pinned directory descriptors; no external binary is executed during freezing.

## Closure and retained boundaries

The copied prefix must contain exactly one Ruff metadata directory and exactly one three-column `../../../bin/ruff` RECORD row. The executable must be a unique regular non-symlink file, within the 64 MiB cap, with ELF magic, exact full SHA-256 encoded as canonical unpadded URL-safe base64, and exact decimal byte size matching that frozen row. RECORD reading remains capped at 1 MiB. Validation completes before immutable publication; the copied native executable receives mode `0500`. The final existing install inventory includes both the retained RECORD and executable hash/mode.

Reading the frozen RECORD closes the original copy/read boundary: a later change to external metadata cannot redefine which native bytes the frozen prefix accepts. The independent complete `freeze_python_install` control repeats the original counterexample in a new root: immediately after real Ruff metadata copying, a test hook changes both the original RECORD and original binary. The corrected function now raises `ArtifactIntegrityError`; the copied old RECORD remains, `python/bin/ruff` is absent, the QuantOS wheel has not yet been extracted, and no final install inventory is returned. The new unit control independently requires the entire copied-prefix raw inventory to remain unchanged after the private helper rejects this condition.

The helper still does not add Ruff when copied optional Ruff metadata is absent. It does not invoke a shell, dependency resolver, acquisition layer, mutable host CLI fallback or provider. Existing Python-prefix freezing, dependency hook exclusions, wheel checks, Q12 prefix derivation, isolated manager flags, native namespace execution, runtime/source predicates and coverage requirements are unchanged. This fix adds the missing wheel-bound native file to the frozen installation; it does not relax those boundaries.

## Independent evidence

The reviewed unit command passed **8 tests in 1.26 seconds**: matching native copy, optional absence, hash/size/script/duplicate-record/symlink rejection and the after-copy external RECORD/binary replacement. The complete-function source-change control also rejected the original counterexample.

Ten additional bounded controls rejected source hardlinks, a source FIFO, a symlinked source `bin` directory, hardlinked/symlinked frozen RECORD, duplicate metadata directories, a RECORD larger than 1 MiB, a source executable larger than 64 MiB, absence of the fixed RECORD path and a four-column RECORD. Every rejection left the native target file absent. The two oversize controls use sparse files; no oversized positive buffer or binary execution was attempted.

A separate independent positive component copied the actual local Ruff metadata and invoked the corrected helper against the actual installed ELF. It then executed **only the new private native file's `--version`**, which returned code 0 and `ruff 0.16.5`. Source and copied binary SHA-256 were both `024cdfbba8627539cc951908267077e3fd8e710add19f0b31d6cc606d19ddc32`. The private component prefix inventory, `cbba336da06c89895f6860764b50247e6ce2d0bcf4085f09ea660886df9ba293`, was identical before and after execution, and the original binary hash remained unchanged. This minimal prefix contains copied metadata/native bytes; it is **not** a complete production Python installation, an actual `-m ruff` Q12 command or a qualified deployment.

The parent's separate 30-test component result and zero-error source pyright result are supporting checks. Its native component 01 imported the original helper before the closure fix; a source hash read at completion cannot attest the previously executed helper bytes. Native component 02 reads its implementation hash after import and before the copy call, then checks it at the end; that establishes source-file stability over that interval, not pre-import or executed-module attestation. This closure does not rely on either component to grant source identity or qualification. Their original records/roots must remain separate rather than be rewritten as new-source evidence.

## Evidence hashes

Files below are relative to `/tmp/hm-native-ruff-independent-review02/`.

| Evidence | SHA-256 |
| --- | --- |
| `unit01.txt` | `68991cb760f5c6dc118a224faeef0ace5ba33af6d181035e6cc27d53671fe609` |
| `freeze_record_binding_probe.py` | `a41a8598cd261f11746e9f692222935e897f98c2b6cb5a0a9c0ac369e618384c` |
| `freeze-record-binding.txt` | `2801a673238cd516592fb213035119fe424a4e328e4d22b03aeecc56fabf9261` |
| `alias_caps_probe.py` | `3091c017ebe1bb7d04742cdd4ef929b8c84939f97d884a915948baf968f9da67` |
| `alias-caps.txt` | `029280ddfad202171cb5c745773352e71b0a7fe3963572949a890045e1cf75c6` |
| `native_copy_probe.py` | `b8f96095413a8a2944afae49230a065d12a497f8199695d36380f05dc6573324` |
| `native-copy.txt` | `18c096b9cfa68e2d832a38cd4b83bfe96bdba1d2f64e71aa8dbfbe5f8dc63a70` |

Attempt 23's original Ruff failures remain failures. Its continuing complete pytest/coverage capture is separate diagnostic evidence and cannot retroactively qualify failed Ruff checks or this later source revision. A new exact-source freeze and D, actual frozen-prefix Q12 commands, complete offline CI with coverage at least 85%, and the applicable native acceptance matrix remain necessary. This limited code closure grants no Q12 or MVP acceptance.
