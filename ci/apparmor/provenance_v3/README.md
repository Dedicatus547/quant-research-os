# B provenance and cross-job binding proposal

**Unactivated candidate, no policy-loading authority.** Base is the actual M head
`3d5326ee86e9154224225e8baa7a2569852e336a`. B fast-forwarded only as expressly
instructed by `coord/b-apparmor-provenance-request.md`; earlier candidates/proofs
remain unchanged. The real .8 parser, offline compilation, prior7 cases and
actual parser-byte identity are reused, not rerun or relabelled.

## What the next read-only job would collect

`source-plan.json` proposes123 full parent/child identities,115 root source
candidates,260 exact policy/include/tunable/ABI file candidates and3 specific
include directories. It was prepared from the actual retained PR inventory and
known .8 packaged templates. Root filename aliases and template include closure
are **investigation candidates**, not verified loaded sources. Generated
`docker-default` has no proposed persistent source. Actual changed source may
need additional dependencies; unresolved closure stays unresolved. The source
plan includes the reference hashes, not copied package contents labelled runner
files. Duplicate leaf names never overwrite each other.

| Material | Acquisition and use | Remaining limitation |
|---|---|---|
| Actual policy sources/includes | Exact plan paths under `/etc/apparmor.d`, bytes/base64/hash/owner/mode; bounded traversal of3 named tunable include directories | Existence or matching packaged bytes does not prove loading; optional/missing/error records stay visible and conservatively make capture incomplete |
| Current parser settings | `/etc/apparmor/parser.conf`, `/etc/default/apparmor`, exact `/usr/lib` AppArmor unit and two loader helper files | Not proof of historical command line, service overrides, environment or cache selection; no arbitrary service drop-ins are read |
| Kernel features and namespace | Bounded `/sys/kernel/security/apparmor/features` tree and `.ns_name/.ns_level/.ns_stacked/.stacked` | Current features, not the features used by a past compiler; no raw_data binary or policy-management interface is read |
| Parser/bwrap | Hash/size/UID/GID/mode at `/usr/sbin/apparmor_parser` and `/usr/bin/bwrap`, without copying binary contents | Independent .8 package proof and actual M byte checks retain their original sources; no package is downloaded/upgraded here |
| Package provenance | `dpkg-query --search` for readable selected source/settings/binary paths, then `--show` only their validated owner package names | Records installed ownership/version/architecture, not signed archive origin or proof which source was loaded; archive origin stays UNRESOLVED |
| Raw inventory | Original v2 bytes and SHA256 retained, also embedded losslessly as base64; original job JSON/errors remain untouched | Collection completeness is not source correspondence or attachment acceptance |

File reads use directory descriptors and `O_NOFOLLOW` for every component,
nonblocking opens, regular-file checks and before/after size/mtime/ctime checks.
There is no general filesystem search or environment dump. Unknown include paths
are not followed outside the reviewed plan. This is a per-file observation, not
an atomic source-filesystem snapshot. Policy revision is rechecked after source
acquisition; changes refuse completeness. The existing v2 collector is reused
without changing its behavior or historical evidence.

Limits:512 file attempts and512 directory entries;64KiB per text file,4MiB total
file input (one extra byte detects overflow); binary hashing shares that total.
Input inventory is at most1MiB, output report at most12MiB. Each of the two fixed
dpkg commands has10s,256KiB per scratch output file,256KiB retained stdout and8KiB
stderr, with truncation/errors retained and refusal. Scratch is not evidence;
bounded returned bytes go into the report. Missing, denied, symlink, nonregular,
oversized, changing or exhausted resources remain errors, never “no attachment”.
No token, user home, research data, raw prediction file or raw_data binary is a
collection target. The actual runner source report has **not** been obtained yet.

## Executable cross-job proposal

`binding.py` supplies a versioned content projection and comparison, with no
policy installer, approval writer, AARE matcher or decompiler. Its rules are new
and must not be retroactively attributed to prior authorization:

