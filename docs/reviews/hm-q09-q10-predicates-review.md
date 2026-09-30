# HM Q09/Q10 native replay predicates — independent narrow implementation review

Review date: 2026-09-30. Status: **NARROW_IMPLEMENTATION_REVIEW_NO_OPEN_P1 / NOT_QUALIFIED**.

This successor records an independent implementation review, including findings corrected during the review. It does not accept HM07, HM09, the full hosted matrix, or the MVP. No implementation, frozen contract, acceptance document, earlier review, credential, or authority artifact was modified by this reviewer. Only this new review document was added; no commit or push was made.

The explicitly requested development-review model/effort override is `gpt-6.1-sol / high`. Observed model usage and token accounting are unavailable; no usage values were invented. This development-review override does not change the frozen research model profile `gpt-6-sol / high`.

## Reviewed revision and scope

Exact HEAD was `9ae5537dcb06cb2f9c6cd1caf85b8b65fa9f8022`. The implementation reviewed is the working tree over that HEAD, including new, untracked files. HEAD alone does not identify this implementation. The source hashes below identify the final reviewed bytes after the fixes described here.

| File | SHA-256 |
| --- | --- |
| `src/quantos/infrastructure/hosted_replay_verification.py` | `d964e5978ac959c8769050cb596f0909ef2274b326aeec3824fa25fa99b703c3` |
| `src/quantos/infrastructure/hosted_replay_evidence.py` | `96b9c912ae694c3d2dac9ffcf6b2967daa90a6fcd2ca9d8e3a6de61186ae0ca5` |
| `src/quantos/infrastructure/hosted_business_verification.py` | `930a97c9f603387609f5004353e596a9fc82eddb84d94749b7a1acf04dad9eed` |
| `src/quantos/infrastructure/hosted_verification.py` | `30bfb4f8c7d402f79df6ef36ef2e70240f1ad8122c8fa5ce22cb41199f0e2c83` |
| `src/quantos/infrastructure/hosted_offline_verification.py` | `3e6a7dc0932043db99a461c6601eecfd18396e966f5af1a928339236471be5bc` |
| `src/quantos/infrastructure/hosted_qualification_sources.py` | `a994d871288204458ed0ad2b5ca1c12bdd00609bd6c6f4709c51f140b007642b` |
| `src/quantos/infrastructure/hosted_offline.py` | `f23a696c3bac1c8508a12aed251e58ccd7e1aff1a6e595c986936fb17f7e7e18` |
| `src/quantos/infrastructure/hosted_manager.py` | `c78820a82685b95e50f77163b98371a767a8993dc951bfb4276f27f4404a2d5c` |
| `tests/integration/test_hosted_business_e2e.py` | `c6611249c6626603ca7a6f8e2114d58747142cf943f972e27cd26e311a372549` |
| `tests/unit/test_hosted_principal_comparison.py` | `1b1390d32b249ff0109c969dc5aba33f3603d54736462e3cf1a6f5b3a5826802` |
| `tests/unit/test_hosted_offline_verification.py` | `debcc37ce2eb482420d91a7dcf0019cf23c5738c41501cb170ed1523405209db` |
| `tests/unit/test_hosted_offline_origin.py` | `4354192aee42d7f89b424c970819a9355ec094d892bc57f555c1216a88394806` |

The narrow scope is Q09/Q10 source binding, actual native authority consumption, approved C11 path derivation, complete inventories, manager captures, and corresponding tests. The dispatch additions in `verify_case` were checked. Existing Q01/Q11 implementation and unfinished other gates are not granted a new acceptance by this review. Other dirty files, including live driver/request-export changes, belong to their separate reviews.

Frozen files remain unchanged:

| Frozen file | SHA-256 |
| --- | --- |
| `docs/hosted/hosted-contract-v1.md` | `14704b9cbbe0f0ca281751833bc08248820da0c277a281a140bfd12bc6b102df` |
| `docs/hosted/hosted-acceptance-v1.md` | `e5877b503259f6e758f22a6feb9307efdc45397155a9229527b2a8ae5dbfc55e` |
| `docs/hosted/hm02-freeze-manifest.json` | `ac5a4c5e01e8c064906342607ff2ef9f3e9e9b98429188689e6873f76b2ee52e` |
| `docs/reviews/hm02-deployment-bindings-review.md` | `784b573fe47c4e5838a74d2ce39bbb420c707ca39d8d4743610ff55ac3782381` |

## Findings and corrections

### Closed P1: global reference hashes did not identify native authority paths

The initial `c11_business_projection_paths` scanned manifests and combined a global set of references from all candidate reports with all execution identities and frozen variant names. It also used `removeprefix("sha256-")` without requiring that prefix. A valid referenced manifest copied under a directory lacking the prefix, another completed candidate, or an unrelated allowed variant could acquire timestamp-projection permission. Schema validity and a referenced digest somewhere in the campaign did not establish that path's authority.

