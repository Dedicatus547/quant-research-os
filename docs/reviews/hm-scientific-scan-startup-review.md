# Scientific authority scanning and startup registration independent narrow review

Date: 2026-10-01. Assigned reviewer: gpt-6.1-sol, high effort. Outcome: **the two scientific-copy scan cap mismatches and the missing startup REGISTER initialization are CLOSED for the exact source bytes below. Q12 and MVP remain NOT_QUALIFIED.** No substantive production blocker was found within this scope.

Baseline: `70cbd98dcd1898d8ec25956add34827d50365f23`. Reviewed production differences are limited to `capture_authority_snapshot`, `capture_replay_tampers`, and the fixed service entrypoint's new `initialize_registered_protocols` call. Independent evidence and copies of the reviewed source/tests are retained in `/tmp/hm-scientific-scan-independent-review01`. No implementation was edited by this reviewer, no credentials/provider/model services were accessed, no full CI was run, and old failure roots and review reports were not repaired or replaced.

## Exact source identity

| File | SHA-256 |
| --- | --- |
| `src/quantos/infrastructure/hosted_manager.py` | `1c1c98f25523c333bf6d850b23e12f0e07b85360643fe78a067d00d92b362e0f` |
| `src/quantos/infrastructure/hosted_replay_evidence.py` | `7f69fb1fe6c332b4eaf344c5d11e2d129d0c5c6b0684e475e5bae7514dd6fa4c` |
| `src/quantos/infrastructure/hosted_service.py` | `e0f64903e047f1b2dacad12c11674aba576974e66992adc2cc533188d52bb42c` |
| `tests/unit/test_hosted_scientific_scan.py` | `55e69bfd517bad32f1239188554fbc4b8fe6abc05f89a64cb1cc7a295700bc56` |
| `tests/unit/test_hosted_service_initialization.py`, corrected final tests | `6734b0455cf60a8b3e6323b7316deb38be9e81a525008a23bcd7283420f5328c` |
| `src/quantos/infrastructure/hosted_deployment.py`, unchanged guard | `54adc50f1d57aeef5a7f9713f9d4780dbcdcfd214dcd997c0eff97f71dc9d95b` |
| `src/quantos/infrastructure/hosted_verification.py`, unchanged anchored reader/inventory | `ff13dd485c1f5e610f02e171141771665f59b57443a94f5967a3993fa0d851d3` |
| `src/quantos/application/hosted_protocol.py`, unchanged protocol initialization | `62b17cb990e4b937d9fa971ec904e2d0901131a2272c34b268a249d4864709fe` |
| `src/quantos/application/hosted_campaign.py`, unchanged original input callback/business start | `cd4de6187d14d08d8b472e7c840102240833d5f87f22b0a1930e31dcdde53a37` |

The review also read repository rules (`AGENTS.md`, SHA-256 `a0b0cbbc4ab9615e933b6ceca391b2d6dfaeecfdc9323a6ea561119c9fa114c7`) and frozen acceptance (`docs/hosted/hosted-acceptance-v1.md`, SHA-256 `e5877b503259f6e758f22a6feb9307efdc45397155a9229527b2a8ae5dbfc55e`).

## Scientific-copy scan assessment

Both entrances first obtain the existing descriptor-anchored `raw_inventory`. Its ceilings remain 16 GiB per scientific file, 128 GiB per inventory and 100,000 files. The full-file reader still rejects traversal, symlinks, hardlink aliases, special files and mutation during a read. Each copied file now receives the same known capability guard with `byte_cap=item.size_bytes`, drawn from that verified inventory. No chunks are scanned separately: the original complete byte sequence is scanned for all registered variants and decoded as a complete JSON value using the unchanged guard, including its nesting rejection. The default incoming guard cap remains 4,194,304 bytes; the typed reader cap remains 16,777,216 bytes. No protocol, proposal, TTL or research budget was changed.

The snapshot already supplied `expected_sha256=item.sha256`; the replay copy now does too. Growth beyond the observed size is rejected by the guard, and smaller or same-sized different content is rejected by the writer before publishing that file. Existing source inventory rechecks remain after copying; snapshot target inventory equality also remains. Replay subsequently applies its intentional corruption only inside new copies and verifies the original baseline again. The old live authority is not mutated.

The two large-file tests use only a fixed component canary, with mixed Unicode escapes near the end of a JSON document larger than 4 MiB. This avoids satisfying the assertion through raw-only matching: decoded whole-JSON scanning must reject it at both entrances. The positive controls preserve every large byte and the source inventory. These controls cover registered known values; they do not establish detection of arbitrary unregistered secrets or change the pre-existing guard's treatment of unparseable JSON. No positive maximum-sized 16 GiB allocation was attempted.

