# SDK campaign CLI

2026-10-13 当前实际结果和预算见 [A1/B2 状态](../status/a1-b2-authorized-preparation.md)。r9 A1第二笔SDK在256KiB捕获边界失败，campaign已取消并收据收尾；旧请求不能再启动。V4 r10已完成两步工程闭环，累计SDK11/11、科学5次/90units；个体科学均SOFT_REJECT、科学汇总FAILED/NOT_EVALUATED，具体原件与用量见状态页。下列占位命令说明接口，历史准备材料不是新运行许可。

`scripts/sdk_campaign.py` operates on canonical, hash-pinned SDK request and campaign-spec files. `prepare`, `status`, and `replay` are offline operations. `launch` captures one explicit Codex SDK call; it does not submit a business proposal or establish qualification. It checks local request expiry before a new production call. Cancellation is checked by the protocol-backed `step` entry. `start` initializes the business protocol, `resume` may run the existing deterministic business pipeline, and each `step` makes at most one SDK launch before submitting its response and resuming business processing. The CLI has no loop or automatic retry. A retained launch intent is reported as `UNKNOWN` and must be reconciled; it is never reissued automatically.

The frozen inputs and producer evidence must live on durable storage. Do not place authoritative evidence under `/tmp` or `/var/tmp`. Every request/spec/config argument requires the expected SHA256 of its exact canonical bytes. The CLI prints only hashes and states, never the proposal or transcript. It does not read credentials. A `step` with no pending request, or one that only reconciles a captured response, can run without the accepted SDK installed. A new pending launch requires package metadata for both accepted distributions (`openai-codex` and `openai-codex-cli-bin`); metadata compatibility is an early gate and the SDK adapter still verifies the selected runtime binary identity. Direct `launch` likewise reuses a captured response without that runtime preflight.

## Explicit capture versions

Legacy v1/v2/v3 inputs remain valid within their original bounds. The linked v3 authorization was consumed by r9. Development proof does not authorize other live runs.

| Version | Provider cap | Normalized cap | Raw cap | Response frame |
|---|---:|---:|---:|---:|
| v1 | ≤64 KiB | original combined limit | ≤16 KiB | ≤256 KiB |
| v2 | 128 KiB | 64 KiB | ≤16 KiB | ≤256 KiB |
| v3 | 256 KiB | 64 KiB | ≤16 KiB | 512 KiB |
| profile v4 (bounded prompt) | 256 KiB | 64 KiB | ≤16 KiB | 512 KiB |

V3 must bind `sdk-producer-profile/v3`, `sdk-hosted-budget-policy/v3`, `sdk-agent-request/v3` and `sdk-agent-response/v3` together. UTF-8 byte bounds and response-frame bounds are checked independently. JSON escaping and metadata may exceed the frame even when the provider stream fits; exceeding a bound remains a rejection. V3 does not grant extra launches, retries, scientific execution or broader disclosure. Do not edit old campaign files to select it. Freeze a new source/spec/config/campaign tuple only under its approved budget.

V4 selects `sdk-producer-profile/v4` and binds `sdk-frozen-context-projection/v1` and its exact policy hash in the profile and model configuration. It keeps the V3 budget/request/response schemas and capture bounds. The complete immutable request and source evidence remain available to existing verifiers; only the model-facing prompt uses a deterministic presentation capped at 24,576 UTF-8 bytes. It retains candidate options, original object hashes, trial, verdicts, gate reasons and scalar metrics. Omitted detail is bound by hashes/counts. Unknown scope or overflow rejects without truncation. Presentation is proposal context, never new validated evidence.

The retained r9 second request produced a 24,010-byte V4 development prompt. Replaying the successful first request's two prompt-echo event shapes with that prompt produced 77,586 provider bytes and a 128,634-byte response frame. These are offline simulation results, not a prediction or qualification of a future live stream. See the [durable development proof](../../artifacts/hosted-evidence/a1-b2-20261012-01/control/followup-20261013-06/prompt-projection-development/README.md).

