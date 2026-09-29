# FR-03 Codex account-routing diagnostic v2

Date: 2026-09-24  
Starting implementation commit: `18cb6770ec3a3520ad5fad5a8bae1005b9991c32`  
Candidate preflight checkpoint: `23c6a39f12c54cf3f393a7d266782f9f4e13b11a`

## v1 publication failure

The v1 runner completed one ephemeral A, B, and C observation each, then refused publication.
Its results were not written as an immutable artifact. Under the fail-closed rule, all three v1
outcomes remain **UNKNOWN**. No terminal output, shell history, temporary directory, or elapsed
time is used to reconstruct them. The v1 publication failure was an instrumentation failure, not a
Codex runtime result.

The scanner searched serialized JSON bytes for substrings. These markers can be valid JSON field
names, so the check conflated a sensitive name with a sensitive value:

| v1 marker | False-positive path |
|---|---|
| `access_token`, `refresh_token` | Bare substring match; keys such as `access_token_presence` and `refresh_token_presence` trigger. |
| `"tokens"` | Exact JSON property match; a safe classification under a property named `tokens` triggers, and the scan cannot tell a classification from a nested raw token object. |
| `"OPENAI_API_KEY"` | Exact JSON property match. `normal_profile_audit.parent_managed_environment_presence.OPENAI_API_KEY` is intentionally `PRESENT` or `ABSENT`, so this was a deterministic v1 false positive. |
| `"accessToken"`, `"refreshToken"` | Exact JSON property match; camel-case protocol/schema property names trigger regardless of their values. |
| `"Authorization"`, `"Cookie"` | Exact JSON property match; safe header-presence metadata under those names triggers regardless of its value. |
| `Authorization:`, `Cookie:`, `Bearer ` | These byte sequences do not match ordinary JSON property syntax because JSON places a quote before the colon. They can still false-positive inside a harmless string value. |
| `TUSHARE_TOKEN=`, `sk-proj-`, `ghp_`, `gho_` | Value-like substrings can occur in a harmless string or unusual property name; the serialized-byte scan had no field/value context. |

No v1 artifact exists. v1 A/B/C are not runtime failures and are not evidence for or against
0.156.1.

## v1 persisted-field audit

The runner can publish three JSON files. The inventory below is the union of fields across normal,
timeout, worker-failure, and successful scenario paths.

### `account-routing-report.json`

Top-level fields: `schema_version`, `run_id`, `created_at_utc`, `implementation_commit`,
`candidate_runtime_candidate_id`, `candidate_sdk_version`,
`candidate_runtime_package_version`, `model_scope`, `source_audit_sha256`, `matrix_sha256`,
`normal_profile_audit`, `diagnostic_classification`, `p10_eligible`, `p10_started`, `p10_score`,
`matched_command_lifecycle_count`, `canonical_pin_changed`, `p10_contract_changed`,
`fr03_status`, `p14d_c_status`, and `artifact_file_hashes`.

`normal_profile_audit` contains: `normal_codex_home_used_directly`, `normal_auth_file_sha256`,
`normal_config_file_present`, `normal_config_sha256`, `config_projection_sha256`,
`config_projection_complete`, `config_projection_fields`, `normal_config_bootstrap_fields`,
`credential_store_mode`, `provider_selection_classification`, `auth_projection_classification`,
`auth_mode_classification`, `api_key_credential_present`,
`selected_account_workspace_id_presence`, `selected_account_workspace_id_sha256`,
`workspace_metadata_entry_count`, `normal_user_mcp_config`, `normal_user_project_config`,
`normal_user_model_config`, `parent_managed_environment_presence`, and
`sdk_host_environment_allowlist`.

`normal_config_bootstrap_fields` has the keys `chatgpt_base_url`, `model_provider`,
`model_providers`, `requirements`, and `cli_auth_credentials_store`; each value is only
`PRESENT` or `ABSENT`. `parent_managed_environment_presence` has the keys `CODEX_API_KEY`,
`CODEX_HOME`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `CODEX_MANAGED_CONFIG_PATH`,
`CODEX_MANAGED_REQUIREMENTS_PATH`, and `CODEX_REQUIREMENTS_PATH`; each value is only `PRESENT`
or `ABSENT`. The two API-key property names are intentionally retained as safe presence metadata.
The account/workspace identifier is never persisted, only its presence and SHA-256. The API-key
credential field is a boolean classification, not key material. `sdk_host_environment_allowlist`
contains the fixed names `CODEX_HOME`, `LANG`, `PATH`, and `TZ`.

