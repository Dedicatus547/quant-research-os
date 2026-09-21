# FR-03 Codex SDK qualification

Date: 2026-09-21

Frozen SDK/runtime: `openai-codex==0.154.0` / bundled app-server `0.154.0`

Decision: **NO_GO**

## Evidence matrix

| Requirement | Result | Evidence |
|---|---|---|
| Exact SDK/runtime identity | PASS | SDK package, bundled runtime package, initialized app-server version and runtime binary hash captured mechanically |
| Existing authentication reuse | PASS | isolated home reused an existing regular auth file by symlink; no credential bytes entered QuantOS artifacts |
| User-config/global-MCP isolation | PASS | temporary `CODEX_HOME` contained no config and only the declared P10 MCP was observed |
| Structured output | PASS | final message matched the frozen schema and human baseline |
| Normalized transcript | PASS | complete started/completed turn, MCP, message and usage events normalized and hashed |
| Usage | PASS | positive input/output usage captured; no fabricated zero values |
| MCP and repo Skill | PASS | one exact `dataset_describe` call carried the frozen Skill nonce and returned exact structured data |
| Shell/sandbox/parent-secret denial | **FAIL** | SDK stream contained no command events, so write, network and parent-marker probes were not evidenced |
| Failure recovery | **FAIL** | without the two expected failed commands, later recovery could not be proven |
| P13 frozen benchmark | NOT_EVALUATED | blocked by the P10 hard gate; the approved frozen Store is not materialized in this checkout |
| Minimal D0 shell matrix | **OBSERVABILITY_GAP** | aggregate matrix `214c236c...f6fc` verified all four 0.154.0 bundles; every completed turn had zero raw `commandExecution` events and `eligible_for_p10=false` |
| D0.5 direct app-server control | PASS | both 0.154.0 and candidate 0.155.1 executed `/usr/bin/pwd` through `command/exec` with exit 0; this control uses `externalSandbox` because app-server is already inside the host sandbox |
| Candidate 0.155.1 D0 shell matrix | **OBSERVABILITY_GAP** | aggregate matrix `87ad91ae...f577` passed offline verification; the same four completed variants all had zero raw `commandExecution` events |
| D0.6 raw app-server thread matrix | **RAW_THREAD_OBSERVABILITY_GAP** | 0.154.0 matrix `80715924...947d7` bypassed the SDK high-level thread/turn wrapper; all four turns completed with zero command invocations and passed offline verification |
| Candidate 0.155.1 D0.6 raw matrix | **RAW_THREAD_OBSERVABILITY_GAP** | temporary-overlay matrix `af78f1e7...0b438` produced the same four completed zero-command observations and passed offline verification |
| Exact dependency lock | PASS | `pyproject.toml` and `uv.lock` fix SDK and bundled runtime packages at 0.154.0 |

Two live P10 runs were retained under temporary qualification roots rather than checked in. Their
report hashes are `49653ba3e8d36d3a2cbdc69b2ddc9ad559091d08eb0069cbc5149d3a3a9f785b`
and `d256e26245f637f97bc00ed034ce1031099a8e4e65f71347015bc84683cbcd9b`.
Both were 6/9 and failed the same three capabilities.

## Implemented offline surface

- exact optional dependency and lock;
- v2 execution request plus v3 runtime, observation, spec and manifest provenance contracts;
- SDK host, isolated adapter, process-group timeout cleanup and fail-closed normalizer;
- bounded overload-only retries with per-attempt evidence, total wall-clock budget and backoff cap;
- v2 execution request semantics binding retry/backoff/total timeout, plus pre-retention in-memory
  rejection of echoed `TUSHARE_*` values and the synthetic P10 parent marker;
- transport-neutral P10 and P13 evaluation/publication paths;
- separate provider and normalized transcripts;
- immutable failed-run publication with no proposal authority;
- removal of the CLI execution argv/version-check backend;
- historical CLI JSONL decoding isolated under `integrations.codex.legacy_v1` with schema-driven
  v1/v2 replay dispatch;
- local subprocess checks for invalid host input and complete timeout process-group termination;
- raw app-server D0.6 runner with per-version capture-only wire fixtures, exact client/account/thread/
  turn request retention, bounded stdout and hash-only stderr handling, lifecycle/reference validation,
  content-addressed bundles, and model-free matrix replay verification;
- offline contract, normalization, replay and regression coverage.

New runs now use v3 provenance, bind the bundled runtime binary hash, retain a separate capability
observation, and leave effective policy unattested unless runtime evidence supports it. Historical
v2 artifacts remain replayable. No rubric was weakened and no SDK result is represented as the
historical v1 CLI format. The frozen 0.154.0 runtime must first produce a
`SHELL_SURFACE_AVAILABLE` D0 matrix and obtain P10 9/9 before P13 live qualification or FR-03 Go.
The D0.6 result establishes that the zero-command observation also reproduces without the Python
SDK high-level thread/turn wrapper; it does not fully exclude independent SDK-path defects or attest
the effective sandbox policy.
See the
[failure-isolation plan](fr03-codex-sdk-failure-isolation-plan.md).
The provider-facing reproduction is
[documented here](fr03-codex-sdk-upstream-reproduction.md) and was submitted as
[openai/codex#46947](https://github.com/openai/codex/issues/46947).
