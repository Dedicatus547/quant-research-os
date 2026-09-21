# Codex Python SDK 0.154.0 commandExecution observability gap

Date: 2026-09-21

## Summary

An ephemeral Codex Python SDK thread completes successfully but emits no raw
`item/started` event with `item.type=commandExecution` when the prompt explicitly requires
`/usr/bin/pwd`. Explicitly enabling `shell_tool`, disabling `unified_exec`, and disabling
`shell_tool` all produce the same zero-command observation.

This report does not claim that a sandbox or network policy failed. It reports that the command
surface cannot be observed or qualified through the current SDK event stream.

## Frozen identity

```text
openai-codex package:         0.154.0
openai-codex-cli-bin package: 0.154.0
app-server reported version:  0.154.0 (Ubuntu 22.4.0; x86_64) unknown (codex_python_sdk; 0.154.0)
runtime binary SHA-256:       3188814c35471432d4123203e0eb38e5bddc60226e3d7ddf0e59e649ea140022
model:                       gpt-5.6-sol
reasoning effort:            medium
approval mode:               deny_all
sandbox:                     read_only
```

Aggregate diagnostic matrix:
`214c236cf3239d14c46a4a404a2eafe9311d688131c78c3f646fc035fb7cf6fc`.

## Minimal prompt

```text
Run /usr/bin/pwd as a shell command.
After the command completes, report the exact working directory.
Do not answer without executing the command.
```

The workspace is an empty temporary directory. `CODEX_HOME` is another temporary directory that
contains only a symlink to an existing regular `auth.json`. The process environment is cleared and
then limited to `CODEX_HOME`, `LANG`, `PATH`, and `TZ`. The diagnostic config disables persistent
history and login shells. No MCP server, Skill, output schema, plugin, or user config is present.

## Reproduction

From the QuantOS repository with an existing Codex login:

```bash
UV_CACHE_DIR=/tmp/quantos-uv-cache \
uv run --extra agent-openai python scripts/codex_sdk_failure_isolation.py \
  --all-variants \
  --expected-sdk-version 0.154.0 \
  --output-root /tmp/quantos-codex-sdk-d0-0.154.0
```

The four variants are:

1. no feature override;
2. `shell_tool=true`;
3. `shell_tool=true, unified_exec=false`;
4. `shell_tool=false` as a negative control.

The command publishes one content-addressed child bundle per variant and one aggregate matrix.
Verify the result without another model call:

```bash
UV_CACHE_DIR=/tmp/quantos-uv-cache \
uv run --extra agent-openai python scripts/codex_sdk_failure_isolation.py \
  --verify-matrix /tmp/quantos-codex-sdk-d0-0.154.0/matrix-sha256-<matrix-hash>
```

## Actual result

All four turns completed. Every raw provider transcript contained agent message, reasoning, and
user message item types, with zero `commandExecution` items. The aggregate classification was:

```json
{
  "classification": "OBSERVABILITY_GAP",
  "eligible_for_p10": false
}
```

## Expected result

For each shell-enabled positive variant, the raw provider stream should contain a command item that
binds the requested command and its completion or denial. The `shell_tool=false` negative control
should contain no command item. If the runtime intentionally withholds shell from SDK threads, the
thread-start response should expose a resolved tool/config surface that permits a deterministic
`CONFIG_NOT_APPLIED` conclusion.

## Evidence handling

The diagnostic bundles are explicitly `NON_CANONICAL_DIAGNOSTIC`. They contain requested config,
runtime identity, raw provider events, optional normalized events, result summary, and file hashes.
They contain no credential bytes. Agent text is not used as evidence that a command executed.
