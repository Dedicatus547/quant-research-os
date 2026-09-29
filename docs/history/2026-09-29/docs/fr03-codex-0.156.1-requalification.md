# FR-03 Codex 0.156.1 requalification

Date: 2026-09-24

Decision: **NOT_EVALUATED; FR-03 remains NO_GO**

Current candidate interpretation after the superseding runtime provenance review: official
`0.156.1` executable identity is **VERIFIED**. The account/read preflight is **FAILED** and the
unchanged A/B/C observations classify offline as `UPSTREAM_ACCOUNT_ROUTING_FAILURE`; the exact
internal subtype is `UNKNOWN`. Candidate P10 remains `NOT_EVALUATED` because P10 did not start.
The original account-routing matrix retains its initial `INCONCLUSIVE` classification because its
frozen identity assertion was incorrect. The superseding record changes only that identity
assertion and its derived classification, not the historical artifact bytes or runtime outcomes.
See [runtime identity provenance](fr03-codex-runtime-identity-provenance.md) and
[account-routing diagnostic v2](fr03-codex-account-routing-diagnostic-v2.md).

This run stopped during compatibility preflight before any model turn. It is not a new P10 score
and does not revise the canonical 0.154.0 result (`6/9`, `LIVE_EXEC_NOT_OBSERVED`, `0/4` matched
probe lifecycles).

## Bound candidate identity

| Field | Observed value |
|---|---|
| Starting repository commit | `07fd2e4ac8b29bebf2fdfba4005c5b028810112b` |
| Canonical SDK/runtime | `openai-codex==0.154.0`, bundled runtime `0.154.0` |
| Candidate SDK/runtime packages | `openai-codex==0.156.1`, `openai-codex-cli-bin==0.156.1` |
| Upstream source | `rust-v0.156.1`, commit `b412ff32c417f855c2b2d1581b77058eed87c84b` |
| PyPI publishing workflow commit | `8a3c4ea3b5a7c0e92cf24dae46ec87629a26bb7f` |
| SDK sdist SHA256 | `84de33cc7bf39f974423bd7568a5662d4eb1c685e6f9808c6160f1a68338a0c8` |
| Reported app-server version | `0.156.1 (Ubuntu 22.4.0; x86_64) WindowsTerminal (codex_python_sdk; 0.156.1)` |
| Bundled runtime binary SHA256 | `0b2e9301d6100dddda9b3d5c80ebaeaa3a2f1962388f2f36f6b96a9f08b1f33f` |
| Python / platform | `3.11.15` / `Linux-6.18.33.2-microsoft-standard-WSL2-x86_64-with-glibc2.35` |
| Model / provider | `gpt-5.6-sol` / no provider turn started |
| Requested sandbox / approval | `read_only` / `deny_all` |
| Normalizer | `quantos-codex-normalizer/v2`, hash bound in the artifact |

The candidate used an isolated `CODEX_HOME`; the existing auth file was reused by symlink. No auth
bytes, raw provider body, or provider request were retained. The canonical `pyproject.toml` and
`uv.lock` pins remain 0.154.0.

## Upstream compatibility result

Classification: **ADDITIVE_COMPATIBLE**.

The public Python signatures for `Codex.thread_start`, `Codex.thread_resume`, `Thread.turn`, and
`TurnHandle.stream` have the same hash at 0.154.0 and 0.156.1. The notification registry has the
same 82 method names. The `CommandExecutionThreadItem` wire schema and the public
`item/started` / `item/completed` envelope fields have the same schema hash. Six selected
notification schemas have a different hash because the generated public schema has additive and
non-command changes; the candidate models validated the required notification forms and the
existing v2 normalizer replayed a synthetic matched lifecycle.

The exact tagged-source review found:

- From `rust-v0.155.1` to `rust-v0.156.0`, the app-server item schema adds an optional MCP UI
  field; the added `model_context` on command items is skipped from JSON, JSON schema and
  TypeScript output. `codex-rs/tools/src/code_mode.rs` serializes output schemas through
  `ToolOutputSchema::to_value`.
- The same release adds core `notify_command_start` extension-hook plumbing. This is not the
  public app-server v2 `item/started` notification. The v2 dispatcher still ignores deprecated
  `ExecCommandBegin/End`; this hook is not retained or accepted as P10 evidence.
- From `rust-v0.156.0` to `rust-v0.156.1`, the reviewed Python SDK and app-server protocol paths
  do not change; the model catalog and related snapshots/prompts change. No public replacement
  for Code Mode `exec`, nested `exec_command`, or `commandExecution` appears.

The SDK normalizer and the P10 observation contract did not need semantic changes. A finite
candidate runtime profile was added only to let the unchanged isolated SDK host check this package
overlay while retaining 0.154.0 as the default and canonical profile. The frozen P10 request,
evaluator, nine capabilities, probe order and four commands are unchanged.

## Preflight stop

The candidate package and bundled binary versions matched. Direct use of the public SDK started an
ephemeral thread and reported the 0.156.1 app-server version. Its `account(refresh_token=False)`
precheck returned an `InternalRpcError` (`-32603`); only a hash was retained. The exact isolated
QuantOS host profile then returned `UNKNOWN` with hash
`c7562a96f966f7f0eaca94fae0e9237a6cad6fc80a11b7675edc7f0315efa94a` before a thread ID or provider
event was available. No `turn()` call was made.