The corrected implementation derives each exact path from a completed saved step, its exact execution outcome, and its corresponding already-verified ValidationReport. It binds baseline signal/backtest kinds and hashes separately; reproduction uses the actual native `executions/<identity>/reproduction/sha256-<hash>/manifest.json` layout. Cost, parameter and subperiod cases must match frozen policy identifiers, and case evidence kinds determine signal/backtest directories. A parameter case reusing the baseline references does not invent a second authority directory. Result manifests derive from the exact outcome's research-result hash.

It no longer searches arbitrary manifests for authorization or borrows references across candidates. The final function also no longer intersects required paths with existing files: a missing referenced native artifact fails instead of silently losing its projection entry. Three native negative cases copy a real valid signal manifest to the prefix-free, wrong-candidate, and wrong-cost-variant paths, vary only top-level creation time between roots, and require comparison rejection. Unknown extra files remain principal bytes.

### Closed P1: an allowed path did not bind its manifest's own content hash

The earlier projection helper validated the manifest's embedded self-hash but, except for Ledger snapshots, did not bind that hash to the content-addressed directory. The reviewer independently reproduced a comparator-level counterexample using a real native cost signal manifest with content hash `f58c5594a953ba22206bd8dfbafd2e75bc97af5be5d14e0b072cacdefa492504`: two canonical copies at an explicitly allowed `sha256-ffff.../manifest.json` path differed only in top-level creation time, and the comparison emitted one projection. This was a narrow comparator counterexample, not a claimed bypass of the complete original-manager export boundary.

The final public pure helper, `c11_manifest_projection`, requires every non-Ledger manifest's basename to be `manifest.json` and its parent to be exactly `sha256-<parsed content_hash>`. Ledger snapshots retain the existing `sha256-<content_hash>.json` filename check. The independent same-shape counterexample now rejects with `C11 manifest directory/content binding is absent`.

### Closed P1: report references alone did not verify all applicable native sidecars

`verify_validation_report` verifies the report and its own contract sidecars. The native receipt verifier already checked the actual ResearchResult and baseline backtest, but those checks alone did not read every cost/parameter/subperiod/reproduction artifact named by the report. A valid report reference string must not substitute for reading those artifacts.

The final `verify_hosted_business_root` invokes the exact path derivation before returning facts. That function parses each required authority manifest with the path/content binding above and reuses existing `verify_signal_artifact` and `verify_backtest_artifact` for signal/backtest/reproduction directories. These native readers verify file sets, file hashes, typed payloads and internal bindings; no new backtest or accounting engine was added. Raw authority inventory is rechecked after these reads.

The native test places another candidate/baseline's self-consistent manifest at a legitimate cost manifest path and requires directory/content rejection. It separately corrupts a real cost `portfolio.parquet` and requires bottom-up native rejection, then restores original bytes and rechecks the original full inventory. Both cases passed independently in the final regression.

## Q10 boundary assessment

The new Q10 predicate requires two separately mapped original roots. Each root is verified against the frozen business inputs and deployment, and its complete raw inventory remains binding. The original manager export is supplied through an independently selected external manager root; uploaded producer labels, copied PASS records, and model-origin strings are not the source proof. `verify_original_live_source` verifies the original request/response/exchange/protocol and direct launcher captures, and Q10 requires those original hashes to be included in the export.

`verify_offline_manager_run` binds each completion to a retained prelaunch record and its hash, original authority/source roots, exact argv, frozen installed offline program hash, successful integer return code, before/after inventories and actual offline observation hash. A REEXECUTE target's before inventory must equal the complete saved source protocol inventory with the fixed `saved-protocol/` prefix. Merely having files under that prefix is insufficient; old results or a partial imported protocol cannot satisfy it. It also rejects reuse of the original live root. Source protocol bytes must equal the original live protocol, and source inventory must remain exact.

The expected namespace command fixes the seeded isolated executable, offline module, mode, profile, source inventory hash, private staged descriptor and network-isolated service mounts. Observations bind the actual report, numeric thread environment, seed environment and Python initialization flags. Both execute and Qlib Workflow calls must equal the verified execution denominator without repeats. Original manager-captured fixed program execution is required before these counters have authority.

`principal_business_inventory` derives the partition itself. Only the exact offline observation and Qlib MLflow runtime directory beneath a verified execution identity are separated as runtime. Every other file, including additions, remains principal. `compare_verified_principal_roots` first verifies both complete raw roots, checks that supplied principal file metadata is an exact subset, compares the complete principal path sets, and permits only explicitly authorized paths to differ. C11 parses only the frozen seven schemas, requires complete canonical `model_dump` serialization, and removes only top-level `created_at`. Nested dates, unknown schemas, payload values and other authority bytes remain exact.

