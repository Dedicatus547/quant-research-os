# Codex Python SDK 0.154.0 / 0.155.1 commandExecution observability gap

Date: 2026-09-21

## Summary

An ephemeral Codex Python SDK thread completes successfully on both tested versions but emits no raw
`item/started` event with `item.type=commandExecution` when the prompt explicitly requires
`/usr/bin/pwd`. Explicitly enabling `shell_tool`, disabling `unified_exec`, and disabling
`shell_tool` all produce the same zero-command observation.

A direct app-server `command/exec` D0.5 control succeeds on both bundled binaries. This narrows the
gap to the thread/model tool path rather than the app-server command surface as a whole.

A D0.6 raw stdio control then sends an SDK-captured wire fixture directly to the same bundled
app-server, bypassing only the Python transport/message router. All four raw turns also complete
with zero `commandExecution` items on both versions. The wrapper is therefore not required to
reproduce this observation, although this comparison does not exclude independent defects in both
paths or attest the effective runtime policy.

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

Candidate comparison identity:

```text
openai-codex package:         0.155.1
openai-codex-cli-bin package: 0.155.1
app-server reported version:  0.155.1 (Ubuntu 22.4.0; x86_64) unknown (codex_python_sdk; 0.155.1)
runtime binary SHA-256:       0753dfe1d8b87a52436deb13eb1c549661ef4c84fee2c5aa688385eebeccb761
aggregate matrix:             87ad91ae46ee767b910f067b99b86c5ef0b7ee97b2920e0594666ee7c096f577
```

The candidate was run as a temporary dependency overlay. `pyproject.toml` and `uv.lock` remain
pinned to 0.154.0.

D0.6 raw-thread aggregate matrices:

```text
0.154.0: 80715924852e96b36328893e8878f99a315f2f35136e3e9c32754353d3a947d7
0.155.1: af78f1e7ef2de7b633c49d31ef5afdeb4741cfad367c7e501aa1cf0412b0b438
```

## Minimal prompt

```text
Run /usr/bin/pwd as a shell command.
After the command completes, report the exact working directory.
Do not answer without executing the command.
```

The workspace is an empty temporary directory. `CODEX_HOME` is another temporary directory that
contains only a symlink to an existing regular `auth.json`. The process environment is cleared and
then limited to `CODEX_HOME`, `LANG`, `PATH`, and `TZ`. The diagnostic config disables persistent
history and login shells. No project/user-configured MCP server, Skill, output schema, plugin, or
user config is present. The raw event stream did report runtime-provided `codex_apps` startup
status; the same bundled capability was present in both compared paths.

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

Run the identical candidate matrix without updating the project lock:

```bash
UV_CACHE_DIR=/tmp/quantos-uv-cache \
uv run --with openai-codex==0.155.1 \
  python scripts/codex_sdk_failure_isolation.py \
  --all-variants \
  --expected-sdk-version 0.155.1 \
  --output-root /tmp/quantos-codex-sdk-d0-0.155.1
```

Run the raw-thread control against the pinned version:

```bash
UV_CACHE_DIR=/tmp/quantos-uv-cache \
uv run --extra agent-openai python scripts/codex_sdk_failure_isolation.py \
  --all-variants --raw-thread \
  --expected-sdk-version 0.154.0 \
  --output-root /tmp/quantos-codex-sdk-d06-0.154.0
```

Verify it offline:

```bash
UV_CACHE_DIR=/tmp/quantos-uv-cache \
uv run --extra agent-openai python scripts/codex_sdk_failure_isolation.py \
  --verify-raw-matrix \
  /tmp/quantos-codex-sdk-d06-0.154.0/raw-matrix-sha256-<matrix-hash>
```

For 0.155.1, add `--with openai-codex==0.155.1` and change the expected version and output path.

## Actual result

All four turns completed in both versions. Every raw provider transcript contained agent message,
reasoning, and user message item types, with zero `commandExecution` items. Both aggregate
classifications were:

```json
{
  "classification": "OBSERVABILITY_GAP",
  "eligible_for_p10": false
}
```

The D0.6 raw-thread classification was also identical on both versions:

```json
{
  "classification": "RAW_THREAD_OBSERVABILITY_GAP",
  "eligible_for_p10": false
}
```

All eight raw turns completed with reference and item-lifecycle integrity. The verifier binds the
captured wire fixture, runtime identity, effective environment, request/response files, raw event
stream, hash-only bounded stderr summary, result, manifest, and aggregate matrix.

## Direct app-server control

The D0.5 probe sends `initialize`, `initialized`, and this request directly to the bundled
app-server, without a model or thread:

```json
{"id":1,"method":"command/exec","params":{"command":["/usr/bin/pwd"],"cwd":"<temp-dir>","sandboxPolicy":{"type":"externalSandbox","networkAccess":"restricted"},"timeoutMs":10000}}
```

Both 0.154.0 and 0.155.1 returned exit code 0, empty stderr, and the exact temporary cwd on stdout.
Their content-addressed D0.5 bundle hashes are `f54d8e714a6b3194e61e6b8540a2c59e307cf1cb5a51ac6c15d886da7c1a9f52`
and `9799041b9190356b277ef59d13bd6304f9a9e3dffa62ea95b0f08a3426c56be1`, respectively.
`externalSandbox` is intentional because the probe runs inside an existing host sandbox; this
control does not attest thread sandbox policy.

## Expected result

For each shell-enabled positive variant, the raw provider stream should contain a command item that
binds the requested command and its completion or denial. The `shell_tool=false` negative control
should contain no command item. If the runtime intentionally withholds shell from SDK threads, the
thread-start response should expose a resolved tool/config surface that permits a deterministic
`CONFIG_NOT_APPLIED` conclusion.

## Evidence handling

The D0 and D0.6 diagnostic bundles are explicitly `NON_CANONICAL_DIAGNOSTIC`. They contain requested
config or the captured wire fixture, runtime identity, raw provider events, result summaries, and
file hashes. The D0.6 bundle additionally contains request/response evidence, effective environment,
and a hash-only bounded stderr summary. They contain no credential bytes. Agent text is not used as
evidence that a command executed.

Submitted upstream as [openai/codex#46947](https://github.com/openai/codex/issues/46947).
The D0.6 addendum is prepared locally and has not been posted to that issue.
