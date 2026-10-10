# Independent management-negative boundary review, attempt 1

Date: 2026-09-30. Exact HEAD: `24904e9c655cb2ec533fb27a0d90b68e1aa12f34`.
Requested model/effort: `gpt-6.1-sol / high`; observed usage unavailable.
Status: **PERMISSION_BOUNDARY_NO_OPEN_P1_FOUND / NATIVE_ENTRY_REQUIRES_FIX / NOT_QUALIFIED**.

This report is in `/tmp` as requested. No implementation or repository review document was changed, no model was started, no actual authentication material was read, and no commit/push was made. No Q03 or overall qualification is awarded. Frozen research profile and contract remain unchanged. This review concerns the new management-negative entry and transition helper, not previously completed reviews.

## Exact implementation examined

| File | SHA-256 |
| --- | --- |
| `hosted_negative_probe.py` | `e0ebcb730b370fc2f058404b28c25aad00e94f432ebfe62453bfadf26262805c` |
| `hosted_negative_verification.py` | `db128f5803d96dadf9157218f6baef54f095d41453f399831bdf27f13f16f9eb` |
| `hosted_manager.py` | `1f79d3ef22648bc5497646b0c17d0b6f2e66d8297659f05053a3a3c2c0187716` |
| `tests/unit/test_hosted_negative_verification.py` | `e9113d42db8e8ee13be32da93a728cbc275f59daa9d57582dccc18f70b756169` |

Supporting reads covered the installed service bootstrap/production entrypoint, strict channel schema and dispatch, namespace command, stable directory locks and `snapshot(recover=False)`, transport submission/cancellation precedence, and existing management failure tests. Exact-commit full CI was running separately; no full-CI result is asserted here.

## Permissions and origin

No path was found from a production research RPC to the fixture's case or clock selection. HostedChannelRequest admits only start/pending/status/submit/resume/cancel; strict contract parsing rejects additional fields. Dispatch has no negative hook or clock operation. The production service executable takes the fixed profile and network probe port, and calls bootstrap without the negative clock override. The new worker's case choices are a finite tuple, selected by the trusted manager in a separate module invocation, not by a proposal, submission, or channel header.

`run_managed_negative_case` rejects unknown cases, requires the live channel to be stopped/empty, refuses an existing or symlinked case root, and uses a new `qualification-cases/Q03/<case>/{authority,channel}`. Its actual namespace argv mounts that fresh authority/channel and not the live authority. The existing fixed service namespace unshares network, clears environment, stages private capability bytes through memory descriptors, binds fixed frozen inputs/config/provenance/installation, and uses the private guest HOME. The actual attempt08 bind-source list contains no manager home or real model-auth directory/file. Merely searching for the substring `auth` would incorrectly match `authority`; the review used the actual bind-source list instead.

The worker requires initially empty authority/channel, bootstraps the real frozen factory, and changes only its local fixed clock. It never serves a research RPC listener for selecting the fixture. Local direct application calls use the explicit synthetic principal `negative.fixture`. It blocks native adapter execution, Qlib Workflow and socket connection operations, rejects forbidden SDK imports, and marks the observation `TRANSPORT_NEGATIVE_FIXTURE` and `NOT_QUALIFIED`. An accepted transport fixture can create a transport exchange, but cannot establish live model origin: no trusted launcher capture exists, and the full source-bound live verifier must reject it as live evidence.

The manager retains prelaunch identity/hash, fixed argv/profile/program hash, empty initial authority inventory, an actual kernel-observed child identity, and completion bytes. The existing external `/proc` reader verifies wrapper/init/service parentage, exact command, actual executable hash and namespace identities. Same UID or producer zero counters do not establish origin by themselves. There is no complete Q03 source-bound dispatch at this commit; these records are capture material, not a PASS implementation.

## Transition helper and seen-byte accounting

The helper first verifies both protocol roots, then reads snapshots with `recover=False`. It does not complete an outstanding journal, repair a receipt or create a business artifact. Valid protocol verification establishes the existing storage directories before the snapshot constructor is used; the helper never uses a recovery-capable locate/execute path.

It binds supplied response bytes to the complete receipt's digest, size, request, campaign and attempt identity. All non-protocol files must compare exactly. A new negative transition must preserve the original journal prefix and add exactly one INTENT/COMPLETE SUBMIT pair. The expected complete raw file map is reconstructed from every old file, the exact journal publications and the two new journal bytes. Unknown extra protocol files, unknown business additions, modified original artifacts and additional operations cannot be silently omitted.

The receipt chronology, before/after budget hashes, budget predecessor/operation/time, issued-request denominator and per-request counts are recomputed. Exactly one new unique submission is charged, and acceptance cannot be replaced. Conflict requires an existing acceptance with different response bytes; expiry requires frozen TTL to have elapsed; cancellation requires an original cancellation; binding cases isolate exactly the designated mismatch. Only the explicitly justified expiry terminal may be added. The publication set cannot contain unrelated authority.

