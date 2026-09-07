# P8 Agent Boundary & Threat Hardening

Status date: 2026-09-07

P8 is complete as a pre-integration security boundary. It does not add an Agent harness, MCP
server, LLM SDK, research semantic contract, or a new authority path. P9 remains responsible for
freezing proposal/campaign contracts and the minimal DSL v2; P10 remains responsible for proving
process sandbox and permission behavior against a fixed GPT + Codex configuration.

## Frozen invariants

- An untrusted request enters through an explicit capability allowlist and a bounded JSON object.
- The boundary records only capability, payload hash/size, decision, and reason; it never records
  the payload or a secret value.
- Agent process environments are constructed from `LANG`, `LC_ALL`, `LC_CTYPE`, and `TZ` only.
  `TUSHARE_TOKEN`, API keys, credentials, `PATH`, and the parent environment are not inherited.
- Authority inputs are selected by a configured domain plus a lowercase SHA-256 digest. Caller
  paths, mutable aliases, path traversal, non-canonical logical paths, and symlinks are rejected.
- Agent policies cannot grant shell, arbitrary filesystem, secret, snapshot write, Registry write
  or transition, validation override, or equivalent authority capabilities.
- Payloads cannot set authority-owned fields such as verdict/status/canonical, override gates, or
  unseal OOS evidence.
- Snapshot, Qlib view, SignalArtifact, BacktestArtifact, ValidationReport, event, and Registry reads
  reject symlinks and non-regular filesystem objects before parsing or hashing content.
- Immutable file creation uses atomic create-if-absent semantics. Directory publication and all
  multi-file Registry mutations use an advisory exclusive directory lock; a racing writer cannot
  overwrite an existing target or create an event-chain fork.

## Resource limits

The default pre-contract request budget is:

| Limit | Default |
|---|---:|
| JSON bytes per request | 262,144 |
| nesting depth | 24 |
| nodes | 10,000 |
| cumulative UTF-8 key/string bytes | 65,536 |
| requests per boundary instance | 1,000 |

Duplicate JSON keys, non-finite constants, invalid UTF-8/JSON, decoder recursion failures,
secret-bearing fields, and authority control fields fail closed. These limits protect the boundary;
later campaign/execution budgets are separate P9 contracts and cannot weaken them.

## Security-negative matrix

Automated tests cover traversal, non-canonical paths, direct and root symlink escape, artifact hash
and size spoofing, duplicate/non-finite/malformed payloads, byte/depth/node/string/request exhaustion,
secret-field denial, minimal environment construction, OOS unseal and verdict override denial,
forbidden/unknown capability denial, concurrent immutable writers, and symlinks in published trees.
The complete P0-P7 suite continues to run with network disabled and without a token.

## Boundary still to be proven later

P8 supplies deterministic enforcement primitives and hardens the current authority filesystem. It
does not claim that a particular Agent runtime is isolated. P10 must separately demonstrate the
actual Codex sandbox, network denial, environment construction, transcript/usage capture, failure
recovery, and permission-denial behavior. P11 may expose only typed services after P9 freezes their
contracts; it may not expose these filesystem primitives to the Agent.
