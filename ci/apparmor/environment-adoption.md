# CI environment adoption

## Observed AWS runner candidate

Run `41852381146`, job `126651806575`, commit `4ac2f099` exposed a different
hosted pool: image `20261018.96.1`, kernel `7.0.0-1014-aws`, Ubuntu 24.04.
The retained read-only diagnostics show the identical AppArmor `.9` package,
parser, bwrap and profile hashes, root-owned mode 755, both restriction sysctls
enabled and the actual non-root bwrap execution label `unconfined`. The stable,
complete grouped inventory has 124 profiles, no additional namespaces and 100
unresolved attachment exports. This is evidence for a candidate environment,
not a runtime isolation PASS or a reconstruction of unknown attachments.

The successor binds the three observed **image/kernel pairs** explicitly;
cross-combinations and unknown pairs fail. The new AWS kernel must pass the
unchanged live namespace/stacking, reserved-name, parser compilation, actual
loaded-label, nested namespace/capability, unrelated-denial and cleanup checks
on its own runner. Neither the old Azure proof nor the identical parser bytes
qualify that kernel. No historical proof or frozen verifier is rewritten.
Full tests and the original 85% coverage requirement remain mandatory.
The failed preflight did not load policy or execute tests. Its original log is
`artifacts/hosted-evidence/hs300-lowvol-forward-20261104-01/ci-isolated-4ac2f09.log`;
the independent static and offline-unit jobs passed.

## Second observed image with unchanged execution dependencies

Run `41815870682`, job `126526345689`, commit `86a615fd` failed before
policy installation because the host exported `ImageVersion=20261026.354.1`.
The runner's introductory banner instead said `20261025.353.1`; neither label
is treated as a proof of isolation. The retained diagnostic commands observed
the same kernel `7.0.0-1017-azure`, AppArmor `.9`, parser and bwrap SHA256,
root-owned mode 755, enabled restriction sysctls and actual unconfined bwrap
label as the first successor. The grouped inventory was complete, with no
additional namespace; unknown attachments remain unresolved.

The successor accepts the two explicitly observed image environment values.
It preserves the separate exact kernel, package, binary, profile, inventory,
namespace, actual-label and negative-boundary checks. An arbitrary new image
is still rejected. No historical runtime proof is relabelled: this failed job
did not install policy or run the isolated tests; acceptance requires the
next job's actual checks. Static and offline-unit jobs passed independently.
The test command additionally exports coverage JSON, and an always-run step
retains XML/JSON plus the original combined and subprocess coverage databases.
This permits missing-measurement diagnosis without repeating the hour-long
suite just to recover its files. The suite, branch denominator and 85% threshold
remain unchanged; local copies must be retained before artifact expiry.
The original diagnostic log is retained at
`artifacts/hosted-evidence/hs300-lowvol-forward-20261104-01/ci-isolated-86a615f.log`.

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
