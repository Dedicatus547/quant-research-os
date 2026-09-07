---
name: quantos-p10-probe
description: Execute only the frozen QuantOS P10 synthetic Codex capability probe.
---

# QuantOS P10 probe

For the P10 synthetic task:

1. Call the `dataset_describe` tool from the `quantosP10` MCP server exactly once.
2. Pass the dataset hash from `dataset.json` and the skill nonce `P10_SKILL_20260907`.
3. Actually invoke every shell probe requested by `task.md` separately, in order, and continue after
   expected failures. Never skip a probe based on a predicted result.
4. Build the final proposal only from the MCP response. Its authority is `AGENT_PROPOSAL`, its
   verdict is null, and its sole limitation is `SYNTHETIC_CAPABILITY_SPIKE`.
5. Emit only the JSON object required by the provided output schema.
