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

The successor profile is `hs300-daily-trend-tushare-lifecycle/v1`: historical HS300 members available
as of each after-close signal, Tushare Pro as the only market source, next-session open Qlib
execution. It includes all index boards, without a mainboard intersection or THS dependency.
The retained `hs300-daily-trend-tushare/v1` and `daily-mainboard-trend/v1` remain readable
under their original scopes.
Call `research_data_describe` to inspect registered immutable dataset IDs and policies before
preparation. A descriptive historical inventory is not an executable binding.

Prepare with `research_prepare` and `schema_version: "personal-study-request/v4"`, a unique
idempotency key, brief, `proposal: {session_id: "<this-session-label>"}`, and a matching
server-returned dataset ID. Default benchmark is SH000300. First retrospective proposal:
start 2023-01-09, end 2025-12-29, warmup_start 2022-11-01. The profile fixes SMA20, positive
5-session return and turnover amount divided by the preceding 5-session mean >=1.2;
rank momentum and select top10 with 9% targets each. Keep residual cash for fewer names.
Exit on loss of eligibility/displacement, without a fixed holding ceiling. Main, classic and
seeds17/41/73/101/137 are retained. Read the returned candidate rules and limits.

Lifecycle facts classify structural security existence and unsupported account events; they are
not predictive features or an anticipatory exit signal. Preparation requires immutable source,
date and coverage bindings. `READY_FOR_AUTHORIZATION` still grants no execution authority.
At the first unsupported event boundary, inspect the native account, held position, pending
orders and the rights/exposure history required by the frozen policy. Exposed or UNKNOWN state
hard-stops that arm without custom settlement/accounting. Keep its durable failure/audit and all
seven candidates. Pre-run native exposure is NOT_OBSERVED; never call it zero exposure. A
failed/unknown/missing arm is not a completed zero-return comparison.

Lifecycle gaps may be acquired only under the user's separate bounded acquisition authority:
Tushare first, then explicitly permitted credible sources, with exact source identities and
non-vintage limits. These MCP tools do not acquire data. Acquisition approval does not grant
the real seven-account research run; the old BLOCKED/terminal task remains immutable.

The outer host session supplies the proposal; do not nest a research SDK call. Leave
unobservable model identity unknown. Preparation saves a proposal and does not execute.
Read readiness and concrete gaps before discussing a run. Unsupported rules need an explicit
successor, not arbitrary Python or a proposal flag.

Execution requires a separately bound server authorization and budget. Tool input cannot
grant it. `approved=true` is rejected. Only an operator-owned server configuration may bind
an exact prepared/code/dataset/profile hash grant, actual approval evidence, finite seven-arm
budget, expiry, wall limit and complete-growth bound. A lifecycle successor also requires a
new grant binding the lifecycle bundle, every lifecycle source hash and native boundary policy;
a legacy grant cannot authorize it. Default authorization is absent.
Execution uses the existing host storage supervisor and timeout; missing host quota or
capacity is an execution preflight rejection, not permission to relax the guard. A synchronous
MCP execute call may exceed a client wait timeout; inspect the original task and never reissue
UNKNOWN work. An implementation authorization is not permission for market collection, new
research, sealed access, paid services, broker orders, or a permanent scheduler. Within a
valid run authorization, proceed to its terminal state without repeatedly asking to continue.
Use `research_status`, `research_results`, and `research_cancel`; retain UNKNOWN or failed
exits and never reissue an unknown execution. Repeated submissions use the original identity.

For this successor, company information uses only actually returned, entitled Tushare fields.
Announcement entitlement remains UNKNOWN unless verified independently; titles/links are not
body text or proven risk conclusions. These MCP tools do not collect data or fetch PDFs;
separately authorized lifecycle evidence uses the bounded acquisition path.
Retained local material is not relabelled as Tushare and is not a historical trading feature.

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
