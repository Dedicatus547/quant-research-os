# HM-03 protocol implementation

Date: 2026-09-29. Assigned development model: `gpt-6-sol`; reasoning effort: `high`.
Implementation attempt: 1. Observed usage and cost: `unavailable`.
This is component implementation evidence, not hosted deployment or live qualification.

The implementation binds the unmodified HM-02 contract
`14704b9cbbe0f0ca281751833bc08248820da0c277a281a140bfd12bc6b102df`, acceptance
`e5877b503259f6e758f22a6feb9307efdc45397155a9229527b2a8ae5dbfc55e`, and freeze manifest
`ac5a4c5e01e8c064906342607ff2ef9f3e9e9b98429188689e6873f76b2ee52e`.
All three hashes were independently recomputed after implementation. Frozen documents,
historical records and existing user documentation changes were preserved. No commit was made.

## Delivered behavior

`contracts/hosted.py` defines independent versioned spec, request/response, observation,
exchange, receipts, budget facts, checkpoints, journal publications and execution intents.
The hosted spec embeds the complete existing campaign, research budget and execution bindings;
`frozen_input_hashes` enumerates the family/template/manifest, initial Ledger, data, Evidence,
selection and policy/configuration/deployment bindings. The hosted spec content hash and
research campaign hash remain distinct. No old SDK manifest or fabricated usage is created.

External JSON is bounded before parsing and rejects duplicate keys, nonfinite values,
non-UTF-8, unknown/extra fields and noncanonical bytes. Existing canonical contracts have
a before-validator that moves nested JSON into Python validation mode; canonical comparison
after typed decoding therefore enforces exact scalar types and rejects coercion, whitespace
stripping and inserted defaults, while permitting JSON arrays/dates in their canonical form.
Proposal text retains its original UTF-8 bytes, including whitespace.

The store pins directories with openat/O_NOFOLLOW, uses a stable campaign directory inode
flock, rejects symlinks/FIFOs/hard-link aliases and publishes by create-if-absent. The new
anchored primitives in `artifacts/store.py` retain its atomic hard-link publication strategy,
with file and parent-directory fsync. No mutable index supplies authority.
Journal INTENT contains the exact planned canonical artifacts and timestamps; COMPLETE
references their published hashes. Recovery reconstructs incomplete intended publications,
checks journal continuity and bindings, and preserves the original request identity/time.
Read-only status/pending never add facts or reservations; incomplete/corrupted authority
raises a safe integrity error and requires mutation recovery or intervention.

Request and unique-submission reservations are durable independent budget facts. A request
has a fixed exhaustion receipt, and the campaign has one fixed exhaustion receipt. Rejected
and conflicting unique inputs consume allowance; identical accepted/rejected/prefix submissions
return their original receipt before TTL/cancellation/cap checks. Oversized frames read at
most cap+1 bytes and retain only an explicitly incomplete prefix digest and bounded metadata.
Cancel/expire do not refund reservations; reissue is fixed false.

Credential scanning runs before persistence of accepted bodies. Only known typed usage
scalars, the explicitly located 40-digit commit binding, and the declared request JSON schema
receive narrow scanner adaptations. Arbitrary nested proposal objects retain all credential
checks. Rejected bodies are never saved. Host observations remain HOST_REPORTED and retain
unattested policy, unavailable trusted internal usage and nonimmutable model limitations even
when a host fills in all self-reported fields. Trusted launcher validation belongs to HM-06.

## Application API handoff

Construct `HostedProtocolStore(root)` in service-owned configuration, then
`HostedProtocolService(store, clock=trusted_clock, verify_inputs=reverify_frozen_inputs)`.
The reverifier is mandatory for start/resume. HM-04 must verify all frozen inputs and legal
Ledger evolution through this callback; HM-03 has no business source resolver.

Host-facing operations, after channel authentication and campaign authorization:

- `start(spec_hash) -> HostedProtocolStatus`: initialize exact registered spec/budget facts;
  protocol READY is an internal checkpoint for HM-04 to build its first business request.
- `pending(campaign_hash) -> HostedAgentRequest | None`: return stored request bytes/identity.
- `status(campaign_hash) -> HostedProtocolStatus`: read-only state and projected expiration.
- `submit(request_hash, response_bytes, authenticated_principal) -> HostedSubmissionReceipt`:
  the shared bounded binding, cap, deduplication, conflict and receipt implementation.
