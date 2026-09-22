# Prepared follow-up comment for openai/codex#46947

Status: local draft only. Not posted. External issue write requires separate authorization.

Canonical basis: CodeMode-aware P10 on pinned `openai-codex==0.154.0`, report
`c5f8f53fccb844e5b87ea6888385bed63677c1d7403772845933c72d9787a1fc`, classification
`LIVE_EXEC_NOT_OBSERVED` (`6/9`).

---

## Draft comment (English)

Follow-up after a Code Mode-aware P10 qualification run on the same pinned `0.154.0` runtime.

### A/B on the same pinned 0.154.0 runtime

**Deterministic shadow provider (controlled loopback, upstream exact-tag Code Mode script shape):**

```text
exec
  -> tools.exec_command
  -> commandExecution
PASS
```

One nested `exec_command` is mechanically bound to the outer `exec` call. The exact fixed marker
(`printf QUANTOS_D07_NESTED_EXEC_OK`) returns exit 0 with a nonempty chunk id, and one matched
`commandExecution` start/completion is observed before `turn/completed`. A bounded post-terminal
drain observes no later command events. Classification: `CODE_MODE_CHAIN_AVAILABLE`.

**Real `gpt-5.6-sol` provider (CodeMode-aware P10 live turn):**

The model was explicitly instructed to use Code Mode `exec` and await `tools.exec_command` for four
exact required commands:

1. `/usr/bin/test -z "${P10_FORBIDDEN_SECRET-}"`
2. `/usr/bin/python3 write_probe.py`
3. `/usr/bin/curl --max-time 2 -fsS https://example.com`
4. `/usr/bin/pwd`

Observed result:

```text
turn completed
0 command starts
0 command terminals
0/4 matched command lifecycles
```

Outer Code Mode `exec` initiation and nested `exec_command` attribution remain `UNKNOWN` on the
retained public surface. Classification: `LIVE_EXEC_NOT_OBSERVED`. Report
`c5f8f53fccb844e5b87ea6888385bed63677c1d7403772845933c72d9787a1fc`, `6/9`, offline replay
reproduced.

### What this does and does not prove

This does not prove a provider bug.

It narrows the unresolved boundary to real Responses Lite / model-provider tool initiation: the
pinned Code Mode host, nested `tools.exec_command` dispatch, and public `commandExecution` lifecycle
are available when execution is deterministically scripted, while the real model turn that was
explicitly instructed to use the same chain produced zero observable command lifecycles.

Earlier zero-command reproductions in this issue therefore remain valid as natural-language /
model execution-contract observations. They are not evidence that nested Code Mode execution or the
public command lifecycle is generally unavailable.

### Related issue

This observation is related to https://github.com/openai/codex/issues/31894 (tool initiation /
execution boundary). We are **not** claiming the two issues share a proven root cause; the present
evidence only places both near the real Responses Lite / model-provider tool-initiation boundary.
