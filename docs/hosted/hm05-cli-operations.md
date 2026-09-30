# HM-05 hosted CLI operations

Date: 2026-09-30. Assigned implementation model: `gpt-6-sol`; reasoning effort:
`medium`. Implementation attempt: 1. Observed usage and cost: `unavailable`.
This is CLI component evidence, not deployment, source, or live qualification.

The CLI calls only `HostedUnixClient` over the restricted Unix channel. The service
manager must first register the immutable spec and frozen inputs. `start` accepts
the registered spec's explicit content hash and its campaign hash; the research
channel cannot register specifications, choose inputs, or read service paths.
The campaign hash on every command scopes channel authorization. `latest`,
`current`, `auto`, upper-case and malformed hashes are rejected locally.

The client configuration is a canonical `hosted-client-configuration/v1` file.
Its default host-visible location is `/install/hosted-client.json`; the manager
must freeze it in the read-only install inventory before launch. `--client-config`
selects another manager-provided host-visible file. It contains only socket path and channel
policy. The service manager provides a 32-byte capability through a private
inherited descriptor; pass only its integer with `--capability-fd`. The CLI
consumes and closes that descriptor. Never place capability bytes in arguments,
environment variables, configuration, shell tracing, logs, or evidence.

```text
quantos hosted start --spec <spec-sha256> --campaign <campaign-sha256> --capability-fd <fd>
quantos hosted pending --campaign <campaign-sha256> --capability-fd <fd>
quantos hosted request-export --campaign <campaign-sha256> --output <new-local-file> --capability-fd <fd>
quantos hosted submit --campaign <campaign-sha256> --request <request-sha256> --response <local-file> --capability-fd <fd>
quantos hosted resume --campaign <campaign-sha256> --capability-fd <fd>
quantos hosted status --campaign <campaign-sha256> --capability-fd <fd>
quantos hosted cancel --campaign <campaign-sha256> --request <request-sha256> --capability-fd <fd>
```

`pending` prints only request identity and expiration. `request-export` obtains
the canonical pending request from the service and writes it to an explicitly
named new local regular file with mode `0600`; it never overwrites an existing
path. The output path is not sent to the service or echoed to stdout. Both
input and output paths reject symlinks in every parent component; response and
client configuration inputs also reject hard-link aliases. `submit` opens a local regular
file and reads at most the channel response
cap plus one byte. It sends those bytes, never the path. The extra byte allows
the shared service protocol to record an incomplete-prefix rejection and charge
the appropriate reservation for an oversized response. FIFO/device paths are
rejected without blocking. Local errors and channel failures emit fixed JSON
reason codes, never raw exception text, response content, or capability bytes.

`start` and `resume` advance to a persisted waiting point or terminal state.
`submit` returns the durable receipt. `status` and `pending` are read-only.
Receipt replay, budget, PIT, admission, execution and recovery semantics remain
in the common application/protocol service; the CLI has no local fallback.

The targeted tests exercise dispatch, explicit identities, bounded local reads,
request export, private descriptor consumption, safe errors, and existing CLI
regression. They do not establish Q07/Q11 or live qualification; those require
the separate deployed identity and source probes in the frozen acceptance plan.