The Q10 comparison observation must equal the verifier's complete reconstructed dictionary, including both original root names, complete raw/principal/runtime inventories and every actual projection's path, schema, both raw hashes and projected hash. The producer cannot omit a runtime difference or supply an arbitrary smaller principal subset. The older unrestricted `compare_principal_roots` helper is used by the component test, not by the Q10 qualification dispatch.

## Q09 boundary assessment

Q09 requires the original live receipt authority and an original manager-invoked RECEIPT_REUSE run. The retained before/after inventories must match except for the explicit offline observation. Both native call lists must be empty. The fixed offline program additionally forbids invoking native execution/Workflow during reuse, blocks socket connect paths, executes under the network-isolated namespace, and rejects forbidden transport imports.

The baseline is fully verified before tamper outcomes are considered. Five separate altered roots must retain the same complete file set and change exactly one claimed original file. The original object must have the frozen request, response, native receipt, ResearchResult or event schema; the altered bytes must be precisely its canonical fixed invalid-schema mutation. The altered raw inventory is recomputed and accepted as the altered inventory before semantic verification, so failure is not merely an obsolete inventory hash mismatch.

`verify_tamper_case` runs the actual bottom-up business reader over each altered root. In particular, the receipt target is the identity receipt consumed by native recovery, rather than an unused secondary receipt copy. Request/response objects are consumed through the saved protocol and exchange bindings; the ResearchResult manifest and campaign event are read through their native authority paths. A mutation of an unused copy would not yield the required semantic rejection and would fail the case. Each reproduced exception class must match the recorded observation, with exactly the five frozen kinds in order. Every altered root is mapped to original manager files, and the complete original baseline is rechecked.

Management capture helpers preserve comparison facts and five distinct tampered copies without overwriting live authority. Copying the baseline into negative tamper roots is appropriate to Q09 and is not evidence of Q10 reexecution. Capture helpers always record `NOT_QUALIFIED`; their generated records still require original source and actual invocation checks in the qualification predicates.

## Independent validation and retained failure facts

The reviewer ran the following checks directly, with no model/provider credentials and no network acquisition:

- Before the final additional sidecar fix: principal/business/offline units, **39 passed / 5.90 seconds**; original-manager metadata units, **34 passed / 6.65 seconds**; actual synthetic Qlib native integration, **1 passed / 121.03 seconds**.
- After the final path/content and sidecar fix: principal/business/offline/original-manager metadata units, **73 passed / 7.77 seconds**; actual synthetic Qlib native integration, **1 passed / 123.51 seconds**.
- Independent comparator counterexample before the fix accepted one wrong-directory projection; repeating its shape after the fix rejected it as documented above.

The final native test performs two separate saved-protocol reexecutions, checks two completed native calls per root, verifies the original protocol inventory remains unchanged, compares complete native inventories with approved projections, exercises the three valid-manifest copied-path negatives, executes all five authoritative typed mutations, and generates/rechecks management comparison and tamper observations. It also covers the legitimate cost path's wrong self-consistent manifest and corrupt native portfolio sidecar. Synthetic source observations explicitly declare `SYNTHETIC_COMPONENT_TEST`; actual Qlib execution does not make them actual model output or qualified launcher provenance.

Both independent native runs reported 232 warnings: 231 Qlib empty-slice runtime warnings and one blocked `socket.getaddrinfo` warning from the test network guard. They were successful test runs, not successful real Q09/Q10 qualification runs. The warning is not presented as proof of a fully observed production transport boundary.

The initial developer regression log `/tmp/hm-q09-q10-native-regression.txt` remains a failed run: the initial reproduction path authorization had one extra directory level. The log was inspected and was not overwritten by the reviewer. Its named ephemeral `pytest-329` fixture directory is no longer present after pytest directory rotation; it must not be described as a retained qualification authority root. The subsequent developer logs `/tmp/hm-q09-q10-native-regression02.txt` and `/tmp/hm-q09-q10-unit-regression02.txt` were inspected, reporting 1 pass / 94.63 seconds and 60 passes / 16.52 seconds respectively. Later developer test results were communicated separately; the independent results above are the reviewer's evidence.

## Remaining qualification limits

No open P1 was found in the final narrow implementation identified by the hashes above. This conclusion closes the implementation findings described here and does not establish production readiness or all-gate acceptance.

Actual Q09/Q10 gate evaluation still needs immutable, complete real live model/launcher captures, original saved authority, the fixed installed native process and manager prelaunch/completion records, both real fresh roots, the actual full raw/runtime/projection records, and the five retained tamper roots exported from the independently selected original manager. These component and metadata tests cannot provide that origin. A newly frozen deployment/profile must contain the final reviewed implementation; the older attempt06 installation cannot attest working-tree additions.

Other matrix gates and the overall HM07/HM09 acceptance remain outside this narrow result. No profitability criterion, new research engine, relaxed original protocol, post-launch seed workaround, runtime omission or additional timestamp exemption was approved. **NOT_QUALIFIED remains the result.**
