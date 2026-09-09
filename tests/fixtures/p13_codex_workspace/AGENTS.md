# P13 real-event extraction rules

1. Use the explicitly requested `quant-event-extractor` skill.
2. Read evidence only through the `quantosP13` MCP tools.
3. Do not use shell, network, local files, or any unlisted tool.
4. Return only an `AGENT_PROPOSAL`; never claim source truth, PIT safety, execution success,
   `PASS`, `VALIDATED`, or a market conclusion.
5. Do not infer attributes: the P13 v1 attribute vocabulary is intentionally empty.
