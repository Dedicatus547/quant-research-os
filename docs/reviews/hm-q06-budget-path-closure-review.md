# HM Q06 budget staging path closure review

Status: **specific ancestor-alias and case-basename P1 CLOSED for the successor bytes below; NOT_QUALIFIED**. No complete installed seven-budget matrix, Q06, Q11, HM09 or MVP acceptance is granted. The original [narrow review](hm-q06-budget-narrow-review.md) and its failing component remain unchanged (report SHA-256 `cbd02d35428b0ea895fe3b3ebb589119ef4394fa7d8e13d77cc3d9575f8492fe`).

Assigned model: `gpt-6.1-sol`; reasoning effort: `high`; independent review attempt: 1, with three bounded local test runs; observed usage: unavailable. Baseline HEAD: `93fef2875bcf10386badb921f6ede112cf2704c5`. These are uncommitted successor sources, not the frozen installed93 code. This review ran only the two authorized unit test files in new `/tmp` roots and read existing component records; it did not stage another deployment, edit implementation, modify historical evidence/frozen worktrees, read credentials, or call a provider/model.

## Correction and remaining basename window

The original stager checked the leaf name while following an aliased existing ancestor, allowing a failed staging attempt to write into the component parent's authority. The successor pins the management root with `O_NOFOLLOW`, inventories protected directory identities, and rejects existing staging ancestors that are symlinks or overlap protected inodes before creation. Fixed-prefix creation and evidence publication use pinned descriptors; later replacement of those labels cannot redirect their writes.

The first successor pinned only the Q06 parent and still passed `Path(case)` to the stager. Independent code review identified a remaining case-basename replacement window; this was reported before closure. The final successor creates and opens the finite case directory with `O_NOFOLLOW`, then a separate management child uses `fchdir(case_fd)` and calls the real stager with `Path('.')`. Its management-only `prepared_root_fd` entry requires exactly `'.'`, the same cwd device/inode as the descriptor, and an empty directory before publication. Subsequent copy, git and compiler destinations remain relative to that pinned case cwd. The main process cwd stays unchanged. Post-stage label/inode checks establish the original source identity; they are not relied upon to prevent earlier redirected writes.

Declarations and safe failure records are published through the pinned evidence descriptor. The finite recipe and 300s staging deadline are retained. `prepared_root_fd` has no research CLI/RPC wiring; its only production caller found in `src` is the finite management budget stager. Existing normal staging still requires a nonexistent root. This closes the two identified write-boundary counterexamples without changing parent business inputs or frozen accounting rules.

## Independent checks

Only `tests/unit/test_hosted_budget_staging_paths.py` and `tests/unit/test_hosted_budget_cases.py` were executed, using `PYTHONDONTWRITEBYTECODE=1`, separate new `--basetemp` roots, and the repository virtualenv:

| Run | Independently observed result | Log SHA-256 |
| --- | --- | --- |
| `independent01` | 47 passed / 5.22s; earlier parent-pinning version | `813042f1f36b002786b305cee79f33308a752ce601b3fb00f320bab5b833812d` |
| `independent02` | 48 passed / 5.19s; final case-pinned implementation | `17c1c42505ac5c5dee934a1eaa6af388d26354949b5456ffbb772bdaf2964682` |
| `independent03` | 52 passed / 5.22s; same implementation plus four entry negatives | `53b8e6aa4bef83afd17f5fa5d22b68fdcf57520b95d41d608a26b87d08ec0253` |

Logs are `/tmp/hm-q06-budget-path-closure-independent0N.log`; their independent roots remain retained. Run03 covers sixteen existing ancestor aliases (eight protected roles at two levels), real fork/waitpid controls for a retargeted Q06 parent, evidence label, and new case basename, plus named-root/different-cwd/nonempty-root/regular-file-FD rejection. The alias and fork tests compare raw files, empty directories and device/inode/link-count/size/mtime/ctime facts. The four prepared-entry negatives mock provenance checks to reach the entry guard; they are not installed-source evidence. Thirty fixed-budget derivation tests also pass. No unit result is represented as a complete deployment qualification.

