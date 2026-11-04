# CI environment adoption

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
