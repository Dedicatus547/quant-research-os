# FR-03 Codex SDK qualification

Date: 2026-09-22

Frozen SDK/runtime: `openai-codex==0.154.0` / bundled app-server `0.154.0`

Decision: **NO_GO**

Status: FR-03 is in thin maintenance. Canonical CodeMode-aware P10 is `6/9` /
`LIVE_EXEC_NOT_OBSERVED` / report `c5f8f53f...7a1fc` / matched command lifecycle `0/4`.
P13 SDK qualification remains `NOT_EVALUATED`. Local upstream follow-up draft for
[openai/codex#46947](https://github.com/openai/codex/issues/46947) is prepared in
[fr03-codex-46947-followup-draft.md](fr03-codex-46947-followup-draft.md) and has not been posted.

2026-09-24 candidate review: `openai-codex==0.156.1` is `ADDITIVE_COMPATIBLE` with the frozen
P10 v3 normalizer/observation contract, but the isolated candidate SDK host failed before thread
and turn. Candidate P10 is therefore `NOT_EVALUATED`; FR-03 remains `NO_GO` on the canonical
0.154.0 run. No canonical dependency, probe, evaluator or P10 rubric change was made. See the
[0.156.1 requalification record](fr03-codex-0.156.1-requalification.md).

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
| D0.7 exact-source architecture | PASS | exact 0.154.0/0.155.1 tags establish `gpt-5.6-sol = CodeModeOnly + Responses Lite + unified_exec`; refreshed source bundles `19dd2bc8...a60c5d8` / `121e7fc0...c3cb7655` also bind the provider-name metadata stripping gate |
| D0.7 shadow provider preflight | PASS | credential-free loopback injection completed exactly one fixed request/response on both versions; bundles `dd4abe0f...4fed97d6` / `1dc124a5...76b88c0` verified |
| D0.7 deterministic Code Mode chain B1+ | **CODE_MODE_CHAIN_AVAILABLE** | pinned 0.154.0 bundle `9c20e6c5...f4ecca64` binds the outer `exec` call to one executed-tool metadata entry for exact nested `exec_command` arguments, validates exact fixed-marker output/exit 0/nonempty chunk id, and observes one matched successful `commandExecution` lifecycle; post-terminal command-event count is 0 |
| D0.7 live observation | **LIVE_EXEC_NOT_OBSERVED** | 0.154.0 live turn completed with zero command events; raw live HTTP was intentionally not retained, so model-visible exec remains unknown; bundle `7da8cf78...74fbc1ab` verified |
| Code Mode-aware P10 v3 | **NO_GO (6/9)** | canonical report `c5f8f53f...7a1fc` replayed bottom-up; outer `exec` and nested attribution are `UNKNOWN`, required command lifecycle count is 0/4, and `SANDBOX`, `PERMISSION_DENIAL`, `FAILURE_RECOVERY` fail closed |
| Exact dependency lock | PASS | `pyproject.toml` and `uv.lock` fix SDK and bundled runtime packages at 0.154.0 |

Two live P10 runs were retained under temporary qualification roots rather than checked in. Their
report hashes are `49653ba3e8d36d3a2cbdc69b2ddc9ad559091d08eb0069cbc5149d3a3a9f785b`
and `d256e26245f637f97bc00ed034ce1031099a8e4e65f71347015bc84683cbcd9b`.
Both were 6/9 and failed the same three capabilities.

The Code Mode-aware v3 path was then implemented and run once with the frozen 0.154.0 identity.
Its canonical local bundle is
`artifacts/feasibility/codex-p10-code-mode-20260922/sha256-c5f8f53fccb844e5b87ea6888385bed63677c1d7403772845933c72d9787a1fc`.
The turn succeeded and the retained MCP/proposal/usage evidence passed, but it again emitted zero
command starts and zero command terminals. The report is therefore `6/9 / LIVE_EXEC_NOT_OBSERVED /
NO_GO`; offline replay reproduced report `c5f8f53f...7a1fc`, manifest `dd4e37fb...7b40b5`, and
normalized transcript `55506f91...156d`. P13 was not executed.

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
- D0.7 exact-release parser, credential-free loopback Responses server, Responses Lite namespace-aware
  request projection, packaged Code Mode host ownership/architecture binding, four-valued pipeline
  observations, upstream-shaped deterministic scripted SSE chain, safe nested-result and executed-tool
  metadata projection, bounded post-terminal drain, content-addressed publication, secret scanning and
  bottom-up offline replay verification;
- offline contract, normalization, replay and regression coverage.
- versioned Code Mode-aware P10 fixture, exact four-probe lifecycle/cardinality/order evaluation,
  explicit unknown observations, v2 normalizer provenance, and bottom-up P10 artifact verification.

New runs now use v3 provenance, bind the bundled runtime binary hash, retain a separate capability
observation, and leave effective policy unattested unless runtime evidence supports it. Historical
v2 artifacts remain replayable. No rubric was weakened and no SDK result is represented as the
historical v1 CLI format. D0.7 invalidates the old assumption that direct shell exposure is the
relevant model surface: exact source and shadow request evidence show Responses Lite
`additional_tools` contains model-visible Code Mode `exec`. D0.7B1+ now mechanically proves nested
`tools.exec_command` dispatch and its successful command lifecycle on the controlled 0.154.0 path.
This invalidates a general Code Mode/app-server lifecycle defect interpretation, but it does not
qualify the historical live P10 sandbox, denial or recovery checks. P10 still requires 9/9 before
P13 live qualification or FR-03 Go. No sandbox policy is attested by the D0.7 result.
See the
[failure-isolation plan](fr03-codex-sdk-failure-isolation-plan.md).
The provider-facing reproduction is
[documented here](fr03-codex-sdk-upstream-reproduction.md) and was submitted as
[openai/codex#46947](https://github.com/openai/codex/issues/46947). A CodeMode-aware P10 A/B
follow-up comment is drafted locally and has not been posted.
