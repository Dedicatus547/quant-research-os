# Successor after the runner identity stop

Candidate only. No host policy, active workflow or old candidate file is changed.
The parent candidate is B commit `91418c59e2a63f8e566241f3b2565f1c7a7d917e`;
M's actual read-only workflow base is `f9516424088dacab2977242b8d1a6ee1567ebba8`.
The main-repo instruction is
`artifacts/evolution-next-20261015/coord/ci-apparmor-identity-stop.md`.
Keep the previous `.9` compiler proof and `.8` archive404 evidence under their
original identities. `sources.json` here is a successor, not a replacement.

## Actual .8 compiler proof

The observed runner package is `4.0.1really4.0.1-0ubuntu0.24.04.8` (amd64).
Its retained generic parser version `4.0.1` alone did not identify that package.
The exact package was retrieved from the fixed-date
[official Ubuntu snapshot](https://snapshot.ubuntu.com/ubuntu/20260915T000000Z/pool/main/a/apparmor/apparmor_4.0.1really4.0.1-0ubuntu0.24.04.8_amd64.deb).
The [snapshot service](https://snapshot.ubuntu.com/) supplies historical archive
versions; no host APT configuration was changed. Current archive/security URLs
still returned404, and that new result and the earlier404 are retained separately.

| Input/result | SHA256 |
|---|---|
| .8 amd64 package (639830 bytes) | `190fa2ae7b76a52982bd796fbd25a067f7c42b8ec75c3797bfa67b694bf43297` |
| extracted .8 `sbin/apparmor_parser` | `ad542ad50c2ccd43cf1b1e8d242bc0329b6375cd49ff3bec1233b6ededfed94e` |
| package `abi/4.0` | `e510bb8f6788b45e48de2f859a6f94a7b8416cbac5a1051814cfce925fa911bd` |
| unchanged candidate profile | `45aab8ec644fc7a5a4356eb1c5a633770f51276633d0065df7ad18f929201b8f` |
| .8 offline compiled result | `af71d4a3b8aed8e8fd8b7aa0f6d4ae398855c3fc2fadecdd20243e78b4443f27` |

The actual .8 binary ran with the previously retained private libc/loader and
`--config-file /dev/null --skip-kernel-load --skip-cache`, its own include/ABI4
and `--kernel-features` input. Version/help/compilation exited0. The output happens
to equal .9's output; neither proof is relabelled. This proves offline syntax,
not kernel loading or runner behavior. The runner parser's byte digest has not
been collected yet; the proposed loading step requires the exact .8 digest above.
Package download authority is official HTTPS plus retained SHA256, without a new
APT signature-chain claim. Source archives were also checked against the retained
DSC SHA256 entries, without claiming that the DSC signature was verified.

## What the 100 unknown values mean

Each old export has123 paths for each of name/mode/attach, and100 literal
`<unknown>` values. Sorting all paths and values independently destroyed the
association. It is impossible to reconstruct which100 directories had that value
or their individual modes from those exports. Directory names are investigation
clues, not a substitute for a grouped record or loaded-policy source identity.

The [Linux v6.17 AppArmor export implementation](https://github.com/torvalds/linux/blob/v6.17/security/apparmor/apparmorfs.c)
returns the textual xmatch string if retained; otherwise it emits `<unknown>`
when an attachment DFA exists, and falls back to the profile name when it does
not. Thus this sentinel is not missing data, no attachment, or proof of a wildcard.
An explicit literal attachment can also have a DFA without exported source text.
The actual .8 source package's parser serializer and Ubuntu patch series retain
that DFA serialization path. The .8 package ships explicit named attachments,
for example `1password` attached to `/opt/1Password/1password`.

This explains a concrete source of these exports, not a proven per-profile
attribution of all100 values to the packaged examples. The exact Ubuntu Azure
kernel source/binary correspondence, loaded-policy hashes and installed source
bytes were not in the old logs. Upstream v6.17 is a reference for interpreting
the sentinel; it is not falsely labelled as the complete Azure kernel source.
**All100 remain unresolved for `/usr/bin/bwrap` conflict review.**

`collect.py` replaces the lossy export with one JSON record per profile directory,
including nested profiles: required name/mode/attach values and their byte hashes;
optional loaded `sha256`, `raw_sha256`, `raw_abi`; and raw_data/raw_hash/ABI symlink
metadata. Missing, empty, unreadable, oversized, invalid and literal unknown fields
stay distinct. It reads no raw_data binary and no policy-management interface.
Raw metadata availability depends on kernel export/hash configuration and access;
absence is recorded, never converted to a no-match. There is no direct textual
xmatch read API assumed here. Profile and raw-data hashes have different scopes
and cannot simply be equated to a source file hash.

Policy revision is read before/after; failures, a change, unexpected symlinks,
additional namespaces or exceeding512 profiles make collection incomplete. Reads
are bounded to8192 bytes per metadata field. This is read-only observation, not an
atomic kernel snapshot or an attachment verifier. It always reports UNREVIEWED
and `load_authorized=false`, including when collection itself succeeds.

## Concrete next steps and authorization differences

1. Review/apply **only** `readonly-workflow.patch` against the stated M base. It
   replaces the previous inspection step and adds no install/remove or research
   work. It records the actual parser path/hash, version, bwrap and collector hash,
   emits grouped JSON and its exact digest, and preserves the collector's exit.
   All other existing steps, namespace failure, coverage and safety checks remain.
   This B turn prepares the patch; it does not push or start a new runner job.
2. M reviews that actual grouped output. For each unknown, bind the loaded hash
   or exported raw policy, actual installed policy source/includes/tunables and
   parser/features/config provenance. Read-only follow-up commands can include
   `dpkg-query -S /etc/apparmor.d/1password`, `sha256sum` of the actual source and
   included files, and the actual .8 parser's `--preprocess --skip-kernel-load
   --skip-cache --config-file /dev/null` on that source. A source header or package
   version alone does not prove it is the loaded policy. Reproducing serialized
   bytes/hash requires matching compilation settings and the correct profile/raw
   hash scope. If binary export or provenance is absent, keep it unresolved.
   Do not implement an approximate AARE matcher or a new policy decompiler to
   approve a guess. Exact/AARE/xattr attachment ambiguity means stop.
3. `load-workflow.patch` is a separate **unapproved** successor proposal against
   the same M base, not a patch to stack on `readonly-workflow.patch`. It uses
   the same unchanged profile/target/installer/rollback as the reviewed candidate,
   changes the package binding from .9 to actual .8, adds exact parser-byte
   verification and binds the new grouped JSON bytes. The inventory digest stays
   empty and rejects loading. No legacy hash or unknown is approved by this file.
4. The approved scope explicitly fixed .9 and the old raw export. Moving to .8
   and a grouped schema is a material binding revision for M to review and, for
   loading outside those fixed premises, to seek explicit successor authorization.
   The original authorization is not silently transferred. The raw JSON still
   contains kernel-assigned IDs and revisions; another job can differ and must
   stop. This proposal does not strip IDs or introduce semantic-equivalence
   approval. If exact cross-job binding is impractical, that remains a concrete
   execution limitation; a different approval method needs a separately reviewed
   design/scope, not repeated full CI attempts or automatic trust of new hashes.

No load can proceed until both identity and all attachment questions are resolved
and the correct job's exact inventory is explicitly accepted within valid scope.
The existing named-profile descendant/userns exception and its material security
impact are unchanged; see [original candidate](../README.md). No global sysctl,
setcap, elevated bwrap, isolation bypass, runner change or paid resource is proposed.

The previously specified native/nested bwrap, capabilities/NoNewPrivs, namespaces,
mounts, seccomp/network, PID cleanup, wrong-source rejection, lease/quota tests and
final strict Pyright/full pytest/coverage85 remain future acceptance requirements.
They were not run under a loaded profile here. Local checks cover only .8 offline
syntax, source hashes, the two inactive patches, the grouped collector's small
synthetic positive/negative cases and actual worktree import identity. No full CI,
training, cohort, backtest, acquisition of research data or LLM call is involved.
