# Complete manager source-index capacity

Date: 2026-10-05. Development: current main agent, observed usage unavailable.
Status: implementation regression passed; no hosted qualification is granted.

The complete qualification producer retains the whole 106-case fault matrix,
original live authority, receipt reuse, two fresh Qlib roots and five scientific
tamper roots. Its typed source index maps every exported file to its original
manager path, SHA-256 and byte length. The former 16 MiB source-index limit cannot
accommodate this supported combination.

The exact C31 offline index has 22,745 records and 16,452,551 bytes, SHA-256
`f3306ca6cc9bf49c64ffe5e2caf933c1d68c5f4275d0d82013a20fe64128aefb`.
A read-only diagnostic projected the 616 files of the completed native
`execution-final_report` authority into the full producer's ten live/replay/tamper
authority locations. The resulting typed layout has 28,905 records and 21,063,197
bytes; the original source guard actually rejected it at 16,777,216 bytes.
The diagnostic is explicitly synthetic layout metadata: no future authority,
request, response, model call or qualification was created. It leaves the original
index unchanged. Its record is
[/tmp/hm-prospective-export-cap-diagnostic-attempt31-01.json](/tmp/hm-prospective-export-cap-diagnostic-attempt31-01.json),
SHA-256 `564a8fd6c3bd73301dbd4609c1a5defc288a14b98cc1a6e53249e526a80f11d8`.
The immutable diagnostic script SHA-256 is
`656205c7ec41e5f34d5bc69e8024a6a1ca8dec4ed7d785e2326cc8cff3155289`.

`MAX_MANAGER_EXPORT_BYTES` gives only the canonical `HostedManagerExport` source
index a finite 32 MiB bound (33,554,432 bytes). Publication and the dedicated
`read_manager_export` reader share that bound. The independent verifier reads the
retained original index under the same bound, then checks its exact bytes/hash,
deployment and clean installation, full file denominator and every source and
bundle file digest. Reads continue through pinned descriptors with no-follow,
unique regular-file and before/after identity checks.

The general typed reader remains 16 MiB and `KnownValueGuard` remains 4 MiB per
call. Source-index scanning still decodes every typed record and scans all raw
bytes in overlapping 1 MiB windows, rejecting registered sensitive values across
record/window boundaries. Research requests remain bounded at 1 MiB and proposals
at 256 KiB. Scientific streaming, inventory bounds, frozen families and budgets,
PIT, Qlib, validation and source/provenance predicates retain their existing rules.
The frozen HM-02 document bytes and serialized index schema are unchanged.

Actual regression: 20 tests passed in 38.38 seconds for manager exports,
qualification sources and qualification. The export regression publishes and
strictly reads an index above 16 MiB, confirms the ordinary reader still rejects
it, rechecks sensitive-value/provenance failures, and rejects an index over 32 MiB
before publication. Standard production Pyright completed with zero errors,
warnings or informational diagnostics; Ruff, formatting and diff checks passed.
These checks use unit fixtures and grant no native qualification.

C31's original 1795-test installed CI, complete 106-scene capture and seven-gate
offline export remain immutable historical evidence for C31. Its independent
native verification exceeded the 7200-second limit and failed; the original roots
were not repaired. Revised implementations require a new exact commit,
install/deployment identity and qualification execution.
Authenticated handoff still requires the actual user approval demanded by the
earlier automatic review rejection; no provider authentication has been read.

Pre-live consumer review found that `export_live_source` still read all stopped
manager evidence under the ordinary 16 MiB limit and scanned it under the general
4 MiB guard. The old actual index already exceeds 4 MiB. The corrected copy path
allows only canonical, hash-named `HostedManagerExport` evidence above 4 MiB to use
the existing dedicated reader and typed scanner. Commit/deployment, original
inventory hash and length remain mandatory. All original files are copied;
protocol and request projections retain their ordinary caps.

Actual development regression: 32 tests passed in 52.97 seconds, including 13 new
source-copy cases. The positive case copies a real synthetic index above 16 MiB
and binds all three original roots to the export sidecar. Foreign deployment,
wrong hash/name/length, noncanonical bytes, known sensitive values, unknown large
JSON and evidence above 32 MiB are rejected without a terminal source-export
record. The ordinary protocol/projection limits are also checked. Source bytes
were unchanged during the tests. These fixtures do not establish live or replay
qualification. The complete development collection now has 1825 tests; the new
frozen installation must run its own full CI rather than reuse the old reports.

The final management bundle producer must preserve retained indexes in its file
manifest and source mapping, validate them under this typed boundary, and keep
them separate from ordinary case JSON paths. Raising all case readers to 32 MiB,
dropping original indexes, or treating reader failures as harmless JSON skips
would weaken the existing source checks and is not an accepted correction.
