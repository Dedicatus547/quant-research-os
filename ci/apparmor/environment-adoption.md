# CI environment adoption

## Observed successor tuple

Run `41789472035`, job `126439213904`, commit `6dd5969b` observed image
`20261101.360.1`, kernel `7.0.0-1017-azure` and AppArmor
`4.0.1really4.0.1-0ubuntu0.24.04.9`. The parser SHA256 is
`85e67b4ebc2559cc84c7d256d14890b8a7521e0278aedd544e13a3204a387d05`.
The bwrap and candidate profile bytes are unchanged; bwrap is root-owned mode
755, both restriction sysctls are 1 and its actual pre-namespace execution label
is unconfined. The complete stable inventory has 123 profiles, no additional
namespaces and no reserved name. Its 100 unknown attachment exports remain
unresolved; adoption uses the existing execution-scoped label guard, not an
assertion that unrelated attachments have been reconstructed.

The observed parser exactly matches the retained `.9` package and offline syntax
proof in `ci/apparmor/sources.json`; the retained parser, package and compiled
profile hashes were rechecked. This reuses that syntax proof only, without
claiming it proved the new kernel. The live job still compiles the unchanged
profile before loading, checks root namespaces/stacking, refuses replacement,
observes the loaded label, executes the original boundary checks and complete
tests, and performs the original cleanup. Only the four observed identity values
change. Full runtime acceptance remains contingent on those actual checks.

The initial successor's `static` and `offline-unit` jobs passed remotely; its
`isolated-tests` failed at the old identity guard as expected. That failure is
retained, not rewritten. Diagnostic originals and local hash checks are retained
under `artifacts/review-followup-20261104/engineering-01/`.

## Follow-up repair (2026-11-04)

The successor adds an independent `offline-unit` job for the explicitly inspected
file-only fixtures in `test_personal_memory.py` and `test_personal_scope.py`.
They exercise immutable JSON, references and budget accounting with synthetic
exit records; they do not start Qlib accounts, namespaces, acquisition or models.
Both files still run in the complete isolated suite. Its original steps, native
preflight and 85% coverage denominator are unchanged.

Format, lint and type checks now report independently even after another static
check fails. `typings/qlib/backtest/exchange.pyi` describes only the Qlib 0.9.7
surface consumed by the frozen adapter, without altering its runtime bytes.

Three historical source files retain their exact bytes under
`ci/frozen-style.sha256`: the two legacy execution dependencies are exempt only
from formatting; the completed confirm2 script also retains its enumerated lint
diagnostics. CI verifies the hashes before accepting those exceptions. Changed
bytes require review, not automatic expansion of the exception. This is explicit
historical style debt, not a claim that the original script is lint-clean. Other
files keep the existing rules; no scientific or safety check is waived.

The failed environment preflight now emits read-only OS/image/kernel, package,
binary/mode, sysctl, actual bwrap-label and grouped AppArmor inventory diagnostics.
Every probe reports its actual exit. The path cannot install policy or adopt an
environment, and the original failure stays failed. This fixes the absence of
evidence when image drift is detected before inventory collection. A hosted run
and review of its actual tuple are still required before changing accepted
identities; the old date is not replaced speculatively.

Local retained checks: `artifacts/review-followup-20261104/engineering-01/`.
Format/lint and strict type checks passed with the explicit historical style
policy above; 32 file-only tests passed. YAML/shell syntax and byte-for-byte
preservation of the original isolated job steps were checked. These results do
not claim hosted CI recovery, real market execution or forward observations.

## Original split and adoption boundary (historical)

2026-11-04 successor layout: `.github/workflows/ci.yml` has independent `static`
and `isolated-tests` jobs. Both use Ubuntu 24.04 and Python 3.11 with the existing
frozen uv lock. Static tools do not require AppArmor policy installation or user
namespaces. The test job retains the **entire** pytest command and its original
coverage threshold, exact reviewed tuple, inventory, profile load, boundary
checks and cleanup. Neither job depends on the other.

The Ubuntu label selects the supported OS family. It does not pin the hosted
image, kernel or installed parser. The existing image `20261012.334.1`, kernel,
package and binary hashes remain the sole accepted isolated tuple. A new image
will fail closed until its actual identities are adopted. No current hosted CI
run or new kernel acceptance is claimed by this change.

## Dependency classification and adoption path

| Responsibility | Runtime dependency | Placement |
|---|---|---|
| Ruff format/lint, strict Pyright | Frozen Python/development dependencies; no policy load | `static` |
| Pure contract and projection checks | Offline Python and small temporary files | Kept in full test job |
| Qlib native synthetic integrations | Frozen Qlib and local provider data | Kept in full test job |
| Hosted manager/storage/role probes | bwrap, nested user/net/PID namespaces, bounded tmpfs, seccomp, AppArmor | Mandatory original preflight |
| Fresh offline interpreter probes | Child Python plus inherited offline/process safeguards | Kept in full test job |
| Remaining tests with transitive/unknown isolation dependencies | Not classified as namespace independent | Kept in full test job |

This separates static feedback without guessing which collected tests import or
launch isolation code. No tests are excluded, re-marked, or counted as passed by
the static job; the full original coverage denominator remains in the isolated
job. Local targeted tests are implementation checks, not substitutes for it.

For a changed hosted tuple, use the existing read-only inventory/provenance
collectors (`identity_v2/collect.py`, `provenance_v4/`) on the intended disposable
runner before a policy write. Retain actual OS/image/kernel, package/parser and
bwrap bytes/mode/ownership, collection completion, namespaces and complete
profile attachment inventory. Review attachment conflicts and unresolved AARE
matches; retain a concrete successor identity binding. Compile the unchanged
profile against the actual parser before adopting a changed parser identity.
Then revise only the identities whose new evidence is accepted and exercise the
unchanged native preflight, nested namespace/capability boundaries, unrelated
denial and no-live-label cleanup. A date substitution, successful container, or
static-job success cannot perform that adoption. Frozen original sources and
proofs under this directory keep their original scope.

Remote execution and policy installation were not performed for the local W1
layout/projection implementation. No new authorization gate is introduced for
the remaining already authorized local engineering work.
