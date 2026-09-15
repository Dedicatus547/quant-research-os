# FR-03 Codex SDK qualification

Date: 2026-09-15

SDK/runtime: `openai-codex==0.154.0` / bundled app-server `0.154.0`

Decision: **NO_GO**

## Evidence matrix

| Requirement | Result | Evidence |
|---|---|---|
| Exact SDK/runtime identity | PASS | SDK and initialized app-server versions captured mechanically |
| Existing authentication reuse | PASS | isolated home reused an existing regular auth file by symlink; no credential bytes entered QuantOS artifacts |
| User-config/global-MCP isolation | PASS | temporary `CODEX_HOME` contained no config and only the declared P10 MCP was observed |
| Structured output | PASS | final message matched the frozen schema and human baseline |
| Normalized transcript | PASS | complete started/completed turn, MCP, message and usage events normalized and hashed |
| Usage | PASS | positive input/output usage captured; no fabricated zero values |
| MCP and repo Skill | PASS | one exact `dataset_describe` call carried the frozen Skill nonce and returned exact structured data |
| Shell/sandbox/parent-secret denial | **FAIL** | SDK stream contained no command events, so write, network and parent-marker probes were not evidenced |
| Failure recovery | **FAIL** | without the two expected failed commands, later recovery could not be proven |
| P13 frozen benchmark | NOT_EVALUATED | blocked by the P10 hard gate; the approved frozen Store is not materialized in this checkout |

Two live P10 runs were retained under temporary qualification roots rather than checked in. Their
report hashes are `49653ba3e8d36d3a2cbdc69b2ddc9ad559091d08eb0069cbc5149d3a3a9f785b`
and `d256e26245f637f97bc00ed034ce1031099a8e4e65f71347015bc84683cbcd9b`.
Both were 6/9 and failed the same three capabilities.

## Implemented offline surface

- exact optional dependency and lock;
- v2 request, runtime, event, attempt, error, spec and manifest contracts;
- SDK host, isolated adapter, process-group timeout cleanup and fail-closed normalizer;
- transport-neutral P10 and P13 evaluation/publication paths;
- separate provider and normalized transcripts;
- immutable failed-run publication with no proposal authority;
- removal of the CLI execution argv/version-check backend;
- offline contract, normalization, replay and regression coverage.

No rubric was weakened and no SDK result is represented as the historical v1 CLI format. A future
SDK/runtime upgrade must repeat M0 and obtain P10 9/9 before P13 live qualification or FR-03 Go.
