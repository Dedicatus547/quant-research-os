# HM-06 isolated deployment and restricted channel implementation

Date: 2026-09-30. Development model `gpt-6-sol`, reasoning effort `high`,
implementation attempt 1 (continued phases); observed token usage and cost `unavailable`.
This is implementation evidence, not Q07/Q11 qualification. The frozen contract,
acceptance matrix and ADR retain their original bytes. The approved binding order is
[HM-02's deployment review](../reviews/hm02-deployment-bindings-review.md).

The production entrypoint is
`/install/python/bin/python3 -I -m quantos.infrastructure.hosted_service --profile-hash <D.hash>`
inside `namespace_command("service", paths, command)`. The executable accepts only the
profile hash. It never accepts a host-selected path, factory, import, spec or registration.
The management launcher supplies the literal `/install`, `/config`, `/inputs`, `/provenance`,
`/projection`, `/authority`, `/channel` mounts. Only the service sees private `/config`,
offline `/inputs`, readonly clean provenance, and writable authority. The research host
sees `/install`, its exact readonly request projection and readonly channel. Both are
Linux x86_64 bwrap namespaces; the service has no parent network, while the proposal
host has an empty readonly `/proc` and the frozen source seccomp filter. The external
Codex CLI is the host process, not a QuantOS LLM runtime backend.

The trusted manager creates immutable configuration in this order:

1. `HostedFrozenBusinessInputs` **B** and its bottom-up frozen input tree under
   `/inputs/sha256-<B.hash>.json`; B embeds the original research campaign and complete
   hosted recipe, never a hosted spec or deployment hash.
2. `HostedBusinessLoaderConfiguration` **L** at `/config/sha256-<L.hash>.json` with
   `business_inputs_hash=B.hash`, `input_root=/inputs`,
   `provenance_workspace=/provenance`, `business_root=/authority/business`.
3. `HostedServiceConfiguration` **C** at `/config/sha256-<C.hash>.json`, with
   `business_configuration_hash=L.hash`, one static campaign authorization and the
   full channel policy and principal/FD registrations. Choose policy P before C.
4. `freeze_python_install` stages standalone Python 3.11, dependencies and the exact
   QuantOS wheel, copies the frozen Codex binary, and writes public
   `HostedClientConfiguration(socket_path=/channel/quantos.sock, policy=P)` to
   `/install/hosted-client.json` before computing the full installation inventory.
   The manager saves the wheel at `/config/sha256-<wheel.hash>.whl` and the canonical
   install inventory at `/config/sha256-<inventory.hash>.json`. The fixed initial
   projection **I0** has its own exact inventory under the same content-addressed
   config convention; it contains only actual static input, no future request.
5. `HostedDeploymentProfile` **D** binds C, I0, exact wheel/installation, clean
   provenance checkout/commit/lock, OS and bwrap identities, mount policy, source
   BPF, Codex executable/version, model config and extraction rule. Save D at
   `/config/sha256-<D.hash>.json`; pass only D.hash on the service command line.

Before socket readiness, bootstrap reads each D/C/L/B canonical object via anchored
regular-file descriptors, rejects aliases/hardlinks and mismatched hashes, verifies
actual I0/install/wheel members/public client config/OS/source filter/provenance and
the one loaded campaign. It derives unique S from B plus verified D.hash, compares
stored S bytes on restart, invokes only the fixed HM-04
`load_hosted_campaign_application(L, protocol, business_lock_root,
deployment_profile_hash=D.hash)`, and restores the request-to-campaign map from
**all** persisted requests, including old terminal requests. A stale or unexpected
campaign/spec fails before bind. A host `start` target must equal the derived S hash.
The literal system binaries and `/etc` files are separately recorded in the OS
inventory; they are trusted manager observations, not host-provided paths.

The host uses `HostedUnixClient.from_configuration(public_config, capability_fd)`.
The FD is consumed and closed; neither the capability nor model auth value enters
argv, environment, logs or evidence. The six client calls are
`start(spec_hash,campaign_hash)`, `pending(campaign_hash)`, `status(campaign_hash)`,
`submit(request_hash,response_bytes,campaign_hash)`, `resume(campaign_hash)` and
`cancel(request_hash,campaign_hash)`. The channel authenticates SO_PEERCRED **and**
the independent 32-byte memory capability, then enforces campaign and derived
spec/request allowlists before calling the shared HM-04 application. It allows
one bounded frame per connection, a bounded total and concurrent connection count,
and separate frame and operation-reply deadlines. A submit reads at most
response-cap+1 and passes that prefix to the protocol for its immutable counted
rejection; no second admission path exists. Host response bytes remain original.

For each persisted pending R, management calls
`export_registered_request_projection(root, R, application, guard=...)`, which asks
HM-04 only for the original ContextPack and proposal-schema hash objects and publishes
an exact `{R.hash, context.hash, schema.hash}` inventory **Ii**. It then calls
`publish_projection_fact(R,S,profile=D,initial_inventory=I0,
projection_root=root,host_instance=...,publish_bytes=evidence.publish_bytes)`.
The trusted evidence store uses anchored create-if-absent/fsync publication; the
`HostedProjectionFact` **Pi** must exist before `TrustedCodexLauncher.capture`. Capture
rechecks Pi, mounted Ii and readonly mount flags in the actual restricted namespace,
then directly reads the real CLI stdout/stderr pipes into bounded memory. The
launcher record v2 references Pi, mount observation, exact executable/config/argv,
raw JSONL and the unmodified final agent-message proposal. Source verification
recomputes these links; a host `HostObservation` cannot assert trust by itself.
Requested model/effort and genuine captured turn/output are recorded separately
from unavailable provider-internal model snapshot/effective policy/transcript/usage.

`KnownValueGuard` holds the channel capabilities in memory before any submission or
response publication. If the manager supplies a private model-auth memory FD,
`register_model_auth_memory` scans all bounded JSON string values into the same
guard before CLI launch. The launcher maps only that FD as a private readonly
`/tmp/codex/auth.json` in host tmpfs; it does not mount the developer's Codex home.
Raw CLI output and proposal are scanned before persistence. A known-value rejection
retains only a safe rejection fact and never stores the contaminated bytes.

Focused component validation currently covers channel capability/campaign refusal,
cap+1 counted receipts and idempotence, projection aliases, wheel alias/installed
wheel mismatch, known-value raw/encoded refusal, launcher Pi/source binding and
bounded process capture. Preflight real-namespace observations are in
[hm06-environment-probe.json](hm06-environment-probe.json) and
[hm06-cli-source-boundary.md](hm06-cli-source-boundary.md); these were run before
the final wheel and do not grant Q07. A formal Q07 run still needs the clean
commit/installed wheel, actual restricted host syscall/API probes and independent
verifier. Q11 additionally requires an authenticated real Codex turn and genuine
captured output; CLI help and synthetic JSONL are insufficient. Until those occur,
both gates remain `NOT_EVALUATED`.
