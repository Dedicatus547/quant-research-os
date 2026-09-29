# ADR-0002: Official Codex Python SDK execution boundary

Status: implemented, qualification **NO_GO**; amended 2026-09-22.

## Decision

New P10/P13 harness code currently uses the exact-pinned `openai-codex==0.154.0` Python SDK through a
QuantOS-owned process-isolated adapter. There is no `codex exec` execution backend. Historical v1
CLI artifacts remain immutable and their contracts/parser remain read-only verification code.

The application and contract packages do not import the SDK. A fresh host process imports it,
starts one ephemeral thread, denies approvals, applies a read-only sandbox, disables history and
login shells, and receives only the explicitly declared environment and MCP servers. The adapter
creates a temporary `CODEX_HOME` containing only a symlink to an existing regular `auth.json`; it
does not read, copy, print, or persist credentials. User config, plugins and global MCP definitions
are absent from that home.

Provider notifications are retained separately and normalized fail-closed into
`quantos-agent-event/v1`; the normalizer implementation identity is now
`quantos-codex-normalizer/v2` because command correlation is retained. New runs use v3 provenance. It binds the SDK distribution/version,
bundled runtime distribution/reported version/binary hash, normalizer identity/hash, every attempt,
aggregate usage, stable terminal errors, capability observation, normalized transcript, and either
a provider-transcript hash or a non-retention reason. Failed attempts cannot carry a proposal hash.

Requested policy, resolved runtime configuration, capability observation, and attested effective
policy are separate fields. The harness never derives an effective-policy claim by copying the
requested-policy hash. When no runtime attestation exists, v3 requires the explicit
`EFFECTIVE_RUNTIME_POLICY_NOT_ATTESTED` limitation. V2 remains available only for historical
artifact replay.