For `seen_bytes`, the receipt must already exist in before authority, remain identical, and the entire before/after raw inventories must be equal. Seen accepted/rejected bytes cannot be recharged after cancellation/TTL/cap changes. The fixed worker also repeats the primary response after expiry, reuses the original previously seen response where present, and repeats cancellation where present. In the conflict fixture, the cancellation is a rejected cancellation of an accepted request, not a rollback of acceptance.

Independent tests: **51 negative-helper tests passed / 40.41 seconds**, including raw/business/response/extra-operation/extra-protocol-file mutations, borrowed case labels, two binding mutations, early expiry, absent cancellation, old receipt substitution, and seen accepted response after cap/TTL/cancel. **2 manager failure-record tests passed / 5.60 seconds** (`/bin/false` and `/bin/true` without observation); these substituted commands are durability tests, not namespace origin proof.

## Actual attempt08: failed worker, valid primary rejection

Original manager root: `/tmp/hm-stage-24904e9-attempt08`; D is `c6a2f1fe222dfdb92c9d836700600d8ce715334be3076126cfc8019589d68b20`.

The reviewer read actual retained prelaunch `490c446b1eb3c8f168e1284b1bfab78c470f0a36a47e1e77a17d4186238ede1f` and completion `f8120cbe9335ef12c9462ae3d788282116690ba726c179ed1a664724f80648f6`. Their fixed case/argv/profile/program/root fields matched. Prelaunch authority is empty. The actual process chain is `1314392 → 1314393 → 1314394`, with the installed seeded executable hash `6e06066e6b81eae1d2929546f29917435295900b0d272449ea4fdc5c92d3fe9a`, separate net/pid/mnt/user namespaces, UID/GID1000, zero effective capabilities and NoNewPrivs1.

This is a **failed** first case (`campaign_hash`), return_code=1, no negative observation hash, and no final success observation. The eight-case campaign did not complete. The retained log SHA-256 at review time is `1df2873cbf007c573e60b4f2a63f4aaa203a8fcceef02e94c26ae92709f8dfeb`; it records the failure. No zero execution/network counts are asserted for that incomplete observation.

The original before snapshot contains 20 files and six protocol journal entries. The original after authority contains 24 files and eight entries; both roots independently pass protocol verification. The reviewer reconstructed only the deterministic, explicitly synthetic response bytes from the saved R and fixed fixture construction, with raw hash `8e7f691ea986aae4a56caf93e0dfa6577e37a42089155cb162c87dd90e33fe46`. This matches the actual receipt `60d23dfba1b92c10473b0cd87c3721fb5607e8d64951c46d30e4181d1c8cf470`. The actual before→after helper independently returned 13 checked hashes: REJECTED/RESPONSE_BINDING_MISMATCH, unique submission0→1, request denominator unchanged and no terminal. The captured primary transition is correct despite the later worker failure. No actual model response was synthesized or substituted.

## Required integration fix and safe follow-up

The developer traced the real failure to eager SDK import: `application/__init__` imports `application.capabilities`, which imports `data.tushare`, whose `capabilities.py` imports the Tushare SDK at module scope. The reviewer independently used a fresh process with an import blocker installed **before** importing `hosted_negative_probe`. It attempted to load `tushare` and was rejected before SDK execution; no real provider call or credentials were involved. This confirms the actual dependency defect and explains why the existing forbidden-import guard cannot accept this entry. The same eager import affects `hosted_offline`; no Q09 native production success is asserted at this revision.

**Required before native entry acceptance:** remove the module-level SDK import and import it only after nonempty-token validation inside `TushareSnapshotSource.__init__`'s strict `client is None` acquisition branch. Use the injected client directly in the other branch. The SDK's only use in this module is `pro_api(token)`; the structural `TushareQueryClient` protocol already supplies annotations. Keep explicit token forwarding, provider error cleaning, rate limiters and query budgets unchanged. Do not replace the existing forbidden-import guard with a weaker check. A false-valued injected client must not accidentally trigger `client or SDK` fallback. Fresh-process import-blocker regressions for negative/offline/campaign imports and injected-client/stub-SDK constructor tests are appropriate without real credentials.

This dependency repair is required functional work; it is not a newly discovered RPC privilege escalation. The reviewed commit's negative worker is not accepted as working merely because the primary protocol rejection succeeded. A new frozen installation must be used for a successful rerun; the failed attempt08 remains immutable evidence.

**Durability follow-up:** launch OSError or wait TimeoutExpired currently exits through cleanup before the normal completion publication. Durable prelaunch and partial roots remain, correctly representing an uncertain attempt, but there is no separate safe failed-attempt record for these paths. Do not fabricate a completed worker or a success return code. A safe record can bind prelaunch identity, an explicit failed/uncertain stage and bounded error type, with unavailable return/observation fields, after cleanup; retries must still refuse the original root. Cover launch/timeout in addition to the current normal-exit failure tests. This gap does not authorize Q03 or make the incomplete attempt a PASS.

Final scope result: no production RPC privilege escape found, no helper refund/repair/unknown-file omission found in the tested transitions; current native entry requires the SDK dependency fix and a new actual run. **NOT_QUALIFIED**.