The original candidate-preflight capture records two isolated host preflight invocations because the first summary formatter attempted
to read a nonexistent result attribute after the host had returned. Each host request had
`max_attempts=1`; neither invocation started a turn or provider request. The second result was
captured in the artifact. This was preflight diagnostics only, not P10 best-of-N or sample
selection.

Therefore the 0.156.1 live P10 score and command lifecycle counts are **NOT_EVALUATED**. They are
not reported as `0/9` or `0/4`. The stop point is CASE D: no live qualification is possible until
the isolated host can pass preflight. No prompt, probe, approval policy, rubric or historical
artifact was changed. The later superseding provenance record corrects only the frozen runtime
identity assertion and reclassifies the existing account/read observations; it does not revise
those observations.

## Superseding provenance and current candidate classification

The official package audit verified `openai-codex-cli-bin==0.156.1`, the manylinux x86_64 wheel
SHA-256 `84a12567ca54ba6ae4ed755911c04e7cdf658315f8719963c8daa8592d8fe068`, and its bundled
executable SHA-256
`0b2e9301d6100dddda3b9d5c80ebaeaa3a2f1962388f2f36f6b96a9f08b1f33f`. The PyPI Trusted
Publishing provenance is GitHub Actions in `openai/codex` at commit
`8a3c4ea3b5a7c0e92cf24dae46ec87629a26bb7f`. The provenance artifact
`6768f0e935643c535e452a3fd311fbda3c552f0eb44c647d9d29588bb02565af` passes its offline verifier.

After correcting the identity assertion in interpretation only, the existing observations are:

| Scenario | Runtime identity | Initialize | `account/read` | Other retained outcome |
|---|---|---|---|---|
| A: isolated 0.154.0 | `VERIFIED` | `PASS` | `PASS` | `accounts/check` false; no thread, turn, or provider request |
| B: official isolated 0.156.1 | `VERIFIED` after superseding provenance | `PASS` | `FAILED` | `InternalRpcError` / `-32603`; safe classification `UNKNOWN_INTERNAL`; no thread, turn, or provider request |
| C: 0.156.1 safe normal-profile projection | `VERIFIED` after superseding provenance | `PASS` | `FAILED` | same error classification and bounded error-message hash as B; no thread, turn, or provider request |

The immutable diagnostic's original classification was `INCONCLUSIVE` because the frozen runtime
identity binding did not match the official executable. The superseding record mechanically
recomputes the unchanged A/B/C observations as `UPSTREAM_ACCOUNT_ROUTING_FAILURE`. It does not
identify a more specific subtype: retained evidence supports only `UNKNOWN_INTERNAL` and does not
distinguish timeout, duplicate workspace, or origin mismatch. Candidate P10 is still
`NOT_EVALUATED`; FR-03 remains `NO_GO`, P13 remains `NOT_EVALUATED`, and P14d-C remains
`BLOCKED_UNIMPLEMENTED`.

## Immutable evidence

Final preflight artifact:

```text
artifacts/qualification/fr03-codex-0.156.1/
  sha256-d41f4009d2bb47a6cea58bc2eb868fb42ce6627fd5c8748425e3f2c4f2a67945/
```

Report hash: `d41f4009d2bb47a6cea58bc2eb868fb42ce6627fd5c8748425e3f2c4f2a67945`.

Offline verification, including synthetic notification replay and bottom-up replay of the
historical canonical P10 artifact, passes with no model, provider, auth or network:

```bash
UV_CACHE_DIR=/tmp/quantos-uv-cache uv run --offline --extra agent-openai \
  python scripts/verify_codex_candidate_preflight.py \
  --verify-run artifacts/qualification/fr03-codex-0.156.1/sha256-d41f4009d2bb47a6cea58bc2eb868fb42ce6627fd5c8748425e3f2c4f2a67945
```

Historical P10 still replays as report `c5f8f53fccb844e5b87ea6888385bed63677c1d7403772845933c72d9787a1fc`,
manifest `dd4e37fb41d14a13c452cac6403df9178797653363ca6af35af3b115ff7b40b5`, `6/9`,
`LIVE_EXEC_NOT_OBSERVED`, and `0/4` matched probes.

Upstream source links: [rust-v0.155.1 unified exec](https://github.com/openai/codex/blob/rust-v0.155.1/codex-rs/core/src/tools/handlers/unified_exec/exec_command.rs),
[rust-v0.156.0 app-server event handling](https://github.com/openai/codex/blob/rust-v0.156.0/codex-rs/app-server/src/bespoke_event_handling.rs),
[rust-v0.156.1 command item schema](https://github.com/openai/codex/blob/rust-v0.156.1/codex-rs/app-server-protocol/src/protocol/v2/item.rs),
and [rust-v0.156.1 Python client](https://github.com/openai/codex/blob/rust-v0.156.1/sdk/python/src/openai_codex/client.py).

FR-03 remains **NO_GO** on its canonical 0.154.0 result. P14d-C remains blocked and was not
implemented.
