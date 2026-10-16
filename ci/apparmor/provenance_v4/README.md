# Successor read-only provenance candidate

Prepared against actual M baseline `84a38d01b6658d9dfa234fff5f39b4cb8507941d`.
Apply only `readonly-workflow.patch` after M review. The active workflow is left
unchanged by this B commit. This proposal grants no loading authority; every
`load_authorized` is false and the comparison CLI always exits 1.

The two retained v3 reports (601251 bytes each) remain immutable failures:
137 readable sources, 125 missing source candidates, two missing settings and
the bulk ownership query's exit 1 yielded 128 errors. Their equal candidate
content does not prove source correspondence. v3 schema, code, candidates,
32-case proof and original exits remain unchanged. This version explicitly
changes observation classification, not historical acceptance or policy loading.

The new plan uses the saved source bytes before packaged templates. Its 309
exact file-or-directory candidates and 496 reference dependency edges retain
the input report hashes, reference source hashes and each edge's origin/line.
All 426 literal dependency edges in the actual readable sources are covered.
Besides ABI 3.0/4.0 and user-tmp, the old plan omitted required consoles, mysql,
passt and eight local includes. These are now requested; missing required local
includes remain failures, including the historical `#include` spelling.

| Change | Observation and remaining boundary |
| --- | --- |
| Loader | Read `/usr/lib/apparmor/rc.apparmor.functions`, as referenced through `/lib` by the actual captured loader. Observe only `/lib` and `/sbin` alias metadata; accept only the fixed `usr/lib` and `usr/sbin` targets, otherwise retain an error. No arbitrary symlink following. Nonmerged `/lib` loader/helper files are observed separately. |
| Dependencies | Record literal ABI, required include and explicit `if exists` edges from observed bytes. Actual directories are listed/read with the existing bounds; duplicate files are read once. New unplanned dependencies are reported, not followed. Unsupported paths, variables or directive syntax remain errors. This small literal inventory is not an AppArmor parser, AARE matcher, effective-policy evaluator or historical compilation proof. Grammar reference is the retained .8 package's `apparmor.d(5)`. |
| Absence | Only a genuine missing path referenced by an observed `if exists`, with no required edge or root-candidate obligation, becomes `EXPLICIT_IF_EXISTS_ABSENT`. Its original missing record remains. Errors, symlinks, denied reads, limits, required missing dependencies and investigation gaps still refuse completeness. Template optionality cannot waive them. `/etc/default/apparmor` remains a requested setting and its observed absence remains an error; no default file is fabricated. |
| Bundles | The two Ubuntu helper root declarations are in the actual `ubuntu_pro_esm_cache` source and share its raw group (which also includes children). All four transmission roots share another raw group; the retained .8 `transmission` template and its include closure are requested as a bundle candidate. The six separate guessed filenames are removed only from this successor plan. Template bytes do not attest runner source or loading. |
| Remaining roots | Edge's `microsoft-edge-stable` is not equated with the readable `msedge` profile. snap-confine's source and generated docker-default remain unresolved. Transmission's corrected file has not yet been collected. A single nonrecursive metadata-only listing of `/etc/apparmor.d` (names, directory/symlink booleans) can locate candidates for a later exact-path review; no listed file is automatically read. |
| Ownership | Retain original argv/exit/stdout/stderr. A single bulk query covers readable paths and fixed logical aliases only when alias metadata supports them. Parse successful owner lines even on exit 1, retain exact-path `UNOWNED` alongside alias `OWNED`, and query versions only for observed owners. Exact unowned diagnostics account for exit 1; unrecognized/truncated/failed/conflicting results still refuse completeness. Unowned local bytes remain useful observations; signed archive origin and historical loading remain `UNRESOLVED`. |

Collection completeness describes bounded observations and explicitly permitted
absence. It is separate from source-to-loaded correspondence, historical compiler
flags, attachment review and loading approval; those remain unresolved even for
a complete synthetic packet. A root without a readable candidate still prevents
completeness. Therefore this patch does **not** promise to make the next job pass:
the default setting and unresolved/generated roots may still produce exit 1.
It does not bypass that failure to run later CI steps.

The v4 binding reuses the unchanged v3 inventory/byte/namespace/authority checks
through an internal validation adapter, not a stored or relabelled v3 report.
It checks the new dependency/ownership classifications against observations,
retains all new fields in a domain-separated v4 content digest, and rejects
assertions of verified correspondence or compilation history. No approval digest,
acceptance writer or loading consumer exists. Source file hashes, kernel profile
hashes and raw-group hashes keep their different meanings.

The existing descriptor-based `Reader` and bounded `command` are reused unchanged:
512 file attempts, 512 directory entries, 64 KiB/text file, 4 MiB total file input,
1 MiB inventory and 12 MiB output. Directory traversal and the new root listing
share the entry budget; the latter has an additional 256-name limit (under 128 KiB
of encoded names/metadata). The two fixed alias metadata observations do not read
file contents. Each dpkg command retains at most 256 KiB stdout/8 KiB stderr,
has a 10-second timeout and existing scratch limits. No package download, raw_data
binary, user data, environment dump, loader/parser execution or policy write is
part of acquisition. The policy revision is checked again after acquisition.

The patch only switches the existing observation step to this successor and
prints its tools' hashes, including inherited dependencies. It preserves the
grouped inventory, real exits, namespace/native invocation and every subsequent
CI step, strict typing, tests and coverage threshold. It is not activated here.

```sh
# Future runner observation only; requires actual inventory hash and image identity.
# May exit 1 with a retained incomplete report. Do not substitute a template hash.
sudo /usr/bin/python3 -I -B ci/apparmor/provenance_v4/capture.py \
  --inventory /path/to/grouped.json --inventory-sha256 ACTUAL_SHA256 \
  --image-version ACTUAL_IMAGE_VERSION > /path/to/provenance-v4.json

# Diagnostic comparison: always exits 1, including for equal complete packets.
python -I -B ci/apparmor/provenance_v4/binding.py job-a.json job-b.json
```

Local checks cover only affected path/closure/absence/ownership/refusal behavior,
strict types, lint/format, patch/YAML/bash and worktree import identity. Original
32 cases, reader guards and parser/package proofs are reused at their original
tuple. No live runner acquisition, historical compilation reproduction, native
permission qualification, full local/remote CI or scientific execution is claimed.