Independent diagnostics additionally exercised both entrances with growth, shrinkage, same-sized SHA drift, symlink, hardlink and a sparse 16 GiB + 1 file: **all 12 cases rejected before publishing the scientific file**. The size/hash drift controls substitute returned bytes at the read boundary; they are component controls, not native concurrent file-race qualification. The oversize control uses a sparse file and does not allocate a 16 GiB buffer.

## Startup registration assessment

The actual fixed `main` calls `service.initialize_registered_protocols()` after full `bootstrap_hosted_service` and before the network probe, bootstrap observation publication and `serve`. That method requires a concrete `HostedCampaignApplicationService`, sorts the existing frozen spec-to-campaign authorization map, checks each key against `application.registered_spec(campaign_hash).content_hash`, and invokes only that same application's `protocol.start(spec_hash)`.

This reuses the original bootstrap-installed mandatory callback, which calls `application.verify_registered_inputs` and rechecks registered identities, frozen business inputs, execution bindings and the initial Ledger prefix. It adds no weak replacement callback, RPC or host-controlled authority write. Bootstrap already restricts this production configuration to the unique frozen campaign and spec. An initialization exception blocks readiness.

The unchanged protocol `start` writes only an empty journal's existing REGISTER INTENT/COMPLETE, zero-request/zero-submission budget and prepublished request-less exhaustion receipt. It uses the frozen `spec.started_at`; it does not call business `_advance`, issue a request or start a request TTL. Existing journals are recovered/verified rather than replaced, and malformed nonempty journals are not initialized over. Repeating initialization re-verifies inputs without charging or adding journal entries. The existing restricted business `application.start` later performs the request issuance with the then-current clock.

Independent tests observed exactly two REGISTER entries, no requests/terminals/execution, zero budget and successful `verify_protocol_root`. Advancing the component clock one day and initializing again left the entire raw inventory unchanged while re-running the original callback. Only the subsequent business start issued the first request at the advanced clock. Wrong spec binding and original callback failure published no journal. Fixed-main component controls confirmed registration precedes probe/readiness/serve and rejection prevents all three; a separate independent control rejected a non-concrete application before invoking its protocol.

These tests use frozen synthetic fixture inputs and a test execution producer; fixed-main controls substitute bootstrap/probe/publication/serve. They are source/control-flow evidence, not an actual new frozen deployment's native bootstrap, scientific execution or acceptance matrix.

## Independent checks and retained failures

The final combined scan/startup test command passed **9 tests in 7.61 seconds**. The unchanged guard/header component selection passed **6 tests in 8.06 seconds** with native AF_UNIX permission. Two additional independent main/type controls passed **2 tests in 4.46 seconds**. The 12 negative-copy controls also completed successfully.

The initial independent guard selection remains a failed log: 1 failed, 5 passed because the ordinary sandbox refused AF_UNIX `bind` with `PermissionError`. It was re-run with the required native permission, and its original failure log remains. An initial combined run during test insertion remains **2 failed, 7 passed**: main wiring test tails contained the preceding test's callback/business-start assertions. Those test boundaries were corrected; production source hashes did not change. Neither failed log is represented as PASS. An earlier invocation found no `pytest` on shell PATH; later commands used the repository `.venv/bin/python -m pytest` explicitly and retained the first log.

| Evidence under `/tmp/hm-scientific-scan-independent-review01/` | SHA-256 |
| --- | --- |
| `scan-initialize-tests02.txt`, final 9 passes | `a80a513532f8e0f1e46903ded185ce6721b3ac7a60ab2803a75e584e24b3f597` |
| `scan-initialize-tests.txt`, retained 2 failures | `88b9744760162f578a88afe37c35c60d29d43970d2f3882eb5f5e3663b71eb9d` |
| `guard-tests-native.txt`, 6 passes | `0bad1cdcdb42f858df5c4f359d8a9a8c797e7e8e7950c39c02d751621b95aff5` |
| `main-wiring-tests.txt`, 2 passes | `9da52cc473e7fb44a8fc5b37f63fcdf484cf02928f97c2f1fad8df65511a2496` |
| `negative-controls.txt`, 12 rejection controls | `246c2731d46742353d8adc52317db5728d3d412f3a9d6e8042be20522fea711f` |

The parent-reported real 29,788,439-byte scan and broader 41-test component results are supporting context, not independently repeated real-source evidence in this review. No attempt 19/22 failed root was backfilled or restarted here. This change requires a new exact-source freeze and deployment, complete offline CI with coverage at least 85%, and the applicable native qualification matrix. Prior CI, old failure roots, this review and these components cannot grant Q05/Q09/Q12 or MVP qualification.