The parent-produced real staging component02 was independently reread. Its driver calls the real compiler/wheel/git/frozen-input stager in a fresh component root, then compares eight protected raw-file/directory inventories and the main cwd before/after. Child D is `3257f1e3b33e325acce4027b2c5f71546ee3410bd2b4b3c0ee46363b205aaf31`, B is `5d12624bd9f09c18f4887d2e0a4f6f41714428e89c185921c9ba6568abf4999a`. These component assertions cover files/directories, not all physical metadata.

Independent read-only `read_managed_budget_deployment` recomputed the expected B variant, parent/child runtime binding, complete child install/provenance/projection inventories, and both canonical parent declarations. The component's complete raw-file and directory inventories stayed unchanged; denied execute/Workflow/socket hooks observed zero calls. Driver `/tmp/hm_q06_budget_path_closure_readonly02.py` SHA-256 `38eef77466457094ad85eddc9ca7fe399995318e04fb6bb34ac1ee2ac0092547`; successful log `/tmp/hm-q06-budget-path-closure-component-readonly02.log` SHA-256 `49ae89b92876e54ce86bf4ad51e2f0a3d90c558fa82b51f2316b54839f768943`.

The separate real case-root replacement component was also read: its child pins the case inode, replaces the case label with a symlink to the fresh synthetic authority, then invokes the genuine stager at `'.'`. An intentionally nonexistent base prefix stops construction later. Actual waitpid reports PID 51 / exit 0 for that expected failure control; 23,832 partial native files remain only under the original case inode, and all eight protected raw-file/directory inventories remain unchanged. It is a retained partial staging control, not a completed D or installed worker.

| Parent-produced component artifact | SHA-256 |
| --- | --- |
| `/tmp/hm_q06_budget_stage_native_component02.py` | `00bbc41822a188f22e977e67d2be80b507a95208ac16356d3d7a342ba8f58165` |
| `/tmp/hm-q06-budget-stage-native-component02.txt` | `24e6c0f9d2dd6b366de89197f60a41a23ad53b9ead4f351cdd67c2b5a18ed48f` |
| `/tmp/hm_q06_budget_case_root_component01.py` | `c522ff0744db54c31a50fa493412d60184624d8bcc27ce814115cf4f65bf36ff` |
| `/tmp/hm-q06-budget-case-root-component01.txt` | `02d933d23fb13e6082591195a037e9a77b0696b5efede130783ec102fd86719e` |
| Replacement component `component-result.json` | `5a9037d07ef4f6a416481b1f9abde3c134b6f2f20c60cf490d58014949d32936` |

## Exact successor identity and qualification boundary

| Reviewed source/test | SHA-256 |
| --- | --- |
| `src/quantos/infrastructure/hosted_budget_deployment.py` | `d8ea93aaa97ac98bc01707ab6376692463704b1ab31c693f05e490e1da7b04fb` |
| `src/quantos/infrastructure/hosted_budget_staging_paths.py` | `f81da125e90d2b4a4e26a21966f192d654269bf66b8164abc738579c09dd6015` |
| `src/quantos/infrastructure/hosted_manager.py` — prepared-root increment only | `ace555759c6ff09bb84f885407e4e36220bde8f2581391e626fac6cc6a530c56` |
| `tests/unit/test_hosted_budget_staging_paths.py` — run03 | `9e718fa803a633b8b3cf1ed36f6debcba8d6594ca2a1d3c54d752cab8e88f73c` |
| `tests/unit/test_hosted_budget_cases.py` | `c2ff044a4a588db48887bb50713f4821be350a16d6a966cba0b375070d9e4ac3` |

Tracked diff capture `/tmp/hm-q06-budget-path-closure-reviewed-diff02.patch` SHA-256 `a7369e64fc423b0b560c7590bf443f9439a4250d6d34a994b6c199b19deefa69`; new untracked modules are identified separately above. Run02's test file hash was `ef50427b79eba91def4ad8aed3082c8b1d607778af600be373c17252559fddcf`; only the four additional tests changed before run03, while all three implementation hashes stayed fixed.

The readonly parent reference is actual18's frozen D `8af66253b6f052821ab4d8a9f4caca1d78e348311e4e98ca439f4ec89f54580b`; staging writes went to new component roots, not its manager evidence or authority. Its old93 wheel has no Q06 budget worker, independently confirmed in the child install. These checks therefore close the concrete successor path P1 only. All seven newly installed budget workers and their source-bound native lifecycle/accounting originals remain required. Neither original93/actual18 nor any earlier failed attempt is retroactively changed or accepted.
