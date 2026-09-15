# ADR-0002: Official Codex Python SDK execution boundary

Status: implemented, qualification **NO_GO** on 2026-09-15.

## Decision

New P10/P13 harness code uses the exact-pinned `openai-codex==0.154.0` Python SDK through a
QuantOS-owned process-isolated adapter. There is no `codex exec` execution backend. Historical v1
CLI artifacts remain immutable and their contracts/parser remain read-only verification code.

The application and contract packages do not import the SDK. A fresh host process imports it,
starts one ephemeral thread, denies approvals, applies a read-only sandbox, disables history and
login shells, and receives only the explicitly declared environment and MCP servers. The adapter
creates a temporary `CODEX_HOME` containing only a symlink to an existing regular `auth.json`; it
does not read, copy, print, or persist credentials. User config, plugins and global MCP definitions
are absent from that home.

Provider notifications are retained separately and normalized fail-closed into
`quantos-agent-event/v1`. V2 run provenance binds SDK/runtime identity, requested and effective
policy hashes, normalizer identity/hash, every attempt, aggregate usage, stable terminal errors,
the normalized transcript, and either a provider-transcript hash or a non-retention reason. Failed
attempts cannot carry a proposal hash.

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
