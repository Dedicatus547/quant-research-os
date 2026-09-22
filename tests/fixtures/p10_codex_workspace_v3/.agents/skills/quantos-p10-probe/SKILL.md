---
name: quantos-p10-probe
description: Execute only the frozen QuantOS Code Mode-aware P10 synthetic capability probe.
---

# QuantOS Code Mode-aware P10 probe

For the P10 synthetic task:

1. Call the `dataset_describe` tool from the `quantosP10` MCP server exactly once.
2. Pass the dataset hash from `dataset.json` and the skill nonce `P10_SKILL_20260907`.
3. Use the model-visible Code Mode `exec` tool for every requested shell probe. Inside Code Mode,
   call and await `tools.exec_command({cmd: ...})` once for each exact command, sequentially and in
   the listed order. Never combine commands or skip a probe based on a predicted result.
4. Continue after both expected non-zero exits and execute the final recovery probe.
5. Build the final proposal only from the MCP response. Its authority is `AGENT_PROPOSAL`, its
   verdict is null, and its sole limitation is `SYNTHETIC_CAPABILITY_SPIKE`.
6. Emit only the JSON object required by the provided output schema.
