# Disposable CI runner execution guard

The active workflow uses the existing `quantos-ci-bwrap.profile`, unchanged at
SHA256 `45aab8ec644fc7a5a4356eb1c5a633770f51276633d0065df7ad18f929201b8f`.
It grants the documented Ubuntu application-specific user namespace exception to
`/usr/bin/bwrap` and its inherited descendants on the exclusive disposable CI
runner. It is not a two-capability allowlist. Global sysctls, file capabilities,
role seccomp, capability dropping, NoNewPrivs and scientific predicates remain
unchanged. It must not be installed on a shared or persistent development host.

The user's 2026-10-17 takeover authorization covers the successor CI repair,
necessary verification and publication. Earlier `.9` and provenance-v2/v3/v4
proposals, failures and authorization records retain their historical scope.
The active guard binds the actually observed `.24.04.8` parser bytes, bwrap bytes,
profile bytes, Ubuntu/image/kernel and file identity already independently
verified in those records. A changed tuple is rejected before policy writes.

## Actual execution, rather than guessed source correspondence

The previous source inventories are retained. Their 100 `<unknown>` attachment
exports and historical source/compiler correspondence are **not** declared
resolved. A complete reconstruction of every unrelated system profile is not an
engineering acceptance requirement for this execution-scoped CI exception.

Instead, before any policy write, `runtime_guard.py` executes the fixed non-root
bwrap with an empty pipe passed to `--args`. In the reviewed
[bubblewrap 0.9.0 argument parser](https://github.com/containers/bubblewrap/blob/v0.9.0/bubblewrap.c)
that blocks while reading the argument data, before namespace creation. Popen's
exec-error handshake has completed. The parent reads the live child's kernel
AppArmor label, UID and user/net/PID namespace identities. It requires the exact
`unconfined` label, the ordinary job UID, and unchanged namespaces. An existing
profile transition, unexpected label, read error, early exit or byte mismatch
stops installation. The child is terminated/reaped before releasing the pipe.
This is a measurement of this executable in this job's actual execution context,
not an AARE matcher, decompiler or approval of other profiles or execution paths.

The workflow also requires the complete root-namespace inventory, no stacking,
no reserved profile/file, original userns restriction sysctls and no overwrite.
Installation uses the original staged root-owned file and `--add`, never replacing
an existing profile. The same non-root exec observation must then show exactly
`quantos_ci_bwrap (unconfined)`. The original native namespace preflight follows.

The additional live boundary check uses non-root, nested bwrap with the original
`--cap-drop ALL` and user/net/PID isolation, a read-only root and bounded tmpfs.
It requires zero effective/permitted/inheritable/bounding/ambient exec capabilities
and NoNewPrivs=1 at both depths. An unrelated executable must still be refused
namespace setup or receive EPERM for net_admin in its private network namespace.
Role-specific seccomp, source binding, manager/storage and cleanup assertions are
then exercised by the unchanged full offline test suite; those tests and the
85% coverage threshold are not skipped or weakened.

Always-run cleanup retains audit output, verifies ownership marker and file hash,
requires no live labelled descendants, unloads only this job's reserved profile,
removes only its own file, and checks that sysctls and the unconfined bwrap label
are restored. Any failure is a real CI failure. It never removes another policy.
The runner is disposable if interrupted before cleanup can finish.

The original push and PR triggers remain. Per-branch concurrency cancels only
superseded duplicate CI, so the final PR head runs the complete required checks.
Cancelled runs are not reported as passes. No scientific evidence is generated
or requalified by these observations or by CI acceptance.
