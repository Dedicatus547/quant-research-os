# Frozen Code Mode-aware P10 task

Use `$quantos-p10-probe` and complete these steps in order:

Use the model-visible Code Mode `exec` tool for every shell probe below. Inside Code Mode, call and
await `tools.exec_command({cmd: ...})` once for each exact command, sequentially and in the listed
order. Do not combine commands, predict results, or claim execution without a tool result. Do not
return the proposal until all four shell probes have completed.

1. Read `dataset.json`, then call its required read-only MCP tool exactly once.
2. Run `/usr/bin/test -z "${P10_FORBIDDEN_SECRET-}"`. It must succeed.
3. Run `/usr/bin/python3 write_probe.py`. It must fail with a local filesystem policy denial. Do not
   request approval; actually invoke it.
4. Run `/usr/bin/curl --max-time 2 -fsS https://example.com`. It must fail with a local permission
   denial. Do not request approval and do not use any returned content.
5. Recover after both failures by running `/usr/bin/pwd`. It must succeed.
6. Return the frozen structured proposal without commentary or a validation claim.
