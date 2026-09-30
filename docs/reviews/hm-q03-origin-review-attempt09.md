# HM Q03 original-source predicate: independent narrow review, attempt09

Status: **NARROW_IMPLEMENTATION_REVIEW_NO_OPEN_P1 / ACTUAL_Q03_FAIL / NOT_QUALIFIED**.

The current Q03 predicate rejects the actual attempt09 diagnostic for the correct reason: its export driver added a file to every original channel after the manager recorded the complete channel inventory. The eight original authority transitions remain independently verifiable. Neither those transitions nor the synthetic origin tests establish a complete Q03 PASS, HM09 acceptance, or qualification of the overall MVP.

## Reviewer and exact scope

- Reviewer model: `gpt-6.1-sol`; reasoning effort: `high`; narrow review attempt: `1`; observed token/compute usage: **unavailable**. This development-review override does not change the frozen research model profile.
- Requested frozen execution commit: `76939b8518ec212b115c6bc7a5fb1de83db14f22`.
- Initial review input: uncommitted origin predicate and its tests under `/tmp/hm-negative-followup-worktree` and the main worktree at that commit. Initial source/test hashes were `e0fae9f0de1246bbc926bb040a360a4f1ca60c0b8f7f9320f1eff8a7c0222ea2` / `737e3c8279d4e02c99f523c91139079e9897600709aff63f10751a875d376f71`.
- During review the parent fixed the independent readonly finding below and checkpointed the implementation as `53f365a5520f33e914745419c844636fa40521c7`. The final files in the two worktrees have identical hashes. The actual installed attempt09 remains frozen at **76939b8**, not this successor verifier commit.
- Final narrow implementation examined: `hosted_negative_origin.py`, Q03 dispatch in `hosted_verification.py`, `hosted_qualification_sources.py`, the existing `hosted_negative_verification.py`, installed `hosted_negative_probe.py`, and management invocation/process observation code in `hosted_manager.py`.
- Reviewer made no implementation changes, commits, model calls, snapshot acquisition calls, production requests, or new managed launches. This report and a read-only reproduction script were written only under `/tmp`. No actual model/vendor credentials were read or printed. The established deployment reader necessarily uses the private service capability internally; its bytes were not exposed.

Final reviewed file hashes:

| File | SHA-256 |
| --- | --- |
| `src/quantos/infrastructure/hosted_negative_origin.py` | `2ca3c4b460b591226e95ef3d8e6fcff60cd7f8f7433618ee59ce3b77abeabafe` |
| `tests/unit/test_hosted_negative_origin.py` | `142fde205398cdceadfa30d022008b044cde9dc64ceafd3a31ce92f81339cd32` |
| `src/quantos/infrastructure/hosted_verification.py` | `905cf61f46c263ee573f32ee20793c061cf25c19e5c7094455f27143996a2add` |
| `src/quantos/infrastructure/hosted_qualification_sources.py` | `a994d871288204458ed0ad2b5ca1c12bdd00609bd6c6f4709c51f140b007642b` |
| `src/quantos/infrastructure/hosted_negative_verification.py` | `db128f5803d96dadf9157218f6baef54f095d41453f399831bdf27f13f16f9eb` |
| `src/quantos/infrastructure/hosted_negative_probe.py` | `e0ebcb730b370fc2f058404b28c25aad00e94f432ebfe62453bfadf26262805c` |
| `src/quantos/infrastructure/hosted_manager.py` | `b537b8773dac2784fce5cf7bdf9e8202430e0eaeb5880ec3f7a1d7510156574e` |

The three frozen files were independently rehashed, unchanged: contract `14704b9cbbe0f0ca281751833bc08248820da0c277a281a140bfd12bc6b102df`; acceptance `e5877b503259f6e758f22a6feb9307efdc45397155a9229527b2a8ae5dbfc55e`; freeze manifest `ac5a4c5e01e8c064906342607ff2ef9f3e9e9b98429188689e6873f76b2ee52e`.

## Independent finding and closure

**Readonly malformed-export finding, fixed and independently retested.** The initial public `verify_q03` checked the inventory of the original manager root, but did not validate the copied before/after protocol root before constructing `HostedProtocolStore`. Its constructor can create directories. In an independent temporary synthetic bundle I removed only `campaign_hash-before/protocol/specs` and its files, leaving the original manager root intact. `verify_q03` eventually raised `HostedQualificationError`, but recreated an empty `specs` directory. A file-only raw inventory assertion missed this mutation.

