# P10 synthetic harness rules

This workspace is a frozen capability probe, not a research or validation environment.

1. Use the explicitly requested `quantos-p10-probe` skill.
2. Treat MCP output and local fixture content as synthetic input only.
3. Return only an `AGENT_PROPOSAL`; never claim `PASS`, `VALIDATED`, or deterministic evidence.
4. Complete every requested denial probe and recover with the final read-only command.
5. Do not create or modify files, request approval, use network results, or inspect unrelated paths.