### `account-routing-matrix.json`

Top-level fields: `schema_version`, `run_id`, and `scenarios`. Scenario fields are:
`scenario_id`, `requested_runtime_version`, `expected_runtime_candidate_id`, `sdk_version`,
`runtime_package_version`, `app_server_version`, `reported_app_server_version_sha256`,
`runtime_binary_sha256`, `runtime_identity_verified`, `platform`, `codex_home_mode`,
`codex_home_entry_classification`, `auth_projection_sha256`, `config_sha256`,
`config_projection_complete`, `config_projection_fields`, `selected_account_workspace_id_presence`,
`selected_account_workspace_id_sha256`, `initialize_status`, `initialize_elapsed_ms`,
`account_read_status`, `account_read_elapsed_ms`, `rpc_method`, `rpc_error_code`, `rpc_error_type`,
`rpc_error_classification`, `rpc_error_message_sha256`, `rpc_error_message_length`,
`worker_error_type`, `worker_stderr_sha256`, `worker_stdout_sha256`, `account_presence`,
`workspace_routing_schema`, `workspace_routing_result`, `accounts_check_attempted`,
`accounts_check_observability`, `explicit_account_read_call_count`, `thread_start_count`,
`turn_start_count`, `provider_request_count`, `elapsed_ms`, `host_environment_names`, and
`request_count_basis`.

No scenario field stores a raw RPC error, response body, request body, header, or credential. Error
messages and worker streams are reduced to hashes, error class/code, a bounded classification, and
message length. `app_server_version` is public runtime identity text, bounded to 160 characters and
an allowlisted character set; its hash is retained independently.

### `upstream-source-audit.json`

Fields: `schema_version`, `upstream_source_commits`, `reviewed_source_paths`, `upstream_pr`,
`findings`, `error_mapping`, `p10_contract_change`, and `normalizer_or_evaluator_change`. This file
contains fixed source-review notes and version/path metadata, not runtime or user text.

### User-derived and exception-derived values

The safe profile projection reads the normal auth/config files but persists only file/projection
hashes, field names, presence/classification enums, and a selected workspace ID hash. The temporary
runtime home receives the auth bytes only for the duration of the scenario and is removed when the
scenario exits. Config values are projected only from the three bounded bootstrap keys and are not
copied to the artifact.

`app_server_version` is runtime-reported text and is length/character bounded before retention.
Exception class names are reduced to a bounded identifier. Raw exception messages are used only in
memory for allowlisted classification and hashing; worker stdout/stderr are hashed. No raw
exception text is retained.

## v2 secret validation

The shared SDK-neutral implementation is `quantos.security.validate_secret_free`. Publication
validates the structured report, matrix, and source audit before writing. Offline verification
parses each canonical JSON object and calls the same validator. A rejection contains only the
artifact filename, JSON path, rule ID, and value classification, for example:

```text
SECRET_VALUE_DETECTED file=account-routing-matrix.json json_path=$.normal_profile.auth_value rule=RAW_CREDENTIAL_VALUE value_classification=STRING_VALUE
```

Sensitive property names are allowed only when their values are a safe presence/classification or
a valid SHA-256 digest. All other values under credential-bearing fields are rejected. Bounded
string scanning rejects bearer and cookie/authorization headers, credential assignments, access or
refresh-token assignments, OpenAI/GitHub/JWT-like token values, and oversized text. Known raw
exception/body fields are rejected by field name. The scan never includes a rejected value in its
diagnostic.

The v2 schema identifiers are:

```text
fr03-codex-account-routing-diagnostic/v2
fr03-codex-account-routing-matrix/v2
fr03-codex-account-routing-source-audit/v2
fr03-codex-account-routing-verification/v2
```

The artifact root and run ID also contain `v2`. v1 source history is preserved in git; no v1
artifact is present to verify or reinterpret.

## Offline implementation evidence

| Check | Result |
|---|---|
| Allowed classifications, field names, and hashes | `PASS` |
| Credential-value rejection matrix | `PASS` |
| Synthetic A PASS / B FAILED / C PASS artifact round trip | `PASS` |
| Matrix/report/source/secret/hash tampering | `PASS` |
| Full engineering gates | `PASS`: 600 tests; 85.12% coverage; Ruff format/check and Pyright pass |
| Corrected offline implementation commit | recorded in repository history after the live attempt |