- Validate the complete v2 schema, field bytes/hashes, counts, mode, unknown count,
  collection/errors/namespace state and revision stability. Reject missing fields,
  duplicate directories and duplicate full identities. Identity is the ordered
  root-to-child name lineage, not a leaf name or guessed filename.
- Directory structure must alternate profiles/name.ID with present parents.
  Preserve every mangled directory prefix and full name lineage. Only numeric
  allocation IDs become execution-local witnesses; they remain in the original.
- All3 raw links must be canonical relative links to the correct raw_data/ID
  group and field. Refuse escapes, inconsistent target groups, hash/ABI conflicts.
  Preserve the group membership graph, profile hash, raw hash and raw ABI. Splits,
  merges or moved children are drift, even when leaf names coincide.
- Preserve source bytes/hashes/mode/ownership, plan/dependency listings, settings,
  all features, parser/bwrap hashes, package metadata, image/kernel, namespace and
  tool source hashes. Reject changed namespace/stacking, invalid source bytes/hash,
  missing image/kernel and unsupported inventory fields. Incomplete reports
  cannot match an explicit digest. Unknown sources cannot gain approval.
- Before/after revision values must agree within each job and through source
  acquisition. The exact revision numbers, raw JSON formatting/hash and reader
  counters are retained witnesses, not portable content. All other capture
  fields, including future fields, participate in the proposal digest. Canonical
  JSON uses sorted keys, ASCII escaping, compact separators, no NaN.

The two actual retained inventories pass structural validation and have equal
inventory-only candidate content, including123 profiles and their raw group
relations. Their distinct original hashes stay retained. This observation is not
a complete provenance binding: neither job has a source packet. All100 unknown
attachments and source/compiler correspondence remain UNRESOLVED.

`compare` can report content equality and comparison with an explicitly supplied
candidate digest, but **always reports load_authorized=false**. The CLI always
exits1: equal content is not proof of source-to-loaded correspondence or absence
of an attachment conflict. No approval digest is populated in any repository
file. A caller cannot assert VERIFIED to bypass this boundary.

```bash
# Diagnostic only; exit1 remains required even for identical content.
python -I -B ci/apparmor/provenance_v3/binding.py job-a-provenance.json job-b-provenance.json
```

A reliable loading approval is not yet implementable from the retained materials.
The minimum gap is actual bounded sources and compiler/settings for every loaded
hash/group, then verified correspondence and per-lineage exact/AARE/xattr review.
Source hashes, kernel profile hashes and serialized raw-group hashes have
separate scopes and are never equated here. Reproduction needs matching parser,
ABI/features, includes/tunables/config, flags and group boundaries; current loader
source does not attest a past invocation. If these cannot establish correspondence,
keep UNRESOLVED. Raw_data is not currently judged necessary to read: first inspect
the source report. Any later binary request must name the particular groups,
size/hash bounds and failed correspondence that requires them for M review.

After those facts exist, M must explicitly review the portable binding rule and
new .8/provenance tuple before designing/activating a loading consumer. The old
exact-raw-JSON approval cannot be silently carried across. Current comparison is
a review aid with executable rejection, not a new source of permission.

## Proposed integration and checks

Apply only `readonly-workflow.patch` against the exact3d5326 baseline after M's
review. It retains the existing v2 report/hash, adds source collection, preserves
actual exits, prints the bounded source JSON/hash, and changes no other workflow
step or field. Native namespace argv/exit and all later checks are byte-identical.
A failed source read makes this inspection step fail and can prevent later steps;
that failure is retained, not relabelled as a namespace test or invalid policy.
No loading/removal block is added; old loading patches remain inactive and must
not be stacked on this baseline. No sysctl/setcap, elevated bwrap, alternate runner,
new paid resource, research call or change to coverage85/PIT/Validation is involved.

Local validation uses only new synthetic boundary cases, targeted strict Pyright,
Ruff/format, patch/YAML/bash checks, actual worktree import checks and the bounded
new projection of the retained two inventories. Existing .8/7-case/type proofs
are reused. No live source collection, policy load, native/nested permission
qualification, complete local CI, remote CI or scientific execution is claimed.
