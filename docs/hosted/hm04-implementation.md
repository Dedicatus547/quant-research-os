# HM-04 business orchestration implementation

Date: 2026-09-30. Assigned development model: `gpt-6-sol`; reasoning effort: `high`.
Implementation attempt: 1. Observed model usage and cost: `unavailable`. This is implementation and
focused test evidence, not hosted live/deployment qualification. The HM-02 v1 contract and acceptance
files retain their frozen bytes. The [deployment binding review](../reviews/hm02-deployment-bindings-review.md)
approves the acyclic implementation order without changing those files.

`HostedCampaignApplicationService` exposes only `start(spec_hash)`, `pending(campaign_hash)`,
`status(campaign_hash)`, `submit(request_hash, original_response_bytes, authenticated_principal)`,
`resume(campaign_hash)`, and `cancel(request_hash, authenticated_principal)` to a host channel.
`register_inputs`, `registered_spec`, `verify_registered_inputs`, and `projection_object_bytes` are
management operations. `pending` returns the retained original canonical request contract. The
business service has a stable, service-owned per-campaign directory flock across `resume`; it holds no
protocol flock through execution. Protocol publishes use HM-03's short-lock journal/CAS API.

The old Scripted/Replay `_validate_response` is unchanged and keeps validating the historical
AgentRun manifest. Hosted response bytes are parsed by the independent protocol; a verified
`HostedAgentExchange` is the only hosted run identity. Shared `AutonomousCampaignOrchestrator` business
helpers now accept explicit proposal bytes/hash and provenance (`HOSTED_EXCHANGE`), then reuse the
existing candidate governor, trial identity, execution request construction, PIT/Qlib/Validation
adapter, campaign event store, Ledger reconciliation and P14c selection handoff. No SDK manifest,
zero usage, or policy pass is fabricated. Hosted requests expose the full frozen candidate set so
known repeat proposals form existing `DUPLICATE_CANDIDATE` trials; the governor still chooses the
remaining work and preserves the full family denominator.

A separate research budget journal reserves the next candidate's trial, distinct candidate,
execution, validation round and the adapter's existing deterministic workload units before
execution. The step journal publishes `PREPARED`, then durably publishes `STARTED` before calling
`execute`. A fresh process seeing `STARTED` calls only public
`QuantosResearchExecutionAdapter.verified_completed_execution(request)`. A valid receipt is
bottom-up verified and reused; a missing receipt publishes `UNCERTAIN` and a
`RECOVERY_REQUIRED / EXECUTION_UNCERTAIN` terminal report without retrying Qlib or refunding the
reservation. That public probe may repair the receipt's content-addressed index when a receipt
exists; this is an explicit recoverable publication, not a pure read. It never manufactures a
missing receipt or invokes the execution pipeline. Recovered results, trials, events and Ledger
nodes are checked against original request and execution identities. The final hosted report lists
all frozen candidates, attempted and remaining candidates, protocol/research budget facts,
selection report when available, trial/event hashes and the actual research outcome. It always
marks qualification eligibility `NOT_QUALIFIED`; independent Q07/Q11/HM-09 gates remain.

The fixed management loader takes the typed `HostedFrozenBusinessInputs` bundle (B),
`HostedBusinessLoaderConfiguration` (L) and a deployment profile hash verified by the management
bootstrap (D). B contains the original campaign, complete hosted recipe, policies, two-candidate
manifest, seed Ledger/event bytes and source inventories; it does not embed a HostedCampaignSpec or
profile hash. The loader checks the exact P14-DQ family, bottom-up snapshot/view and seed Ledger,
frozen contract/acceptance/model configuration/upstream release bytes and a clean provenance
checkout, then uniquely derives and registers S from B and D. The service wheel imports this
literal `p14dq-frozen/v1` loader; the host cannot select a factory, path, plugin or code. HM-06 owns
verification of D→C→L→B before invoking the loader, the unique campaign→S authorization map, and
the trusted pre-launch projection fact. The application exports only the pending request's original
ContextPack and proposal schema bytes by their allowlisted hashes. The full per-request projection
and model source proof are later HM-06/HM-07 authority, not claims made by this functional service.

Test-only hooks are `research_initial`, `request_checkpoint`, `prepared`, `started`,
`execution_receipt`, `completed_intent`, `trial_event`, `ledger`, `step_completed`,
`selection_ledger`, and `final_report`. Fresh spawned-process functional tests exit at durable
windows and resume from disk; `started` before the fake execution call stops uncertain, while a
completed receipt is reused and no duplicate functional execution occurs. These fake executions
are explicitly functional evidence and never a production, live, Qlib or qualification substitute.
An existing real Qlib integration test exercises the new public quote/receipt probe with an actual
completed receipt and a missing receipt, confirming no extra Workflow call. HM-07 retains the full
Q01–Q12 fault, verifier, offline import, two-root replay and cross-process barrier matrix; those
cases are not marked PASS by these component tests.

Focused verification: 100 hosted campaign, legacy campaign and hosted protocol cases
passed together; the subsequently added unaccounted Ledger change rejection passed
separately (101 relevant business/protocol cases total). Two fixed-loader filesystem
boundary tests passed, and the existing real Qlib execution integration case passed
with the new receipt probes. Repository `pyright` reported 0 errors, targeted `ruff`
check and format checks passed, and `git diff --check` passed. The frozen contract,
acceptance and manifest hashes remain `14704b9c`, `e5877b50` and `ac5a4c5e`
respectively (abbreviated here; full hashes in HM-02's manifest).

The production deployment remains pending clean-commit bundle/profile bootstrap and HM-06 channel,
projection, source and isolation checks. The high-privilege development workspace and functional
fixtures are not a qualified research host. No standalone scheduler, historical vendor-vintage PIT,
provider-internal token/cost enforcement, immutable model snapshot or physical exactly-once
execution is claimed.
