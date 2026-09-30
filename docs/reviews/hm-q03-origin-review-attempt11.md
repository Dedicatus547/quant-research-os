# HM Q03 actual attempt11: independent original-source narrow review

Status: **ACTUAL_SOURCE_BOUND_Q03_PREDICATE_PASS / DIAGNOSTIC_ONLY / NOT_QUALIFIED**.

I independently verified the complete original manager export and reproduced the saved Q03 PASS with the frozen 955b07f predicate. All eight original channels exactly match their original management completion inventories. The complete saved verifier result is byte-identical to the independently recomputed result: **Q03 PASS, the other eleven gates NOT_EVALUATED, overall NOT_QUALIFIED**. No P1 was identified in this narrow recheck. This report does not grant formal bundle acceptance, HM09 acceptance, or overall qualification.

## Reviewer, exact version, and scope

- Reviewer model `gpt-6.1-sol`, effort `high`, narrow review attempt `1`, observed usage **unavailable**. This applies to development review; the frozen research model profile is unchanged.
- Frozen clean source and reviewer HEAD at start and finish: `955b07fbf4850be5450df68be2d18a32cea91844`. Root `git status --short` was empty at both checks.
- Original manager root: `/tmp/hm-stage-955b07f-attempt11`.
- Diagnostic export: `/tmp/hm-q03-955b07f-attempt11-diagnostic`.
- Scope: existing frozen Q03 original-source/accounting/process predicates and actual attempt11 original evidence. No Q04 worktree draft or general unfinished gate matrix was reviewed.
- Reviewer changed no repository implementation, frozen document, original deployment artifact, or saved diagnostic. No commit, push, managed launch, model call, acquisition call, or actual model/vendor credential read was performed. Established deployment verification uses the private service capability internally without exposing its bytes. Only this report, a read-only reproduction script, and its logs were written under `/tmp`.

The Q03 implementation and tests have exactly the same bytes as the final independently reviewed version in `/tmp/hm-q03-origin-review-attempt09.md`:

| File | SHA-256 |
| --- | --- |
| `hosted_negative_origin.py` | `2ca3c4b460b591226e95ef3d8e6fcff60cd7f8f7433618ee59ce3b77abeabafe` |
| `test_hosted_negative_origin.py` | `142fde205398cdceadfa30d022008b044cde9dc64ceafd3a31ce92f81339cd32` |
| `hosted_verification.py` | `905cf61f46c263ee573f32ee20793c061cf25c19e5c7094455f27143996a2add` |
| `hosted_qualification_sources.py` | `a994d871288204458ed0ad2b5ca1c12bdd00609bd6c6f4709c51f140b007642b` |
| `hosted_negative_verification.py` | `db128f5803d96dadf9157218f6baef54f095d41453f399831bdf27f13f16f9eb` |
| `hosted_negative_probe.py` | `e0ebcb730b370fc2f058404b28c25aad00e94f432ebfe62453bfadf26262805c` |
| `hosted_manager.py` | `b537b8773dac2784fce5cf7bdf9e8202430e0eaeb5880ec3f7a1d7510156574e` |

I did not rerun unchanged synthetic unit tests. The preceding independent 17-test run, including explicit missing-specs/missing-campaigns directory-topology assertions, closed the public-predicate readonly defect; those exact source/test bytes are present here. This round instead verifies the new actual managed execution/export and full preserved result.

Frozen contract, acceptance, and freeze manifest remain unchanged, independently rehashed respectively as `14704b9cbbe0f0ca281751833bc08248820da0c277a281a140bfd12bc6b102df`, `e5877b503259f6e758f22a6feb9307efdc45397155a9229527b2a8ae5dbfc55e`, and `ac5a4c5e01e8c064906342607ff2ef9f3e9e9b98429188689e6873f76b2ee52e`.

## Original artifact and installation bindings

