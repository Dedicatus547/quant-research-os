# Scientific authority snapshot cap independent narrow review

Date: 2026-10-01. Assigned model: gpt-6.1-sol; effort: high. Outcome: **the reviewed scientific snapshot cap mismatch is CLOSED for the exact bytes below; qualification remains NOT_QUALIFIED**. No substantive production blocker was found in this narrow change.

Baseline: `c046e37c6618e1f65b025a57924c0fe4b0c5fd93`. The only reviewed production difference is `snapshot_management_authority` in `hosted_management_runtime.py`; the new snapshot tests are also reviewed. The reviewer did not implement changes, commit, invoke authentication/providers/models, run full CI, repair failed roots, or execute another Qlib recovery. Independent diagnostics and source copies are retained under the new `/tmp/hm-scientific-snapshot-independent-review01` root.

## Exact source identity

| File | SHA-256 |
| --- | --- |
| `src/quantos/infrastructure/hosted_management_runtime.py` | `074cd7d493b8aaed7595d926a79dc2c878d7692ebda9c908de19db23bf0ca261` |
| `tests/unit/test_hosted_management_snapshot.py`, corrected exception expectations | `5f9267970a8136db503d2a376ee05e42e7606818744fdad39417e164323d880d` |
| `src/quantos/infrastructure/hosted_verification.py`, unchanged reader/inventory | `ff13dd485c1f5e610f02e171141771665f59b57443a94f5967a3993fa0d851d3` |
| `src/quantos/artifacts/store.py`, unchanged writer/path primitives | `a01b07d546bb6f3ebf24f36a5677f32bd62e77a3723b90ca4095cca4a6055da8` |

## Cap and integrity assessment

The helper initially obtains a real descriptor-anchored `raw_inventory` and directory inventory. The existing inventory rejects non-regular or multiply linked files, unsafe paths, files above **16 GiB**, inventories above **128 GiB** and more than **100,000 files**. Directory closure is separately bounded and includes empty directories. These limits and implementations are unchanged.

The copy now reads each raw authority artifact with `max_bytes=item.size_bytes`, where the size came from that observed inventory. This remains bounded by the scientific-artifact file ceiling and is stricter than giving every read an unrestricted or uniform oversized cap. It does not change `read_relative`'s default **16,777,216-byte typed cap**, protocol/proposal/schema limits, or any research budget. The helper transports opaque authority bytes; it does not award validity to a large incoming JSON contract.

The reader still anchors every component with no-follow directory/file opens, accepts only unique regular files, enforces the supplied byte cap and detects file metadata changes during read. The immutable writer now receives `expected_sha256=item.sha256`, so a smaller or same-sized replacement cannot be published under the earlier inventory binding. The helper additionally rechecks the source inventory after copying, then checks the target inventory and exact source/target directory closure. Added, removed, changed or growing source files therefore cannot become a successful snapshot merely because some copies completed first. Failed copies remain retained.

Independent bounded controls confirmed:

- A **16 GiB + 1** sparse artifact is rejected by `raw_inventory` before the channel/target is created. It occupies zero physical blocks; no 16 GiB byte buffer was allocated.
- Growth beyond the previously observed size is rejected by the reader before publication; a same-sized content replacement is rejected by the writer's expected SHA-256. Neither case publishes the changed file.
- Symlinks, hardlinks and FIFOs are rejected before target creation; no safe-reader behavior was relaxed.
- A zero-byte source copies with its exact zero-size/hash binding.
- The new **16 MiB + 1** copy control preserves the full raw artifact and empty directory, while default typed reads of both source and copy still reject it.
- The after-copy source-mutation control rejects the attempt and retains the previously copied original bytes.

These are transport/integrity controls, not scientific validity or execution qualification. No maximum-sized positive 16 GiB copy or full CI was tested.

## Read-only comparison of the actual scientific artifacts

The independent audit read the existing source at `/tmp/hm-stage-359338d-attempt19/qualification-cases/Q05/execution-prepared/authority` and the separate new forensic copy at `/tmp/hm-scientific-snapshot-native-component01/channel/snapshots/recovered/authority`. It recomputed every raw file SHA-256 and size and the directory closure against the retained source inventory.

Both contain **616 files**, with exact inventory hash `44d59424f34705ad16af85c4122844f530899deaec7504cdcc6ac9b7f03536c9`. Source inventory and directory closure were unchanged before/after the audit. The four artifacts above the typed cap have sizes **29,788,439; 30,002,001; 29,788,439; and 30,229,272 bytes**. Their full logical paths, sizes and hashes are recorded in the independent audit JSON; all four copied bytes match their source bindings.

