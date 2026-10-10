# Independent large manager-export scanning review

**Narrow implementation review passes; NOT_QUALIFIED. No P1 found in the reviewed size/scan increment.** This does not qualify Q05 or any deployment, and does not reinterpret frozen1122922 attempt16 as containing the new manager producer.

Assigned model `gpt-6.1-sol`; reasoning effort `high`; independent attempt1; observed usage unavailable. Base HEAD `1122922f6e67e3b1802010cf3b350764e898f99a`; tracked diff SHA-256 `5244edc54c276383c9ed422c90a32f951fec1a5da283e94e60b8dbba2d7fac86` excludes the new untracked test file. Reviewer did not modify repo, touch the independent actual16 worktree/original evidence, read credentials or call model/provider. All extra canary artifacts are `/tmp` synthetic fixtures.

| Exact reviewed source | SHA-256 |
| --- | --- |
| `hosted_manager.py` | `a2c73c8a7e2278d31c17dc0aaf356dfdea8ac96ce8d00761b605e62653bf633d` |
| `test_hosted_manager_export.py` | `cf670283d083d553ba04f62ed1f1c104d62150e54d0cce74335d84f954cf8dfd` |
| unchanged `hosted_deployment.py` guard | `4bbe2c3cd1ab8e8c0d33e246918980236736a3272bec5612149863ebd7f05e0f` |
| unchanged `hosted_qualification_sources.py` reader | `a994d871288204458ed0ad2b5ca1c12bdd00609bd6c6f4709c51f140b007642b` |

`publish_manager_export` rejects canonical aggregate bytes over16MiB before immutable publication, matching the existing typed reader. The generic KnownValueGuard default remains4MiB; neither it nor research-channel caps are enlarged. Header and every typed record are complete canonical JSON guard inputs, retaining decoded key/string scanning. A record exceeding the unchanged per-call cap fails closed. All scanning completes before the atomic write.

Every raw aggregate byte also enters overlapping1MiB scans. Registered sensitive values are16–4096bytes; all existing representations are at most6 times original byte length: raw/hex/base64/percent/Unicode escapes, including UTF-8 quote and padding-stripped forms. Thus overlap6N covers every registered contiguous variant crossing a window boundary, with strictly positive stride even at4096bytes. Invalid partial-window JSON does not remove decoded scanning: complete header/records supply that separately.

Independent repository tests: **4 passed /17.37sec**, covering9000-record aggregate above4MiB, sensitive bytes spanning both record and window boundary, over16MiB rejection without publication, and in-record known value rejection. The general guard still rejects the >4MiB input.

Additional independent producer canary uses synthetic newline/tab bytes: no registered raw variant appears in canonical record bytes, but full JSON decoding finds the sensitive value and rejects without writing evidence. Separate guards at16/32/4096bytes confirm longest Unicode variants spanning the1MiB edge are detected and the stride is positive. No actual credentials are used or printed.

Evidence hashes: test log `/tmp/hm-large-manager-export-independent-tests.log` `119b470b375e47587735d2ec51713f9a877988b316b95133681f0ab1fb8b46dc`; canary `/tmp/hm_large_export_escape_canary.py` `7eb1e877c572428da9a7741ea60aab4dd8780bea8512a2b79994e13bb9ec94dc`; canary log `/tmp/hm-large-export-escape-canary.log` `a2197e223c028000d85a7dbcbcdf5918553f3970a909c293ca22f22ee36df4b1`.

The change supports a separately identified successor management diagnostic producer while preserving exact canonical export bytes and all prior size/secret-scanning boundaries. Formal origin/verifier/deployment qualification remains outside this review.