Actual r10 completed both SDK launches and both native scientific executions under this V4 profile. Live prompts were 12,281/23,942 bytes, provider streams 58,279/84,579 bytes and response frames 94,157/136,664 bytes. Both responses were accepted; the second request consumed its own first trial and verified original receipt. Controller and guard exited 0 with verified cleanup. Each scientific result was SOFT_REJECT; the frozen selection report remains SOURCE_INCOMPLETE and campaign scientific aggregate FAILED / NOT_EVALUATED. These results establish the bounded engineering handoff, while qualification remains NOT_QUALIFIED. See the [actual run and evidence](../../artifacts/hosted-evidence/a1-b2-20261012-01/control/followup-20261013-07/README.md).

The original proposed envelopes below retain their 2026-10-12 planning meaning. The completed r10 used a 2GiB full-job forecast inside the cumulative A 4GiB cap, original 32GiB physical host floor and 64MiB scratch quota. Its authorization is consumed; the placeholder commands describe interfaces and cannot restart a completed/cancelled request.

## Offline preparation and inspection

```sh
python scripts/sdk_campaign.py prepare \
  --request /durable/frozen/request.json --request-sha256 <64-hex-request-sha256> \
  --spec /durable/frozen/sdk-campaign-spec.json --spec-sha256 <64-hex-spec-sha256> \
  --evidence-root /durable/evidence/sdk

python scripts/sdk_campaign.py status \
  --request /durable/frozen/request.json --request-sha256 <64-hex-request-sha256> \
  --spec /durable/frozen/sdk-campaign-spec.json --spec-sha256 <64-hex-spec-sha256> \
  --evidence-root /durable/evidence/sdk

python scripts/sdk_campaign.py replay \
  --request /durable/frozen/request.json --request-sha256 <64-hex-request-sha256> \
  --spec /durable/frozen/sdk-campaign-spec.json --spec-sha256 <64-hex-spec-sha256> \
  --evidence-root /durable/evidence/sdk
```

`replay` requires a previously captured response; it only verifies the immutable response and reports its identities. `prepare` records the one-attempt reservation. Neither command invokes the model.

## Two explicit A1 launches

For a newly budgeted A1 campaign with two candidates, first freeze the successor SDK campaign spec, loader configuration and business input bundle using the existing trusted bundle process. The example below uses placeholder paths and hashes: source-bundle integration preparation is not a frozen actual campaign, and historical frozen files do not automatically satisfy the successor SDK profile. The accepted profile should request at most 900 seconds, 250,000 input tokens and 4,096 output tokens per launch, with one attempt per launch. These are requested and observed limits, not provider billing caps. The campaign allowance must authorize exactly the intended two launches.

```sh
python scripts/sdk_campaign.py start \
  --spec /durable/a1/sdk-campaign-spec.json --spec-sha256 <64-hex-spec-sha256> \
  --loader-config /durable/a1/loader-config.json --loader-config-sha256 <64-hex-config-sha256> \
  --protocol-root /durable/a1/protocol \
  --business-lock-root /durable/a1/business-locks \
  --evidence-root /durable/a1/sdk-evidence

# Each invocation can launch no more than the single currently pending request.
# Set expected growth from the complete retained run and use the same reservation
# in both the storage supervisor and CLI. The host storage policy/hash are explicit.
python scripts/hosted_storage_guard.py \
  --policy /durable/storage-policy.json --policy-sha256 <64-hex-policy-sha256> \
  --stage matrix --expected-new-bytes <complete-run-growth-bytes> -- \
  python scripts/sdk_campaign.py step \
  --spec /durable/a1/sdk-campaign-spec.json --spec-sha256 <64-hex-spec-sha256> \
  --loader-config /durable/a1/loader-config.json --loader-config-sha256 <64-hex-config-sha256> \
  --protocol-root /durable/a1/protocol \
  --business-lock-root /durable/a1/business-locks \
  --evidence-root /durable/a1/sdk-evidence \
  --expected-new-bytes <complete-run-growth-bytes>

python scripts/hosted_storage_guard.py \
  --policy /durable/storage-policy.json --policy-sha256 <64-hex-policy-sha256> \
  --stage matrix --expected-new-bytes <complete-run-growth-bytes> -- \
  python scripts/sdk_campaign.py step \
  --spec /durable/a1/sdk-campaign-spec.json --spec-sha256 <64-hex-spec-sha256> \
  --loader-config /durable/a1/loader-config.json --loader-config-sha256 <64-hex-config-sha256> \
  --protocol-root /durable/a1/protocol \
  --business-lock-root /durable/a1/business-locks \
  --evidence-root /durable/a1/sdk-evidence \
  --expected-new-bytes <complete-run-growth-bytes>
```