| Identity | Value |
| --- | --- |
| Frozen commit | `955b07fbf4850be5450df68be2d18a32cea91844` |
| D | `3775d679c75bfe43fa52fb0591149e2034fe29bcd5e4aea246316905a557cd57` |
| B | `e089b172f135f584f584b187f4cf86bae5ff29d794af58b83e9516778279b1f8` |
| Original frozen wheel | `ef8849cc5a2fac10bc7e3aa5d40e9441805ddf2ce33caaee6d82e50c4abf884e` |
| Diagnostic manifest/qualification hash | `55637d9b9046cfa3666894235130baf0cc7f610d1ca22b573cd5cac5fb3d5b87` |
| Original retained manager export | `0bccc2d930cc0efe4d8b15a3940ca75f7e6e341d737fb75baafbfa7058302402` |
| Saved/recomputed verifier result | `88f4123cf137f96d518a50448c2b0645a29a450254821baf6628a2bb6d777019` |
| Original negative-staging summary | `d6dd909f43f81821a78fdec0ba0fc0f5e08e35b47d8b830259db49f092167137` |

`verify_manager_export` independently accepted all **436 mapped files** against the externally supplied original manager root, including the retained original export record, exact source paths, hashes and lengths, installation inventory, provenance inventory, profile, commit, and lock bindings. The diagnostic manifest is canonical. A separate complete uploaded raw-inventory comparison found the exact manifest file set plus `qualification-manifest.json`, with every listed file's hash and length equal. No uploaded producer verdict or `TRUSTED` label was used to establish origin.

I additionally compared all **142** tracked `src/quantos` project files using the frozen commit's actual git blobs. The wheel's exact QuantOS member set, wheel member bytes, installed source bytes, and original provenance source bytes are all identical, with no mismatches. The original wheel's SHA-256 matches the frozen profile. This includes the Q03 predicate and installed negative worker; a profile field alone was not treated as proof of those bytes.

## Actual Q03 predicate and complete saved result

Direct `verify_q03` returned **77 checked artifact hashes**. It verified the full sixteen-root matrix, original before/after origin paths and complete raw inventories, both exported protocol roots before readonly Store access, unique original observation/prelaunch/completion records, fresh prelaunch authority, installed program/native image hashes, exact fixed namespace argv and descriptor layout, actual process/kernel bindings, fixed clocks/request/spec, and all receipt/accounting constraints.

The independent `verify_staging` result is **byte-identical** to the saved result and matches its recorded SHA-256. Its complete twelve-gate result is Q03 PASS, Q01/Q02/Q04/Q05/Q06/Q07/Q08/Q09/Q10/Q11/Q12 NOT_EVALUATED, eligibility NOT_QUALIFIED.

Formal `verify_bundle` was also invoked and correctly rejected this diagnostic's non-content-addressed basename with `qualification manifest bytes or path disagree`. I did not rename it, bypass the basename rule, or label the diagnostic a formally accepted qualification bundle. The independently checked internal source facts and staging result do not waive that requirement.

## Actual fresh roots, process records, and full accounting

For every case I separately recomputed `verify_negative_submission_transition` on the original manager's before/after authority directories. All eight bounded checks passed:

| Fixed case | Helper hashes | Before → after file count | Actual wrapper → init → service PID | Original channel inventory |
| --- | ---: | ---: | --- | --- |
| campaign_hash | 13 | 20 → 24 | 1331716 → 1331717 → 1331718 | exact |
| transport_ordinal | 13 | 20 → 24 | 1332175 → 1332176 → 1332177 | exact |
| context_pack_hash | 13 | 20 → 24 | 1332293 → 1332294 → 1332295 | exact |
| request_hash | 13 | 20 → 24 | 1332439 → 1332440 → 1332441 | exact |
| attempt_identity | 13 | 20 → 24 | 1332946 → 1332947 → 1332948 | exact |
| expired | 16 | 24 → 29 | 1333400 → 1333401 → 1333402 | exact |
| cancelled | 16 | 27 → 31 | 1333887 → 1333888 → 1333889 | exact |
| conflict | 19 | 30 → 34 | 1334458 → 1334459 → 1334460 | exact |

All original completions have integer return code zero. Actual container child-pid matches the manager-recorded init PID. Net/pid/mnt container namespace inode fields match the actual `/proc` namespace identities, and child net/pid/mnt/user namespaces differ from the original manager's. The full predicate also verifies the exact fixed command/native executable image and configured service UID/GID with zero CapEff. These are original manager observations bound through the external export, rather than reconstructed synthetic kernel dictionaries.

