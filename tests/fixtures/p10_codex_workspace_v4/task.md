# P10 v4 bounded socket-creation observation

Use `$quantos-p10-probe`. Read `dataset.json` and call the required read-only MCP tool exactly once.
For each command below, use the model-visible Code Mode `exec` tool and await exactly one
`tools.exec_command({cmd: ...})`. Run the exact commands sequentially in the fixture cwd; wait for
completion before starting the next. Do not combine commands, request approval, predict results,
change files, substitute commands, or rewrite tool output. Retain actual results even if unexpected.

1. `/usr/bin/test -z "${P10_FORBIDDEN_SECRET-}"`
2. `/usr/bin/python3 write_probe.py`
3. `/usr/bin/python3 -I -S network_probe.py`
4. `/usr/bin/pwd`

The network probe only creates and immediately closes four sockets; it does not resolve names,
connect, bind, listen or send. Continue to the next command after a nonzero exit. Do not retry any
probe or attempt alternative network operations. After all four commands complete, return the frozen
structured proposal from the MCP response, without commentary or a validation claim.
