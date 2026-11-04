---
name: quantos-research
description: Turn an A-share research direction into bounded executable daily strategies, compare Qlib results, use cited research memory, and prepare frozen signal observations and native shadow accounts through the local quantos_research MCP server.
---

# Personal research assistant

Use the local `quantos_research` MCP server from any working directory. Read
`research_capabilities_summary`, `research_strategy_capabilities(include_schema=True)`, `research_history` and
`research_scope_status` before designing or resuming work. Tools absent from the active client
require a client restart; never claim they were called. The operator CLI is
`scripts/personal_complete.py <actual_tool_name> --config <operator_config> --arguments <json_file>`
using the installed MCP interpreter. CLI arguments cannot grant authority.

The default is historical HS300 membership, Tushare Pro, daily data, supplier-adjusted price and
quantity units, after-close signals and execution at the next actual session's open. STAR and
ChiNext constituents are included. Do not return to the old mainboard/THS requirement. Ordinary
cash dividends are represented by supplier factors; no separate dividend cash credit, payment
claim, tax accounting or share-conversion ledger is provided. Daily coarse lots, full-day volume
capacity and native sell restrictions do not establish full historical exchange-rule qualification.

## From a direction to a result

The user supplies a direction and material constraints. Design the hypothesis, executable
strategy and smallest sufficient controls yourself; select returned dataset identities and
prepare through `research_prepare`. Ask only for missing decisions that change scope or meaning,
not internal hashes or routine implementation choices. The outer session generates proposals
and explanations. Leave unauthenticated model identity unknown and do not start a nested SDK.

For new directions use `personal-study-request/v7` and the capability tool's bounded
`personal-strategy/v1` / `safe-qlib-expression/v3`. Put algorithms in score, eligibility and market
expressions, ranking direction, Top-K/explicit weights, caps/risk, rebalance and holding rules.
Brief text and main/control/successor roles are descriptive. Never dispatch an algorithm by its
report role or claim a changed brief changes execution. The same complete execution tuple may
reuse its original account; changed strategy, actual signal, data, policy, period or runtime
requires a distinct binding. Preserve all proposed and attempted rows, including failures and reuse.

Use only supported mapped OHLC, adjusted volume and actual CNY amount. `amount_cny` is not volume
or close×volume. Windows/nodes/constants/candidates have published limits. `Rank` is time-series;
cross-sectional selection sorts only finite, eligible contemporaneous members with deterministic
instrument ties. Fixed slots leave cash when there are too few names. Input lag and next-session
execution lag each apply once. Unknown availability, future inputs, missing source fields or
intraday requests must fail at preparation. An unsupported idea never silently falls back to main.

Read the complete preparation, exact policy/data dependencies, controls, budget estimates and
gaps. `READY_FOR_AUTHORIZATION` grants no permission. Execution uses an operator-owned, expiring,
finite scope over strategy/data/policy/runtime identities and total attempts/accounts/resources.
`approved` fields or model assertions cannot authorize anything. New collection, real training/
backtest/Validation, forward advances, paid calls and external disclosure require applicable user
authority. Engineering authorization alone permits only its bounded synthetic exercises and
existing-evidence reads. Preserve prior valid authorization without asking again within scope.

With a valid scope, use `research_execute`, `research_status` and `research_results_summary` /
`research_results`. Continue to the authorized terminal state. Use `research_cancel` to request
cooperative stopping. `research_reconcile` verifies completed outputs and actual ownership/exit;
UNKNOWN is never automatically resent. Resume unfinished work through an explicit successor
request with `parent_task_id`, retained feedback references and a matching remaining scope.
Terminal parent requests, receipts and grants remain unchanged. Research may stop after one
informative comparison; no fixed search count or profitability target is required.

## Explain and remember

Use `research_history(query, tags, as_of)` and `research_retained_read` for prior evidence.
`research_feedback_record` forms a cited record from a settled v7 task and your labelled
interpretation/continue-or-STOP rationale; `research_memory_record` appends cited JSON facts and separately labelled model interpretation or
engineering experience. JSON Pointers copy facts from hash-verified originals; Markdown is not
passed to the legacy JSON reader. Revisions append a new record, never edit a prior conclusion.
`research_diagnostic_read` rechecks references and supplies applicability, observations,
counterevidence, uncertainty and continue/STOP rationale. Historical as_of excludes unknown or
future source/record availability. Memory is a derived index, not a second scientific authority.

Explain net wealth/return and drawdown alongside cash/exposure, fees, turnover, yearly descriptions,
qualification→target→orders/fills, partial/unfilled orders and limits where observed. Missing
metrics remain null. Strategy-specific S/T/B need their original definitions. Sell-path categories
are descriptive, not causal identification. Retain failed and cancelled denominators.

The old v6/v3 seven-arm results and classic origin remain readable under their original tuple;
new v7 studies have a question-specific denominator. confirm2 ended
SUCCEEDED / NOT_SUPPORTED / NOT_EVALUATED: the hypothesis was not supported in that scope.
Do not restart 1/3/5-day confirmation searches or rewrite it as independent validation.

For announcements use `announcement_list/read/cite/propose/review` and the existing bounded local
intake. Cite exact returned page/text offsets. A citation proves location, not semantic truth or
absence of adverse information. These tools do not acquire data. Unknown availability cannot
become a historical trading feature, and auxiliary materials keep their actual source identity.

## Frozen observation and native account

`research_snapshot_prepare` inspects a registered immutable snapshot/view and trusted arrival
metadata; it does not fetch market data. `research_observation_prepare` freezes a strategy/policy
and finite planned signal dates. `research_observation_observe` records EMITTED, ABSTAIN, MISSING,
STOPPED or FAILED; late recomputation appends an after-the-fact record without overwriting a
missing day. Use status/recover/stop tools for that explicit observation ID. Revisions keep the
previous snapshot and issued signals. A historical synthetic ENGINEERING_REPLAY is never real
forward observation; actual recorded/publication time is retained separately from its test clock.

Use `research_shadow_prepare` then authorized `research_shadow_advance` with the frozen prior
signal record and a server-returned execution snapshot. It advances a complete native Qlib
Account, preserving Position, cumulative costs/turnover, report history, strategy state, clock,
decisions and fills. Use `research_shadow_status` / `research_shadow_stop` across restarts.
Checks reject late signals, missing sessions, changed historical units/factors, incorrect snapshot
predecessors and unknown company actions. No Position import or independent cash/matching engine
substitutes for continuity. Executed/exported days reconcile before publication and are not replayed.

Use `research_scope_stop(kind, reason)` for a legal research/forward STOP. State engineering
acceptance, exploratory conclusions and formal scientific status separately. Successful synthetic
execution is not alpha, vendor-vintage PIT, independent blind evaluation or future performance.