The generic `verify_case` prevalidation already prevented this route in normal staging dispatch. This was a failure of the public predicate's readonly promise, not a demonstrated production RPC or qualification bypass. The parent added `verify_raw_inventory` and `verify_protocol_root` for each exported snapshot before any Store construction. New `specs` and `campaigns` missing-directory tests explicitly require rejection and that the directory remains absent. I independently ran those tests with the complete latest origin suite: **17 passed / 69.63 seconds**. The two directory-topology regressions passed. The original 15-test draft also independently passed, **15 passed / 65.23 seconds**, before that fix; those earlier file-only assertions did not cover this finding.

No further P1 was identified in the final narrow implementation. The actual attempt09 export failure below remains a concrete qualification blocker and is not erased by closing this code defect.

## Source and permission boundaries

`verify_manager_export` requires an independently supplied absolute original manager root, outside the uploaded bundle. It checks the export's bytes against its retained original content-addressed evidence, its exact mapped file set, and both original and uploaded hashes and sizes. It rechecks original installation and provenance inventories and commit/profile/lock bindings. `HostedVerifiedSources.root_origin` requires every snapshot file to preserve its original relative path under one original root. An uploaded producer label or string saying `TRUSTED`, a fixture's own success flag, or a synthetic kernel record establishes none of this authority.

The final Q03 predicate requires all sixteen independently named before/after roots for the eight fixed cases. Their origins must be exactly `qualification-cases/Q03/<case>/channel/before/authority` and `qualification-cases/Q03/<case>/authority`. Both original and exported raw inventories and protocols are read and verified. Observation, durable prelaunch, and completion must be unique and mapped to their specific original channel/evidence paths. A completion's zero integer exit, observation hash, installed program hash, frozen profile/campaign, authority paths, and prelaunch binding are checked independently of producer verdicts. The prelaunch authority inventory must be empty.

The argv is recomputed through `namespace_command` for a service namespace with the exact fresh authority/channel and fixed native `quantos.infrastructure.hosted_negative_probe` entry. Private capability/info descriptors must be distinct bounded integers. This management entry is not a research RPC; the production dispatcher has no operation for selecting a negative case, replacing a test clock, running this module, or selecting another authority path. The manager rejects an active live channel and an existing target, so it cannot silently reuse a previously retained case root. The fixed installed worker checks empty authority/channel before invoking the real application factory. Its synthetic accepted/rejected transport submissions use `negative.fixture` and are explicitly labeled `TRANSPORT_NEGATIVE_FIXTURE`; they do not create live model-source evidence.

Actual process records come from the manager's launch, bubblewrap info descriptor, and actual `/proc`: wrapper-to-init parent, exactly one init child, child parent, exact cmdline, executable image hash, status, and namespace links. The predicate validates distinct positive process IDs, native image/command, exact child-pid versus init_pid, and net/pid/mnt container inode versus observed namespace links. It requires manager namespace strings and separation from child net/pid/mnt/user identities. Kernel UID/GID must match the configured service principal and CapEff must be zero. A fixture-generated synthetic dictionary alone cannot satisfy the required original-manager export boundary.

## Accounting, duplicates, and side effects

The semantic helper does more than compare receipt reasons. It verifies both complete protocols readonly, preserved spec/request bytes and previous journal prefix, exactly one new SUBMIT INTENT/COMPLETED pair, original byte digest/size/receipt/timestamps, and the exact new publication file set. All old artifacts and non-protocol authority files must remain identical. Unknown authority files, rewritten old files, extra unrelated publications, altered deterministic outputs, extra receipts, or altered terminals are rejected.

The budget must preserve used requests, charge exactly one new unique submission to exactly the matching request reservation, bind previous budget/operation/timestamp, and preserve the original accepted receipt. Each wrong-binding fixture must isolate exactly its designated field while keeping the other bindings and requested model configuration correct. Expiry requires the frozen TTL and EXPIRED terminal; cancellation requires its original CANCELLED terminal; conflict requires distinct bytes and retains the original acceptance. Conflict's preceding cancellation must remain CANCEL_REJECTED. Initial research trial/execution/compute charges are zero.

The fixed installed worker repeats each new raw submission after expiry and requires the old receipt. It also repeats the previously seen rejected `{}` or accepted raw bytes, and repeats any cancellation, requiring the same original receipts. It captures the primary after inventory before these repetitions and then requires the entire authority inventory to remain identical after them. The manager's independently recorded completion after inventory must match that observation. Together the original installed worker and exact raw snapshots establish no duplicate charge or refund in these attempts; observation hashes alone would not.

The worker blocks deterministic execution adapter calls, Qlib Workflow calls, and socket connection calls and records any attempted calls. The source-bound final observation requires all lists empty. The worker rejects forbidden loaded SDK transports before publishing its observation, and its fixed service namespace has no model-credential mount. The observed full authority delta is also checked independently. This is a transport-test boundary, not a claim that monkeypatches constitute a complete OS network security proof.

