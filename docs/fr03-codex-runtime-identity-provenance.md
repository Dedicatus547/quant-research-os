# FR-03 Codex runtime identity provenance correction

Date: 2026-09-24

Classification: **FROZEN_RUNTIME_IDENTITY_BINDING_ERROR**

This record corrects the interpretation of the immutable 0.156.1 runtime identity assertion. It
does not revise any runtime observation or account/read outcome.

## Provenance record

- Starting repository commit: `102db8922c05bc6fc58f81facd7a6b20c740d07f`
- Verifier implementation commit: `94ce87d85dcf73ade5efff95567caccd8552e330`
- Immutable record:
  `artifacts/diagnostics/codex-runtime-identity-provenance/v1/sha256-6768f0e935643c535e452a3fd311fbda3c552f0eb44c647d9d29588bb02565af/runtime-identity-provenance.json`
- Record SHA-256: `6768f0e935643c535e452a3fd311fbda3c552f0eb44c647d9d29588bb02565af`
- Offline verification: **PASS**

The verifier binds the official distribution digest, checks the wheel archive and `RECORD`, checks
the extracted executable bytes, computes the executable digest through Python `hashlib` and
`sha256sum`, verifies the referenced historical artifact hashes, and recomputes the matrix result
using the existing deterministic classifier. It uses no network, auth, provider, model, or runtime.

## Official package chain

The official PyPI release contains distinct Linux x86_64 distributions for glibc and musl. QuantOS
used Linux x86_64 with glibc 2.35 and Python 3.11, so the selected artifact is:

| Field | Verified value |
|---|---|
| Package | `openai-codex-cli-bin==0.156.1` |
| Distribution | `openai_codex_cli_bin-0.156.1-py3-none-manylinux_2_17_x86_64.whl` |
| Platform tag | `py3-none-manylinux_2_17_x86_64` |
| Distribution size | `136219225` bytes |
| PyPI published SHA-256 | `84a12567ca54ba6ae4ed755911c04e7cdf658315f8719963c8daa8592d8fe068` |
| PyPI trusted publishing provenance | GitHub Actions, `openai/codex`, commit `8a3c4ea3b5a7c0e92cf24dae46ec87629a26bb7f` |
| Publishing workflow | `.github/workflows/python-sdk-cli-release.yml` |
| Bundled executable member | `codex_cli_bin/bin/codex` |
| Executable type, mode, size | ELF64 Linux x86_64 regular file, `0755`, `284479848` bytes |
| Wheel `RECORD` entry | `sha256=Cy6TAdYQDd3aO51cgOuuqjovGWI4jy829rlqnwix8z8` |
| `RECORD` encoding and decoded digest | URL-safe Base64 without padding; decodes to `0b2e9301d6100dddda3b9d5c80ebaeaa3a2f1962388f2f36f6b96a9f08b1f33f` |

The wheel passed its archive CRC check and `RECORD` member/hash/size consistency checks. The
materialized executable matched the bytes at the archive member and the decoded `RECORD` digest.
The two independent SHA-256 calculations both returned:

```text
0b2e9301d6100dddda3b9d5c80ebaeaa3a2f1962388f2f36f6b96a9f08b1f33f
```

PyPI also publishes `openai_codex_cli_bin-0.156.1-py3-none-musllinux_1_1_x86_64.whl`, with a
different digest (`950627ab801703e061f2404105ed8216bb9728befbb09d853003a2678b9dbab2`). The manylinux
wheel was selected because the recorded QuantOS host uses glibc. The version string alone was not
used as binary identity.

## Three-way identity comparison

| Identity | SHA-256 | Equals official materialized executable? |
|---|---|---|
| Historical frozen value | `0b2e9301d6100dddda9b3d5c80ebaeaa3a2f1962388f2f36f6b96a9f08b1f33f` | No |
| B/C observed value | `0b2e9301d6100dddda3b9d5c80ebaeaa3a2f1962388f2f36f6b96a9f08b1f33f` | Yes |
| Official package executable | `0b2e9301d6100dddda3b9d5c80ebaeaa3a2f1962388f2f36f6b96a9f08b1f33f` | Yes |