The SDK package launches a pinned bundled app-server runtime. These choices follow the official
[Codex SDK documentation](https://developers.openai.com/codex/sdk/) and
[authentication documentation](https://developers.openai.com/codex/auth/).

## Qualification outcome

The isolated SDK authenticated successfully, mechanically reported SDK/runtime version `0.154.0`,
streamed a complete turn, returned schema-constrained output, reported positive usage, and exposed
the frozen P10 MCP/Skill boundary. Two independent frozen P10 executions produced the same strict
result: six capabilities passed, while `SANDBOX`, `PERMISSION_DENIAL`, and `FAILURE_RECOVERY` lacked
evidence because no shell command event was emitted.

This is a hard `NO_GO`, not an inferred sandbox failure or a research rejection. The historical
ADR-0001 CLI qualification remains historical evidence, but it does not qualify SDK 0.154.0. P13
SDK live qualification and FR-03 cutover remain blocked until a newly pinned SDK/runtime produces
all 9/9 P10 observations without relaxing the rubric.

## 2026-09-18 amendment

The project freezes `openai-codex==0.154.0` and the matching bundled runtime packages as the current
FR-03 implementation target. A later dependency upgrade is a separate qualification change and
must not silently replace this evidence set.

A standalone non-canonical D0 diagnostic ran four 0.154.0 variants: defaults, explicit
`shell_tool=true`, `shell_tool=true` with `unified_exec=false`, and `shell_tool=false`. Every turn
completed and every raw provider transcript contained zero `commandExecution` events. The new D0
runner aggregates these variants into a content-addressed matrix with a mechanical classification
and P10 eligibility flag. The current result is an observability gap, not proof that sandbox or
network policy took effect. See the
[failure-isolation plan](../fr03-codex-sdk-failure-isolation-plan.md).

## 2026-09-21 identity hardening

The frozen identity now includes the installed `openai-codex` version, installed
`openai-codex-cli-bin` version, app-server reported version, and bundled runtime binary hash. The
isolated host fails closed with `RUNTIME_MISMATCH` when either installed distribution or the
reported runtime differs from 0.154.0. Matrix
`214c236cf3239d14c46a4a404a2eafe9311d688131c78c3f646fc035fb7cf6fc` passed offline integrity
verification and remains `OBSERVABILITY_GAP / eligible_for_p10=false`.

## 2026-09-21 D0.5 and candidate comparison

A direct app-server JSON-RPC control now executes `/usr/bin/pwd` through `command/exec` without a
thread or model. It passes on both 0.154.0 and 0.155.1, using `externalSandbox` because the probe is
already hosted inside an outer sandbox. This establishes only that the command surface is
reachable; it does not attest the thread sandbox policy.

The same four-variant D0 matrix was run with 0.155.1 as a temporary dependency overlay. All four
turns completed with zero raw `commandExecution` events. Matrix
`87ad91ae46ee767b910f067b99b86c5ef0b7ee97b2920e0594666ee7c096f577` passed offline integrity
verification and remains `OBSERVABILITY_GAP / eligible_for_p10=false`. The canonical dependency
and lock remain at 0.154.0. The reproducer was submitted as
[openai/codex#46947](https://github.com/openai/codex/issues/46947).

## 2026-09-21 D0.6 raw thread comparison

The diagnostic runner now captures the final request shape produced by each SDK version through a
capture-only fake transport and replays that shape directly over app-server stdio. The raw executor
preserves the SDK client identity, `account/read` preflight, child `PATH`, approval, sandbox, model,
effort, prompt, and feature configuration while bypassing `Codex.thread_start()`, `Thread.turn()`,
the SDK message router, and the QuantOS normalizer.

All four raw 0.154.0 turns and all four temporary-overlay 0.155.1 turns completed with zero
`commandExecution` starts. Matrices `80715924852e96b36328893e8878f99a315f2f35136e3e9c32754353d3a947d7`
and `af78f1e7ef2de7b633c49d31ef5afdeb4741cfad367c7e501aa1cf0412b0b438` passed offline
hash, wire-fixture, environment, reference-integrity, lifecycle, and classification verification.
Both are `RAW_THREAD_OBSERVABILITY_GAP / eligible_for_p10=false`.

The gap therefore reproduces without the Python SDK high-level thread/turn wrapper; the wrapper is
not required for this observation. This does not fully exclude independent SDK-path defects and
does not attest or falsify the effective sandbox policy. FR-03 remains `NO_GO`, and the canonical
dependency lock remains at 0.154.0.

## 2026-09-22 D0.7B1+ Code Mode chain qualification

The pinned 0.154.0 exact-tag test shape was replayed through a credential-free loopback Responses
provider using the fixed command `printf QUANTOS_D07_NESTED_EXEC_OK`. The controlled shadow variant
explicitly enabled `executed_tool_call_metadata`. Exact source shows that internal executed-tool
metadata is cleared for non-OpenAI provider names, so this variant used the recognized provider name
`OpenAI` while retaining a loopback-only endpoint, `requires_openai_auth=false`, and rejection of all
authentication headers.

The retained second-request projection contains no unreviewed raw output. It mechanically validates
the nested result, exact marker, exit 0, nonempty chunk id, and one exact-argument `exec_command`
metadata entry bound to the outer `exec` call. The app-server stream also contained one matched
successful `commandExecution` start/completion before `turn/completed`; a 250 ms quiet-window / 1 s
deadline post-terminal drain observed no later events. Offline replay of bundle
`9c20e6c572d8610a340e68b1ee92911f745a1214f4b97c0eb07d96f2f4ecca64` recomputes
`CODE_MODE_CHAIN_AVAILABLE`.

This narrows the earlier issue: there is no general failure of the pinned Code Mode host, nested
`exec_command`, or app-server command lifecycle on this deterministic path. It does not qualify the
historical natural-language P10 execution contract or attest sandbox, denial, and recovery behavior.
FR-03 therefore remains `NO_GO`; the P10 hard gate remains 9/9, P13 was not run in that diagnostic
step, and the 0.154.0 lock is unchanged. The subsequent CodeMode-aware P10 section records the live
qualification rerun.

## 2026-09-22 Code Mode-aware P10 qualification

The P10 fixture and evaluator now require model-visible Code Mode `exec`, nested awaited
`tools.exec_command`, exact probe cardinality/order, and matched command start/terminal identities.
The v3 artifact path retains provider and normalized transcripts and verifies the full bundle
bottom-up without authentication, network, or a model call.

The corrected canonical live run completed the turn but emitted zero command starts and terminals.
Outer Code Mode initiation and nested dispatch therefore remain `UNKNOWN`; `SANDBOX`,
`PERMISSION_DENIAL`, and `FAILURE_RECOVERY` fail for missing run-local evidence. Report
`c5f8f53fccb844e5b87ea6888385bed63677c1d7403772845933c72d9787a1fc` is `6/9`,
`LIVE_EXEC_NOT_OBSERVED`, and `NO_GO`, and passed offline replay. P13 was not run and the hard 9/9
gate was not relaxed.

## 2026-09-24 account-routing candidate review

Official `0.156.1` executable identity is verified by the superseding provenance record. Its
isolated and safe-profile account/read observations fail with `InternalRpcError` / JSON-RPC
`-32603`; the unchanged matrix reclassifies offline as `UPSTREAM_ACCOUNT_ROUTING_FAILURE`, with
exact subtype `UNKNOWN`. Candidate P10 is `NOT_EVALUATED`: no thread, turn, or provider request
started. The immutable matrix's original `INCONCLUSIVE` classification records the earlier
incorrect frozen identity binding; the later provenance supersedes only that identity assertion.
The canonical runtime and lock remain at `0.154.0`, P13 remains `NOT_EVALUATED`, and FR-03 remains
`NO_GO`. P14d-C remains `BLOCKED_UNIMPLEMENTED`.

FR-03 is frozen in thin maintenance. Requalification may reopen only for a newer official Codex
runtime candidate or an upstream fix materially affecting account/workspace routing or the
relevant SDK runtime boundary. The frozen process is official package/executable provenance, one
minimal account/read preflight, then—only if account/read passes—one unchanged Code Mode-aware P10
v3 run with `gpt-5.6-sol` and `max_attempts=1`. P10 `9/9` opens P13 qualification but does not by
itself unblock P14d-C; the full frozen FR-03 contract still applies. See the [0.156.1
requalification record](../fr03-codex-0.156.1-requalification.md) and the [thin-maintenance
policy](../fr03-code-mode-aware-p10.md).