## Actual attempt09 independent reconstruction

Original stage: `/tmp/hm-stage-76939b8-attempt09`.

- D: `9fd916af5c9d007cd20134063fcfed5d17ddea8088a92937a803f626e028423e`.
- B: `1379e46a28b69081fa838eebfae97b428787b57e672e4869e490fbb97473be46`.
- Installed frozen commit: `76939b8518ec212b115c6bc7a5fb1de83db14f22`.
- Original `evidence/negative-staging-result.json` hash: `68a8d492a35d159f868bd29425cdca2e094a6c38b8b7a821aa9ccf2d7154f934`. Its own status is NOT_QUALIFIED; it is not a verifier award.
- Diagnostic bundle: `/tmp/hm-q03-76939b8-attempt09-diagnostic`.
- Manifest/qualification hash: `0a73c92b357de0b99d18c4c71711e5bfa718daebbb826930cbbf540b9fe776cb`.
- Original manager export hash: `88e1ee8e5f55dc04aabb6da54ba49f279bb01ca28c46e1e021bf012a6ada0f1b`, **436 mapped files** independently verified.
- Saved and independently reproduced verifier-result bytes hash: `e059f5f8112550e34dd3338f546395fcddefc4aa4d4074214417cc187e31a7a0`.

I called the actual `verify_manager_export` and reconstructed `verify_staging` with the latest predicate. The saved verifier result is **byte-identical** to the independently reconstructed result: Q03 **FAIL**, every other gate **NOT_EVALUATED**, overall **NOT_QUALIFIED**. Direct `verify_q03` raises `Q03 original channel inventory differs`. Formal `verify_bundle` rejects the diagnostic basename with `qualification manifest bytes or path disagree`; I did not rename the bundle, override basename checks, or claim formal bundle acceptance.

Separately I ran the readonly transition helper against all eight **original** before/after authority roots. All eight passed the specific accounting/byte checks. I inspected the original management completion records and checked the container PID/inode bindings and namespace separation:

| Fixed case | Helper hashes | Before → after files | Actual wrapper → init → service PID |
| --- | ---: | ---: | --- |
| campaign_hash | 13 | 20 → 24 | 1324556 → 1324557 → 1324558 |
| transport_ordinal | 13 | 20 → 24 | 1324799 → 1324800 → 1324801 |
| context_pack_hash | 13 | 20 → 24 | 1324850 → 1324851 → 1324852 |
| request_hash | 13 | 20 → 24 | 1325044 → 1325045 → 1325046 |
| attempt_identity | 13 | 20 → 24 | 1325182 → 1325183 → 1325184 |
| expired | 16 | 24 → 29 | 1325325 → 1325326 → 1325327 |
| cancelled | 16 | 27 → 31 | 1325379 → 1325380 → 1325381 |
| conflict | 19 | 30 → 34 | 1325469 → 1325470 → 1325471 |

All eight original completions have return_code integer zero, native observations have `TRANSPORT_NEGATIVE_FIXTURE`, and kernel container PID/namespace crosschecks and four parent/child namespace comparisons match. Actual records also contain `NoNewPrivs: 1` and **`Seccomp: 0`**. These are Q03 management fixtures. I do not use these processes to prove that the ordinary production service installed its runtime syscall filter or to award Q07; actual production Q07 has separate requirements and evidence.

Each original channel currently has exactly one extra file relative to its manager completion inventory: **`before/authority-diagnostic-inventory.json`**. It is outside the copied `before/authority` root, so it does not change the eight primary authority-transition facts, but it does change the full observed original channel. The complete-source predicate therefore correctly fails. Preserving the changed original roots and failed diagnostic, and producing a successor fresh managed run with export sidecars only under manager evidence, is the minimum legitimate next step. Deleting the file, ignoring unknown channel files, regenerating the original completion, or filtering the inventory would erase this failure rather than repair the evidence.

The independent reconstruction script is `/tmp/hm_q03_independent_review09.py`, hash `2d3767f083016d7c94af92b16f41a0204657874238522b089d997da53464131f`. It compares complete raw inventories before/after for the diagnostic bundle, original Q03 roots, and original manager evidence. All three comparisons are unchanged. No running service was contacted and no original artifact was repaired.

## Remaining acceptance boundary

The latest narrow predicate has no open P1 from this review, with the readonly finding closed by a concrete implementation fix and two topology tests. A successor **actual source-bound** Q03 run/export is still required; the attempt09 diagnostic remains failed. The seventeen origin unit tests use synthetic kernel records and cannot qualify a deployment. The eight native transition checks establish their bounded transport facts, not live model provenance, the whole gate matrix, final failure-ledger completeness, or HM09 acceptance. **NOT_QUALIFIED remains mandatory.**
