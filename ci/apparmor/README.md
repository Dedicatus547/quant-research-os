# AppArmor candidate for the audited Ubuntu runner

This is a **proposal, not an installed policy**. `workflow.patch` is deliberately
not applied to `.github/workflows/ci.yml`. Installing/removing a host profile or
activating this patch needs the separate execution authorization described in
`artifacts/evolution-next-20261015/coord/ci-namespace-audit-handoff.md` (main repo).

## Policy and effect

`quantos-ci-bwrap.profile` attaches the named profile `quantos_ci_bwrap` to the
literal executable `/usr/bin/bwrap`; installation target is
`/etc/apparmor.d/quantos-ci-bwrap`. It uses ABI 4.0 and Ubuntu's documented
application-specific `flags=(unconfined)` / `userns,` exception pattern. See the
[Ubuntu 24.04 release notes](https://documentation.ubuntu.com/release-notes/24.04/).
It changes host policy and is intended to avoid the observed
`unprivileged_userns` capability denials during bwrap setup; runtime compatibility
remains unverified. It is **not** a capability allowlist
limited to `net_admin` and `setpcap`; those were the two observed denials, not a
proof of the complete minimal setup capability set.

Exec descendants can inherit this unconfined label, including the userns
exception. This proposal does not claim that AppArmor denies their capabilities
or prevents them from creating nested user namespaces. That inheritance is
needed by existing nested bwrap paths, and is a material scope of this exception.
An executable path attachment also is not a digest-based kernel rule: the workflow
checks the executable bytes before loading, but the rule itself attaches by path.
Any process able to execute that binary in this disposable runner is in scope.
Do not install this proposal on a shared or persistent general-purpose host.

Existing bwrap capability dropping, `PR_SET_NO_NEW_PRIVS`, namespaces, read-only
mounts, bounded tmpfs, role seccomp and PID cleanup remain responsible for their
original boundaries. This is source analysis, not new runtime proof. See
[bubblewrap v0.9.0](https://github.com/containers/bubblewrap/blob/v0.9.0/bubblewrap.c).
In this repo, `hosted_regression_runtime.ci_namespace_command` explicitly drops ALL
capabilities and can run tests which launch bwrap again;
`hosted_storage` also wraps managers in a PID namespace before nested launches.
`hosted_deployment.namespace_command` keeps its existing role-specific network
and seccomp policy. None of these sources is changed here.

The alternative upstream restrictive exec-child profile denies child
capabilities and has not been shown compatible with these nested paths. It is
not silently substituted for this candidate. See the
[versioned AppArmor example](https://gitlab.com/apparmor/apparmor/-/blob/v4.0.1/profiles/apparmor/profiles/extras/bwrap-userns-restrict).

## Bound sources and remaining identity gap

`sources.json` binds the profile, original workflow, audit logs, observed runner
tuple, package downloads and offline compiler inputs. Retained audit logs prove
the userns profile transition and the two capability denials. They do **not**
record the installed runner AppArmor package version or attachment inventory.
The extracted Noble parser package used offline was
`4.0.1really4.0.1-0ubuntu0.24.04.9`, not an observed runner package identity.
No package, policy or libc was installed on this development host.

The candidate workflow first prints the actual version and a read-only inventory
of loaded profile names/modes/attachments. Its install step is intentionally
disabled by an empty `APPROVED_APPARMOR_INVENTORY_SHA256`. Before activation, review
that inventory from the intended runner, bind its SHA256 in the patch, and obtain
the explicit execution authorization. Review every attachment that could match
`/usr/bin/bwrap` (including AARE patterns), all `quantos_ci_bwrap` names, and unknown
attachments; a conflict or unresolved match means **stop**, not unload/replace.
This is a human review prerequisite, not a claim that grep implements AARE.
The kernel exposes names/modes/attachments through
[AppArmor securityfs](https://github.com/torvalds/linux/blob/v6.17/security/apparmor/apparmorfs.c).

The patch refuses another image/kernel, bwrap digest/mode/owner, package version,
changed inventory, existing target (including symlinks), or reserved profile name.
It does not apt-upgrade AppArmor or disable the userns restriction. If the actual
runner package differs, retain its identity and recompile offline with that
specific package before revising the binding; do not relabel this parser proof.
Inventory paths include kernel-assigned profile IDs: a later boot can produce a
different hash and must not automatically inherit the earlier inventory approval.
The patch may therefore stop on a newer hosted image; it is not a runner pin or
a claim that the audited image can still be provisioned.

## Exact future operations (not executed)

After the identity/inventory review and authorization, check/apply the proposed
workflow change in the authorized integration workspace:

```bash
git apply --check ci/apparmor/workflow.patch
git apply ci/apparmor/workflow.patch
```

The patch contains the complete preconditions and installation commands. It uses
a root-owned staging file and a no-overwrite hard link to install the file, then:

```bash
sudo /sbin/apparmor_parser --config-file /dev/null --skip-cache --add /etc/apparmor.d/quantos-ci-bwrap
```

`--add` deliberately refuses a loaded name instead of replacing it. No existing
profile is modified. Parser options are documented in the
[Noble manual](https://manpages.ubuntu.com/manpages/noble/man8/apparmor_parser.8.html).
On this dedicated ephemeral runner, after all labelled descendants have exited,
an explicitly authorized reload of **this same candidate** is:

```bash
printf '%s  %s\n' 45aab8ec644fc7a5a4356eb1c5a633770f51276633d0065df7ad18f929201b8f /etc/apparmor.d/quantos-ci-bwrap | sudo sha256sum --check --strict
sudo /sbin/apparmor_parser --config-file /dev/null --skip-cache --replace /etc/apparmor.d/quantos-ci-bwrap
```

A changed profile needs its own reviewed successor digest; the command above does
not authorize arbitrary replacement. The always-run rollback step in the patch
checks its installation marker, exact file digest and *all* readable process
labels before `--remove` and deleting only this file. A live label, unreadable
process label (except a process which disappeared during inspection), changed
file, or parser error stops cleanup and preserves the failure for operator review.
It never kills unrelated processes or unloads another profile. Do not unload while
labelled descendants remain: removal alone does not prove that processes lost
their inherited permissions. A failure between linking and writing the marker
can leave the file; the job's runner must be discarded, or an authorized operator
must first prove ownership/identity and no live labels before manual rollback.

The equivalent explicit rollback, under those same ownership and no-live-label
preconditions, is:

```bash
printf '%s  %s\n' 45aab8ec644fc7a5a4356eb1c5a633770f51276633d0065df7ad18f929201b8f /etc/apparmor.d/quantos-ci-bwrap | sudo sha256sum --check --strict
sudo /sbin/apparmor_parser --config-file /dev/null --skip-cache --remove /etc/apparmor.d/quantos-ci-bwrap
sudo rm -- /etc/apparmor.d/quantos-ci-bwrap
```

If `--add` failed without loading the reserved name, retain that exit and inventory;
after confirming it is absent, remove only the matching file created by this job.
No previous profile backup/restore is needed: preexisting targets are refused.
No sysctl, setcap, role policy, coverage threshold, runner selection or scientific
predicate is changed. The ordinary namespace preflight and all existing checks
stay in the proposed workflow, with an always-run bounded audit log read.

## Verification and future acceptance

Completed locally: extracted-parser offline ABI4 syntax compilation, source/hash
checks, patch application check in memory, proposed YAML and shell parsing, and
guard/rejection fixture checks. See the retained `apparmor-candidate-01` commands,
actual exits and compiler result in the main repo reader artifacts. Syntax is
**not** kernel policy load, compatibility, namespace or security acceptance.
No Python application code changed; the shared interpreter's imported source
identity is retained separately. No full CI or research job was run locally.

Only after separate permission authorization, on the bound runner:

1. Save the exact checkout, OS/image/kernel, package/parser/bwrap identities,
   reviewed inventory, profile digest, load command/exit and loaded label. Run the
   unchanged native user/net/PID/tmpfs preflight; save its real exit and bounded
   audit, including on failure. Confirm restriction sysctls remain unchanged.
2. Exercise a non-root bwrap child and nested bwrap with explicit `--cap-drop ALL`.
   Observe inner/outer user/net/PID namespace IDs, UID/GID maps, profile labels,
   `CapInh/Prm/Eff/Bnd/Amb`, `NoNewPrivs`, seccomp state and bounded tmpfs behavior.
   Require `CapPrm/Eff/Inh/Amb=0`, `NoNewPrivs=1` after exec, isolated user/net/PID
   namespaces and the existing role-specific mount/network behavior. Check that
   an unrelated unprofiled executable still encounters the configured userns
   restriction. An unrelated unconfined executable may create a restricted
   userns; its mere successful creation is not proof the restriction was disabled.
3. Run existing affected tests, without relaxing their assertions:
   `tests/unit/test_hosted_manager.py`, `test_hosted_regression_capture.py`,
   `test_hosted_storage.py`, `test_hosted_storage_namespace.py`,
   `test_hosted_service_bootstrap.py`, `test_hosted_stage_graph.py` (all under
   `tests/unit/`). These cover actual child identity/wrong binding, bridge source
   rejection, PID descendants on success/timeout/EOF, lease/quota/cleanup and
   source-bound service/role behavior. Retain individual exits; a `true` success
   alone is insufficient. Verify loaded policy removal only after child cleanup.
4. After the fix is stable, M runs final-head strict Pyright and full
   pytest/coverage with the existing CI configuration once. Coverage85 remains;
   earlier 79.47% belongs to its old checkout, not this proposal. Do not use
   repeated full CI to discover policy setup failures.

No loaded-policy tests, installation/reload/rollback, nested-namespace acceptance,
new coverage measurement or final-head full CI are claimed by this proposal.
