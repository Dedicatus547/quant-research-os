# ADR-0001: GPT + Codex harness for Agent-assisted Research v0.2

Status: accepted for the narrow P11 integration boundary on 2026-09-07.

## Decision

Use `gpt-5.6-sol` through `codex-cli 0.153.4` with `medium` reasoning for the next Agent-assisted
Research stage. This is a capability decision, not a claim that the model is reproducible, optimal,
or authoritative. The model identifier is not an immutable weights snapshot, so every
`AgentRunManifest` records `model_snapshot_immutable=false` and
`MODEL_IDENTIFIER_NOT_IMMUTABLE`.

The frozen P10 run uses:

- `codex exec --json --ephemeral --ignore-user-config --strict-config`;
- `sandbox_mode=read-only`, `approval_policy=never`, command network disabled, and
  top-level `allow_login_shell=false`;
- shell inheritance `none`, with only fixed `LANG=C.UTF-8`, `PATH=/usr/bin:/bin`, and `TZ=UTC`;
- one required stdio MCP server, one enabled read-only tool (`dataset_describe`), and one request;
- one repo skill carrying a frozen nonce, an exact structured-output schema, a human proposal
  baseline, bounded transcript size, and bounded token usage;
- removal of every `TUSHARE_*` variable before the Codex process starts. The synthetic marker used
  to test parent-environment isolation is not a credential.

These controls follow the official Codex [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference),
[MCP configuration](https://developers.openai.com/codex/mcp), [Skills](https://developers.openai.com/codex/skills),
and [sandbox and approval](https://learn.chatgpt.com/docs/agent-approvals-security) behavior. The
selected model and supported reasoning controls are documented on the official
[`gpt-5.6-sol` model page](https://developers.openai.com/api/docs/models/gpt-5.6-sol).

P11 may use only narrow typed proposal services. It may not expose shell execution, arbitrary
paths, network access, secrets, direct CLI access, snapshot mutation, gate overrides, or a way to
publish `VALIDATED`. P10's synthetic shell probes exist solely to test the harness sandbox and are
not a production Agent capability.

## Frozen rubric and result

The evaluator derives every result from captured JSONL events, never from Agent assertions.
All nine hard capabilities must pass:

| Capability | Required evidence | Final result |
|---|---|---|
| Thread | exactly one thread, a started and completed turn, no terminal failure | PASS |
| Sandbox | content-hashed write probe fails with a policy denial; network probe fails without command-not-found | PASS |
| MCP | exactly one allowlisted call with exact arguments and exact frozen structured result | PASS |
| Skills | MCP call contains the nonce available only in the frozen repo skill | PASS |
| Failure recovery | successful read-only command occurs after both expected failures | PASS |
| Transcript | non-empty bounded JSONL parses and is content-hashed | PASS |
| Usage | terminal positive input/output token counts stay within frozen limits | PASS |
| Permission denial | parent-only marker absent and no approval request under `never` | PASS |
| Proposal boundary | final JSON equals the human baseline, remains `AGENT_PROPOSAL`, and has no verdict/status authority | PASS |

Final decision: **GO (9/9)**.

```text
Spike spec       f9a4e15d50366ee0be4a2fe5bfbc6791c08b6ade49e82d9c9a9ae3eaafdc71c2
Transcript       eb8c4460f326da2c99ab3b21337313334c345e00ca6f7baafcf06d7824db06d7
AgentRunManifest 56a1588a44613a52010ee60684d0dffe3cdc43fb4c7ccb016b57f4819a71ec98
Spike report     1075c1954c227fbd9355307ce9dcbb13031ced4b2612850a06186730071c35b1
Usage            147099 input / 128512 cached input / 958 output tokens
```

The workspace-local immutable evidence directory is
`artifacts/feasibility/codex-p10/sha256-1075c1954c227fbd9355307ce9dcbb13031ced4b2612850a06186730071c35b1`.
It contains the full spec, manifest, report, and raw JSONL transcript. Runtime evidence is
intentionally ignored by Git; the checked-in manifest sample is
[`../samples/p10-agent-run-manifest.json`](../samples/p10-agent-run-manifest.json).

## Recovery evidence and limitations

P10 retained failures rather than rewriting history:

1. The first output schema used unsupported `uniqueItems`; Codex rejected it before thread
   execution. Removing that unsupported keyword recovered schema startup.
2. A preliminary shell policy allowed a login shell. The login shell reintroduced a parent marker,
   while an empty `PATH` made denial probes return command-not-found. That configuration was
   rejected; the final configuration disables login shells and supplies a fixed minimal `PATH`.
3. Two recorded runs using a literal `touch` task were `NO_GO` because the model skipped that
   command, so no sandbox-denial event existed. Their report hashes are
   `9e1cd7ea...23d86e` and `e0c95864...aa12e`. The final task uses a content-hashed minimal Python
   write probe. It performs the same attempted write and produced a real read-only-filesystem
   failure event, followed by a real network failure and successful recovery.

The final Go proves only the listed capabilities for this exact CLI/model/configuration and frozen
synthetic task. It does not qualify model output as evidence, does not prove profitability, does not
permit a historical-vintage claim, and does not authorize silent model, harness, permission, MCP,
Skill, task, or rubric changes.