The second `step` only launches if the business service has issued a second pending request. If the campaign has no pending request, it resumes business processing without an SDK call. Captured-response recovery also works offline without the accepted SDK package, though step/resume still require their storage supervisor lease because deterministic business processing may run Qlib. Check state with `business-status`; use `resume` only as an explicit operation because it may execute the existing deterministic pipeline. Guard every `resume` with `hosted_storage_guard.py` in the same way and provide matching `--expected-new-bytes`. The guard requires the lease's complete growth reservation to cover that estimate and checks the output roots and current capacity. An SDK proposal remains a proposal and is subject to the existing admission and validation gates.

## 2026-10-12 original offline request and budget

The proposed new authority is two SDK launch opportunities using `0.162.1 + gpt-6.1-sol / medium`, one attempt each, no automatic retry, and no reissue of an unknown call. Each opportunity requests at most 900 seconds, 250,000 input tokens and 4,096 output tokens; transcript and raw semantic response caps are 65,536 and 16,384 bytes. These are application/requested observation bounds, not provider billing hard caps.

Reserve up to two trials, distinct candidates, scientific executions and Validation rounds. With the exact retained two expressions and ValidationPolicy, the [offline shape quote](../../artifacts/next-stage-offline-20261012/integration/a1-retained-shape-quote.json) is 18 units each, 36 units total. There is no allowance for fresh scientific re-execution; up to two explicit reconciliation resumes may reuse completed verified receipts. A stop proposal still references a candidate and may consume a trial before terminal processing, so a one-execution budget would be insufficient.

Proposed hard envelopes are two hours total wall, 4 GiB total new growth, one scientific worker, and the existing 32 GiB physical host-volume floor. They are proposed caps, not measured requirements or reserved capacity. Reuse immutable snapshot/view inputs read-only; account for any installation/input copies, execution output, replay and failure evidence before launch. Both A1 and B2 heavy work must use the same existing exclusive storage lease in sequence. If both complete and retain their proposed maximum growth, reserve 16 GiB cumulative growth rather than promising each job the same free space.

Before A1, produce a clean successor source binding and new SDK campaign/business bundle, frozen evidence root and guard policy, and verify the accepted interpreter installation. The current repository `.venv` has SDK/runtime 0.154.0 and cannot launch this profile. The [combined proposed request](../../artifacts/next-stage-offline-20261012/control/proposed-run-requests.json) is review material; it is not run authority. No real model or scientific operation was executed during this offline implementation.


## MLflow layout and retained execution failures

MLflow's file-store safety check rejects run paths containing an ancestor named `artifacts`. For a newly frozen two-step v2 campaign, the management controller can use `scripts/sdk_science_namespace.py:configure_execution_namespace(service, args, run)` around the existing `producer.step` calls. The caller first pins the helper bytes and provides the frozen workspace, metadata/spec/config hashes, helper hash and authorized deadline. Each original trial is dispatched at most once into an offline namespace. Its `/tmp/qlib-runtime/<execution_identity>` is a mount of durable storage; native exports keep their original durable paths. The scientific code and MLflow safety check are unchanged. This helper rejects the completed 2026-10-13 campaign and the original failed scientific identity. It is offline integration preparation, not a new run authorization or qualification.

The plain `step` examples above do not install this layout automatically. The reviewed management controller must apply it before the first scientific dispatch when its durable paths contain `artifacts`.

For the narrowly evidenced MLflow recorder-start failure, `scripts/finalize_retained_mlflow_failure.py` requires exact hashes of the original STARTED intent, reservation/baseline, controller exit/request/loaded records and management source. It forbids science execution, publishes the standard immutable `EXECUTION_FAILED / QLIB_EXECUTION_FAILED` receipt with a separate management-origin witness, then calls existing accounting settlement. It creates no ResearchResult, ValidationReport or native process exit. The historical operation has already completed; its sealed evidence is in `control/followup-20261013-04/offline-failure-finalization-01` under the current A1/B2 evidence root. It is not a general permission to recover unknown failures or retry a failed scientific run.