The result is **FROZEN_RUNTIME_IDENTITY_BINDING_ERROR**. The previous `runtime_identity_verified =
false` values in B/C arose because the verifier compared the observed executable against the wrong
frozen identity. The official package bytes match the B/C observed hash. This evidence does not
show that the runtime observations were wrong.

After official package identity was established, the existing environment was checked. Two
materialized 0.156.1 package copies were found; both were `284479848` bytes and had the B/C observed
SHA-256. The historical artifact does not retain an absolute executable path, so this is a content
consistency check, not proof of which path the old process opened.

## Historical binding source

The earliest repository commit introducing the frozen literal is
`23c6a39f12c54cf3f393a7d266782f9f4e13b11a` (`test(fr03): record Codex 0.156.1 candidate
preflight`). The literal first appears in the candidate preflight document and verifier. The
preflight report `d41f4009d2bb47a6cea58bc2eb868fb42ce6627fd5c8748425e3f2c4f2a67945` contains it as
`candidate_runtime.runtime_binary_sha256`; the verifier then trusted that frozen literal. The
account-routing diagnostic later copied the same literal into its runtime-binding check.

The preflight report says the runtime hash was captured, but the committed evidence does not bind
it to an official platform wheel digest or PyPI publishing provenance. The exact earlier hash
generation path is not independently evidenced, so this correction classifies a historical
binding mismatch and does not assert that it was a transcription error.

## Reclassification and scope

The offline verifier applied the corrected identity assertion to the existing immutable A/B/C
observations in memory and passed those unchanged observations to the existing deterministic
classifier:

- Previous classification: `INCONCLUSIVE`
- Recomputed classification: `UPSTREAM_ACCOUNT_ROUTING_FAILURE`
- B/C initialization: `PASS`
- B/C `account/read`: `FAILED`, `InternalRpcError`, JSON-RPC `-32603`, identical error-message hash
- Observation fields changed: none
- P10 eligibility: remains false; P10 result remains `NOT_EVALUATED`

The record supersedes the **runtime identity assertion only**. It does not modify runtime
observations, account/read outcomes, RPC error results, scenario order, or the bytes/hashes of the
preflight and account-routing artifacts. Those references remain:

- Candidate preflight: `d41f4009d2bb47a6cea58bc2eb868fb42ce6627fd5c8748425e3f2c4f2a67945`
- Account-routing diagnostic v2: `1bc3433e953197df3d64bc4506dee3fd56c7613dc8998e65050a82b54377dfac`

No Scenario D or live P10 qualification ran. No model, provider, or account endpoint was called.
The canonical 0.154.0 pin remains unchanged. FR-03 remains **NO_GO**, and P14d-C remains
**BLOCKED_UNIMPLEMENTED**.

## Offline verification command

With the official wheel and materialized executable available locally, verify the record without
network or runtime access:

```bash
.venv/bin/python scripts/verify_codex_runtime_identity_provenance.py \
  --verify-record artifacts/diagnostics/codex-runtime-identity-provenance/v1/sha256-6768f0e935643c535e452a3fd311fbda3c552f0eb44c647d9d29588bb02565af/runtime-identity-provenance.json \
  --distribution /tmp/quantos-fr03-codex-provenance-v1/openai_codex_cli_bin-0.156.1-py3-none-manylinux_2_17_x86_64.whl \
  --binary /tmp/quantos-fr03-codex-provenance-v1/materialized/codex \
  --repo-root /home/zjw/quant-research-os
```

Official sources: [PyPI 0.156.1 release and file provenance](https://pypi.org/project/openai-codex-cli-bin/0.156.1/),
[publishing workflow at the attested commit](https://github.com/openai/codex/blob/8a3c4ea3b5a7c0e92cf24dae46ec87629a26bb7f/.github/workflows/python-sdk-cli-release.yml),
and [GitHub Actions publishing run](https://github.com/openai/codex/actions/runs/35811786542/attempts/1).