- `resume(campaign_hash) -> HostedProtocolStatus`: reconcile pending protocol publication,
  reverify inputs, and durably expire an unaccepted request when required.
- `cancel(request_hash, authenticated_principal) -> HostedRequestTerminalReceipt`:
  serialize with submit; accepted requests return a fixed cancellation rejection.

Internal management/business operations must not appear on the research channel:

- `register(spec) -> spec_hash`: register a frozen spec; not an untrusted host API.
- `issue(spec_hash, business_request, *, projection_object_hashes) -> HostedAgentRequest`:
  use an already verified `AutonomousAgentRequest`, freeze its exact hash and context,
  reserve one protocol request, publish checkpoint and fixed exhaustion receipt.
- `accepted_exchange(request_hash) -> (request, response, exchange) | None`: HM-04 uses
  `exchange.content_hash` as the explicitly HOSTED_EXCHANGE run identity.
- `publish_business(campaign_hash, *, operation_id, recorded_at, artifacts,
  expected_journal_head_hash) -> HostedStoreSnapshot`: internal compare-and-set publication
  for HM-04 PREPARED/STARTED intents, receipts and STEP_COMPLETED terminal facts. Reusing
  an operation with the same artifact hashes is idempotent; changed bytes fail closed.
- `store.snapshot(campaign_hash, recover=False) -> HostedStoreSnapshot`: verified journal,
  artifacts, budget facts and original requests/receipts; `artifact(hash, ContractType)`
  loads a verified typed object. Recovery is explicit, not performed by status/pending.

`read_response_frame(request_hash, binary_stream)` reads only frozen response cap+1 bytes;
an oversized frame must then be closed without draining. HM-06 must enforce authentication,
capability/campaign allowlist, connection/timeout/frame bounds before any protocol lookup.
The hard ceilings are `REQUEST_BYTE_CAP=1048576`, `RESPONSE_BYTE_CAP=262144`; all campaign
limits and TTL are explicit input. HM-06 defines the independent exact DeploymentProfile,
which this spec binds through `deployment_profile_hash`.

Known candidate identity with malformed proposal schema/DSL/fingerprint is transport accepted
for deterministic HM-04 SCHEMA_INVALID admission. Unknown/unparseable candidate identity is
a bounded transport rejection and creates no research trial. HM-04 owns all business budget,
trial/execution/event/Ledger/P14c effects and conservative execution-uncertainty recovery.

## Validation and limits

Focused tests cover Q01–Q04 and the protocol portion of Q06: suspend/restart without charges,
multi-process identical submission, original receipt after TTL/cap/cancel, wrong bindings,
strict parsing/type/default/extra-field negatives, exact proposal whitespace, unknown versus
known invalid candidate, secrets and usage-schema smuggling, fixed campaign/request exhaustion,
cancel/expire/no-reissue, three injected publication failures, and unsafe/corrupt/orphan files.
Artifact store regression tests are included. Final checks passed:

- `.venv/bin/pytest tests/unit/test_hosted_protocol.py tests/unit/test_artifact_store.py -q`:
  **51 passed**, 28.63 seconds.
- `.venv/bin/ruff check` over all five changed/new Python files: **All checks passed**.
- `.venv/bin/pyright`: **0 errors, 0 warnings, 0 informations**, repository strict configuration.
- Frozen contract/acceptance/HM-02 manifest SHA-256 recomputation: all three unchanged.

Formal Q01–Q12 qualification stays NOT_EVALUATED until
HM-07/HM-08 evidence and HM-09 independent acceptance.

The first test pass found an empty Scripted fixture constructor, scanner mismatches for typed
commit/schema fields, and the nested strict-JSON/Python-mode issue. Each was fixed in one
diagnosed iteration; no same concrete problem remained after two repair attempts. Fixtures
reuse existing request construction only; no old fixture manifest is supplied as hosted evidence.

If a process dies between atomic link(temp,target) and unlink(temp), an unexplained hard-link
alias or `.publish-*` remains. This implementation deliberately fails closed and preserves
that authority plus journal intent, rather than deleting an unproven alias. The focused test
simulates this physical file window; actual kill/fsync-window qualification is HM-07 work.
Durability is limited to local POSIX, service-owned roots and intact filesystem/kernel. No
cross-machine/NFS transaction, physical exactly-once or isolation/live qualification is claimed.
