---
name: quantos-research
description: Design bounded A-share research from a user's direction, prepare and inspect persistent studies, compare deterministic Qlib results, and read cited local company announcements through the quantos_research MCP server.
---

# Personal quantitative research

Use `quantos_research` MCP tools from any working directory. Start with
`research_capabilities`, `research_history`, and `announcement_list`; use explicit returned
task and evidence IDs for subsequent operations. If several tasks fit “continue”, show the
choices. A client restart may be required after installation; never pretend an unavailable
tool was called.

The user supplies the research direction; design the supported complete strategy and
explain the choices. Choose ordinary parameters yourself. Ask only about a material change
of target, source preference, expenditure, or disclosure. Check data coverage before designing
around it. Index constituents cannot stand for all mainboard stocks; other sectors cannot
stand for THS; daily data cannot recreate a five-minute exit.

The current finite profile is `daily-mainboard-trend/v1`: daily after-close signal and next-open
Qlib execution, market/trend/volume/THS eligibility, top-K targets, exit on loss of eligibility or
displacement, and no fixed three-day ceiling. Read the returned candidate rules and limits;
this is a distinct daily proposal, not a replication of intraday intuition. Unsupported rules
need a development successor, not arbitrary Python or a proposal flag.

Prepare with `research_prepare` using a unique idempotency key, brief, and
`proposal: {session_id: "<this-session-label>"}`. Include a server-returned dataset ID only
when it matches the intended scope. The outer session supplies the proposal; do not nest a
research SDK call. Leave unobservable model identity unknown. Preparation saves a proposal
and does not execute. Read readiness and concrete gaps before discussing a run.

Execution requires a separately bound server authorization and budget. Tool input cannot
grant it. An implementation authorization is not permission for market collection, new
research, sealed access, paid services, broker orders, or a permanent scheduler. Within a
valid run authorization, proceed to its terminal state without repeatedly asking to continue.
Use `research_status`, `research_results`, and `research_cancel`; retain UNKNOWN or failed
exits and never reissue an unknown execution. Repeated submissions use the original identity.

Read announcements through `announcement_read`; construct `announcement_cite` with exact
returned Unicode offsets and text, then `announcement_propose` and `announcement_review`.
Citation integrity proves location, not semantic correctness. Human review and research
admission remain separate. UNKNOWN availability cannot become a historical feature; partial
source coverage cannot support “no adverse news”. Label these outputs auxiliary analysis
when they are not admitted trading features. Do not externally disclose material merely
because it is readable locally.

Explain results in plain Chinese, separating engineering status, scientific verdict,
proposal, and actual account outcomes. Keep missing metrics null and every fixed random
seed, failed candidate, and attempted variant in the denominator. Read retained evidence
without rerunning it. A strategy REJECT is a legitimate research result. Do not claim alpha,
independent blind evaluation, vendor-vintage PIT, or profitability from engineering success.

Use `research_simulation_prepare` to inspect the actual native-account capability and gaps.
Historical synthetic replay is an engineering exercise. Actual forward simulation needs a
fixed strategy, newly arrived immutable snapshots, an explicitly bounded observation period,
and authorization. Never describe a signal log as an account or elapsed future observation.