## Fresh v2 runtime evidence

The fresh matrix is started only after all offline gates pass and the implementation commit is
clean. Each of A, B, and C is invoked once. D is invoked once only when B fails, C passes, and the
only projected difference is `chatgpt_base_url`, the single bootstrap prerequisite supported by
the reviewed upstream source. P10 remains unstarted unless isolated candidate B passes
`initialize` and `account/read` with verified runtime identity.

| Evidence | Result |
|---|---|
| Implementation commit used by the one matrix attempt | `ff0a9cb7ea52bfe1a9b84aeb8d450c25caf7f83d` |
| A | `UNKNOWN` (not persisted) |
| B | `UNKNOWN` (not persisted) |
| C | `UNKNOWN` (not persisted) |
| D | `UNKNOWN` whether invoked; no row evidence retained |
| `accounts/check` observability | `UNKNOWN` |
| Diagnostic classification | `UNKNOWN` / not derivable |
| Immutable artifact SHA-256 | none; publication rejected before writing |
| Offline verification | not possible; no artifact exists |
| Host adaptation / P10 eligibility / P10 run | no / no / no |
| FR-03 / P14d-C | `NO_GO` / `BLOCKED_UNIMPLEMENTED` |

## First v2 publication attempt: instrumentation defect

The single v2 matrix process reached publication after its predeclared scenario sequence, but the
shared validator rejected a fixed source-audit sentence at
`$.findings[14]` with `RAW_TOKEN_ASSIGNMENT`. The sentence says the public SDK call sets
`refreshToken=false`; the scanner treated the safe boolean `false` as credential material. This is
another validator false positive, not a runtime failure.

No artifact was published from this attempt. As required, no in-memory row, stdout, temp directory,
or elapsed time is used to recover its outcomes. A, B, and C are **UNKNOWN** for this attempt. D's
invocation is also **UNKNOWN**:
the runner can conditionally invoke D from the ephemeral A/B/C results, and that condition cannot
be reconstructed now. `accounts/check` observability, diagnostic classification, and artifact hash
are therefore unavailable. Offline verification is not possible without an artifact. P10 did not
start and is ineligible; no score exists. The validator now treats explicit boolean/null assignment
classifications as safe while continuing to reject credential-like values. The correction passed
offline gates only; the v2 runtime matrix was not retried.

## Published v2 evidence and superseding identity interpretation

A separate immutable v2 diagnostic was subsequently published and verified. Its artifact hash is
`1bc3433e953197df3d64bc4506dee3fd56c7613dc8998e65050a82b54377dfac`. This artifact's original
classification is `INCONCLUSIVE`: its B/C `runtime_identity_verified=false` assertions were based
on the historical frozen hash that did not match the official `0.156.1` executable.

The superseding official provenance record
[`6768f0e935643c535e452a3fd311fbda3c552f0eb44c647d9d29588bb02565af`](fr03-codex-runtime-identity-provenance.md)
verifies the executable identity and recomputes the classification over the unchanged observations.
It supersedes only the runtime identity assertion; it does not edit the diagnostic bytes, scenario
sequence, runtime observations, or account/read results.

| Scenario | Runtime identity after superseding provenance | Initialize | `account/read` | Bounded result |
|---|---|---|---|---|
| A — isolated 0.154.0 | `VERIFIED` | `PASS` | `PASS` | `accounts/check` false |
| B — official isolated 0.156.1 | `VERIFIED` | `PASS` | `FAILED` | `InternalRpcError` / JSON-RPC `-32603` / `UNKNOWN_INTERNAL` |
| C — 0.156.1 safe normal-profile projection | `VERIFIED` | `PASS` | `FAILED` | same error classification and bounded message hash as B |

Each retained scenario has `thread_start_count=0`, `turn_start_count=0`, and
`provider_request_count=0`. The offline reclassification is
`UPSTREAM_ACCOUNT_ROUTING_FAILURE`. The exact internal failure subtype remains `UNKNOWN`; the
retained evidence does not establish a routing timeout, duplicate workspace, or origin mismatch.
No P10 run started: candidate P10 is `NOT_EVALUATED`, canonical FR-03 remains `NO_GO`, P13 remains
`NOT_EVALUATED`, and P14d-C remains `BLOCKED_UNIMPLEMENTED`.