The original failed `channel/snapshots/recovered/authority` was also read-only checked before/after. It remains **496 files**, with inventory hash `046e4bc11caa7348e40adb788f99558df15e83446e0ed751c28b6574081c2b89`. It was not backfilled, replaced or replayed. The new 616-file copy is component evidence for the cap fix, and explicitly remains `NOT_QUALIFIED`. This audit does not recompute the original recovery's terminal campaign, Qlib call counts or Q05 gate semantics.

## Checks and failed-attempt preservation

The independent snapshot/directory-inventory/qualification component command passed **17 tests in 10.62 seconds** using the corrected test bytes copied to the review root. An independent run of the two snapshot tests passed **2 tests in 2.50 seconds**. The parent corrected-unit log separately reports 2 passes, and the source pyright log reports zero errors/warnings.

The first parent affected-component run remains a failed record: **2 failed, 81 passed in 463.40 seconds**. Its two failures are the initial new tests expecting `ArtifactIntegrityError` for the unchanged reader/inventory's actual `HostedQualificationError`. The initial observed test hash was `2d676b1c95fdb2c462518a28196dfa937cae56db5a0246c367787192999b981e`. Only the expected exception types were corrected; the production helper stayed at hash `074cd7d…`, and neither reader behavior nor exceptions were changed. The old failed log is preserved and is not represented as PASS. The current reviewed test hash is the corrected `5f926797…` above.

No new exact-source frozen installation or full offline CI was reviewed. The pre-CI deployment/driver failures in attempts 20 and 21 remain separate failed attempts; they are not proof of this helper's correctness or Q12 qualification. This helper change requires a new source freeze and deployment, followed by the applicable complete CI and actual matrix evidence. Old CI, previous Q12 code-closure reviews, the old failed recovery, and the separate forensic copy cannot grant new Q05, Q12 or MVP qualification.

## Evidence hashes

The first group is relative to `/tmp/hm-scientific-snapshot-independent-review01/`.

| Evidence | SHA-256 |
| --- | --- |
| `original-components.log` (17 passing corrected-source components) | `3d6148cfa52d7e62cac1dbf01731a3abe1fcbf214d18758945897bcc9d392e7d` |
| `corrected-unit.log` | `00fbb378ce90adcdacd6a210d116394f06436c4e3befbd2520d1cafd9968fceb` |
| `bounds_probe.py` | `c99aa9d0c5b0e3bc49df13cc39582a40c8d71015c7b7f1c6974abccaebf17077` |
| `bounds_probe.log` | `56a483a5a5796c72e5e8c2b283d55ec6e2020f4a5dc838b0ae48e5c6f31e9525` |
| `native_copy_audit.py` | `89f4315e3a5dbddeba0929aaac63cbb8755275e36e46a29a6d7e86ca5bc0048e` |
| `native_copy_audit.log` | `f14a255da26621375e0eb63f431e1e77546e4f50018f90be54037515704fa4e1` |
| `native-copy-audit.json` | `9972a623e127e6d21ac5f1ba1579761900ea391dc3651e8a80f6d8a7a672824e` |
| `/tmp/hm_scientific_snapshot_native_component01.py` | `0787ff856d7cce97fc05079ebc6ba643c5b0a8fa02879187a49b8926b2451ea0` |
| `/tmp/hm-scientific-snapshot-native-component01.log` | `db4532cff5fd71bd5d0552d0f96c29bc51499c189ff3e423d08231e928c35afe` |
| `/tmp/hm-scientific-snapshot-native-component01/component-result.json` | `778335929fc14050ded12bacbf114ad6399cb2c38502a2224853d32c9f712fe5` |
| `/tmp/hm-scientific-snapshot-native-component01/source-inventory.json` | `44d59424f34705ad16af85c4122844f530899deaec7504cdcc6ac9b7f03536c9` |
| `/tmp/hm-scientific-snapshot-components01.txt` (retained 2-failure run) | `2d2cd07313dcb756c8a21f72dd2f22b87c0785c6bf0bec3bcbc0bed6e8158281` |
| `/tmp/hm-scientific-snapshot-type01.txt` | `6d88a1b220adb7a3d62092b6e38431f0b3fe8babe9864fab90e5849766260332` |
| `/tmp/hm-scientific-snapshot-unit03.txt` | `98481a7b87c7df6f2bca031757a6de8d8fbf6d521426106464ef1003ab66309e` |