All observations explicitly use `TRANSPORT_NEGATIVE_FIXTURE`; the fixed program cannot serve as live model-source evidence. Actual process status includes `NoNewPrivs: 1`, **`Seccomp: 0`**. This report concerns Q03 management fixtures and does not use those processes to prove the ordinary production service's runtime syscall filter or Q07 security acceptance.

The frozen worker starts with empty fresh authority/channel, calls the real factory, and blocks research execution, Qlib Workflow, and socket connection attempts. Actual observations report no such attempts. The readonly helper independently checks that non-protocol authority remains unchanged, every old artifact and journal entry is preserved, exactly one new SUBMIT journal pair appears, and the full new file set equals its exact journal publications. Unknown files, altered deterministic results, replaced original receipt/acceptance, or unrelated publications cannot be hidden by checking only a producer success field.

Each unique rejected/conflicting response charges the matching bounded submission reservation once, preserving used requests and original acceptance. Wrong-binding cases isolate their designated binding. Expiry and cancellation bind their original frozen terminal/TTL. Conflict retains the accepted response and its rejected cancellation. The worker repeats the same new bytes after expiry, repeats previously seen rejected or accepted bytes, and repeats cancellation where applicable; it requires the original receipts and rechecks the full captured after inventory. The independently bound management completion inventory matches that observation, so those repeats did not add a charge, refund, publication, or execution side effect.

Unlike attempt09, **all eight full original channel inventories remain exact**, with `channel_extra=[]`. The sixteen export inventory sidecars are stored under original manager `evidence/q03-diagnostic-<case>-<phase>-inventory.json`, outside both observed channels and authorities. No sidecar was inserted into an observed root. This closes the specific attempt09 export-layout blocker using new retained execution roots; it does not alter the failed attempt09 evidence.

## Readonly evidence, historical limits, and diagnostic metadata

The independent script `/tmp/hm_q03_independent_review11.py` has SHA-256 `fd99668953420d713a710df15a2b2afd875bacd3eb35e8c30a94ebd6a86a310b`. Its completed log `/tmp/hm-q03-origin-independent11.log` has SHA-256 `6924fbbc1e6aa7e9a661f6b9a67987259fbee58245c6b228166a6b5eb2b16c46`. Complete raw inventories for the diagnostic bundle, all original Q03 roots, and original manager evidence are unchanged before versus after the independent verification. No original artifact was repaired and no running service was contacted.

A reviewer driver preparation initially used a non-existent generic `python` command, so its first requested script invocation could not open a not-yet-created `/tmp` script. That safe failure is retained at `/tmp/hm-q03-origin-independent11-driver-failure.log`; corrected preparation used the explicit repository interpreter. An optional source comparison first looked for the profile without its required `sha256-...json` basename and rejected that absent path; the comparison was then performed against the actual original content-addressed profile above. Neither preliminary path error wrote or changed deployment evidence, affected the native managed attempt, or bypassed verification.

One **non-P1 diagnostic metadata discrepancy** remains: manifest limitations include `PREDICATE_POSTDATES_INSTALLED_COMMIT`. In this attempt it is stale text; frozen 955b07f actually contains the Q03 predicate, and its installed/provenance/wheel bytes were independently matched above. I did not rewrite the saved manifest. A successor export generator should derive this limitation from the actual versions. This text did not establish source authority and does not invalidate the checked Q03 receipt/process facts.

The diagnostic's `failed_attempt_hashes` is empty. It therefore does not prove the full retained historical failure ledger. Prior attempt09's failed source export, and the parent-reported attempt10 predeployment provenance failure and interrupted CI, are not erased or accepted by this report. I did not re-audit those old attempts or general exact-commit CI here.

**This is a narrow original-source Q03 predicate pass with an independently reproduced diagnostic result. Formal bundle acceptance, the other eleven gates, complete failure history, and HM09 remain outstanding. Overall NOT_QUALIFIED remains required.**
