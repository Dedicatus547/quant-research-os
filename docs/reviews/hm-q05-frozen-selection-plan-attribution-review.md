# Frozen selection-plan attribution and offline Q06 narrow review

Assigned model: gpt-6.1-sol; effort: high; independent attempt: 1; observed usage: unavailable. No P1 identified in these two bounded successor changes. **NOT_QUALIFIED**: this review does not grant Q05, Q06, Q11, HM09 or overall deployment acceptance.

## Source identity

Baseline HEAD: `77c129f11e9fc65f76a64fa978cc6d06e9164554`, with uncommitted successor differences. Copies and the exact two-file diff are preserved in `/tmp/hm-frozen-plan-attribution-review-source`.

| Artifact | SHA-256 |
| --- | --- |
| hosted_business_file_closure.py | 4771e2842ec44c8997cd97831b31558754909e974d5ff8c0beaf696208dabc40 |
| hosted_business_verification.py | 945d492ba732e9e798896595b4d6881628677d055ff2a9a7c284cd4b1c0ca17a |
| bounded review.diff | 257af74121e8fe5bb27fb781f9ebf456d157905b085d62705f50674de6cacff3 |
| reused hosted_campaign.py report helpers | cd4de6187d14d08d8b472e7c840102240833d5f87f22b0a1930e31dcdde53a37 |

No implementation, frozen worktree, installed code, historical authority, authentication or provider/model was changed or invoked. Only this requested new review document was written in the repository.

## Selection-plan attribution

The addition authorizes exactly `business/<bound-campaign>/selection-plans/sha256-<bundle.selection_plan.content_hash>/plan.json` when that file exists. Its expected hash and size come from the frozen plan's exact canonical bytes. The campaign/spec and frozen initial selection event are independently bound by the existing bundle and read-only business construction; the plan is not selected from a producer assertion, directory scan or arbitrary schema-valid object.

The production loader actually freezes the plan into this location and verifies the rebuilt plan/event against the frozen bundle. Older component factories kept the same plan only in the bundle and initial event, so absence remains supported by this file-attribution helper. That optional attribution is not permission to remove a captured production file: raw inventories and source/phase binding remain separate mandatory checks.

The final `expected == actual` comparison remains unchanged. There is no wildcard plan path, alternate plan allowance, directory-prefix exclusion or timestamp projection. No directory allowlist was widened; the separate directory/source checks remain responsible for directory inventory equality. The new rule does not itself claim to validate empty-directory semantics.

Independent disposable-copy controls used a retained native-input seed authority. The original authority was checked unchanged. Without materialization its closure passed; writing the exact frozen plan at its exact path added precisely one attributed file and passed. Four negative controls all rejected without modifying the tested copy: noncanonical changed plan bytes, identical valid bytes under a wrong hash directory, an extra file in the plan directory, and a duplicate valid plan under a different campaign. Execute, Workflow and network hooks were denied and never called. Script `/tmp/hm_frozen_selection_plan_independent.py` SHA-256 `231acd5426005090c8ae9fc6d8e8f72c600afa05fb3f14e89652df856a6073eb`; successful log `/tmp/hm-frozen-selection-plan-independent01.log` SHA-256 `80c0da42a59749735dd15f1805a9f91c1076a9b3dbc26654673543d6bb683d66`. This seed component used the existing explicitly synthetic adapter factory, not an installed-source qualification.

## Offline incomplete-DQ report guard

The offline business verifier now recomputes the same exact frozen-profile/incomplete-denominator stop predicate as the producer and demands the exact native limitation tuple. For that branch it rejects selection hashes and any run/verdict other than FAILED / NOT_EVALUATED before proceeding to Ledger and native business checks. It does not catch or relax the existing full-denominator selection gate. The preceding [Q06 narrow review](hm-q06-incomplete-dq-stop-narrow-review.md) remains unchanged.

Independent checks used disposable copies of `/tmp/hm-q06-frozen-dq-bounded-stop-native01-root/{cancel,expire}/authority`, with actual frozen bundle `8037d0010807ee7958aeed52de3154c3a1bcd5d763a6bcca42dc65e797d29dc7` and stage17 profile `077b62211806f06319cd2ec0a9dd42d6155620bd30371779efe0aae931a9ec9d`. Both copies passed the offline business verifier and complete native file attribution; both were rejected by the Q11 research predicate.

Each root then received five separately copied, contract-valid report mutations: missing incomplete marker, extra limitation, reordered limitations, false selection hash, and false SUCCEEDED/SELECTED status with a self-consistent forged candidate partition. For every mutation the reviewer updated both the content-addressed report object and the final INTENT/COMPLETE journal bytes/hash chain; a production protocol snapshot accepted this coherent protocol layer. All ten mutations nevertheless reached and were rejected by the specific new offline report guard. The copies' full file and directory inventories remained unchanged during verification. Both original component roots also remained unchanged, and execute/Workflow/network calls were zero.

Script `/tmp/hm_offline_dq_report_guard_independent.py` SHA-256 `3e5370c5144f47c706b54d53ec33dc4719bebe1a7b8b8ee69ed69730bd9d88e4`; successful log `/tmp/hm-offline-dq-report-guard-independent01.log` SHA-256 `730afe73f039216606bcafd10ccacdadfc81883b2958017fcdc7e4dd2fc723b4` is retained with both positive cases, ten rejections and zero forbidden calls.

## Historical and qualification limits

The preserved attempt17 diagnostic02 log identifies one unattributed frozen plan path and no missing or changed file paths. Its SHA-256 is `cbfbd59064e83ab3f3dc87f0fe5d2c70f250343a400b7b8f6efa781f60f841a4`; diagnostic01/02 failed exports remain failures and were not rewritten. The frozen-DQ component was generated with successor code and manual management registration, not the original installed bootstrap, and has no live model source. These observations support the bounded attribution correction and offline report guard only. Clean-successor source-bound diagnostics and remaining formal acceptance gates still require their own evidence; installed77/attempt17 is not retrospectively qualified.
