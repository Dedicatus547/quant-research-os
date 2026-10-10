# HM Q06 finite budget implementation narrow review

Status: **BLOCKED — P1 staging ancestor alias; NOT_QUALIFIED**. This review does not grant Q06, Q11, HM09 or MVP qualification. No complete seven-variant installed/original-source matrix was available. The P1 below was reported to the main agent before freezing/staging the successor.

Assigned model: `gpt-6.1-sol`; reasoning effort: `high`; independent review attempt: 1; observed usage: unavailable. Repository baseline is `93fef2875bcf10386badb921f6ede112cf2704c5`; reviewed budget/lifecycle code is uncommitted successor code, not that installed commit. No implementation, historical evidence, frozen worktree, authentication or provider was modified/invoked.

## Frozen requirements and reviewed scope

The roadmap and frozen C06/Q06 require request reservations before issue, unique submissions charged before acceptance, rejected/conflicting attempts retained, seen bytes returning their old receipt, immutable restart accounting, campaign and per-request caps, bounded exhaustion artifacts, and native trial/execution/workload accounting. Internal host tokens/costs remain unavailable; `max_compute_seconds` here denotes the existing deterministic workload units, not a wall-clock enforcement claim. Full Q06 also requires the native cross-process cancel/submit and TTL lifecycle matrix.

Read documents: `docs/roadmap/host-mediated-mvp.md` (`0864563a656341df125cf03801cc0acd37a75e020e2b5ec703dad5cd206d6c56`), frozen contract (`14704b9cbbe0f0ca281751833bc08248820da0c277a281a140bfd12bc6b102df`) and acceptance (`e5877b503259f6e758f22a6feb9307efdc45397155a9229527b2a8ae5dbfc55e`). None was changed.

## P1: child deployment writes through an ancestor alias

`hosted_budget_deployment.py:85–105`, reviewed SHA-256 `e2ccd9b6f7884c88716f6f2ba41430d2023d623bafc1436fb26be34341157199`, derives the finite path `parent.root/qualification-deployments/Q06/<case>`. It rejects an existing target or a symlink at the target, but does not reject aliases in the existing ancestor directories before calling the real `stage_hosted_deployment`. That implementation first creates the output root/subdirectories and publishes frozen input files. A later staging failure does not undo these writes.

Independent new temporary component parent `/tmp/hm-q06-budget-stage-alias-independent01-root` had an empty `authority` and `qualification-deployments → authority`. The managed-deployment component object borrowed the original attempt17's frozen input/configuration/provenance/wheel paths for read-only data and used this new temporary parent root; it is not claimed to be a qualified installed manager. Calling the **real staging API**, without monkeypatching the stager or creating any model/provider call, failed with `FileNotFoundError` later in construction. Before that failure, the synthetic existing authority changed from **0 files / 0 directories to 17 files / 21 directories**. This establishes the pathname write-boundary defect; it does not alter or accuse the actual attempt17/18 authority. `GIT_OPTIONAL_LOCKS=0` was used for read-only provenance commands. The required base/dependency paths were deliberately nonexistent, and no native compile or installation was reached.

The preserved independent assertion fails because the original synthetic authority was changed. Driver `/tmp/hm_q06_budget_stage_alias_independent01.py` hash `af79df3996a540d54a7b9a185789e64d4dd51772631e0921c85d073ad2efb2b3`; failure log `/tmp/hm-q06-budget-stage-alias-independent01.log` hash `0b9f866c6cadf392841dee48a350670d0beaa6e9fd172aa94189d5c8dd57cece`; original summary hash `5bfe3060902948d2eee10cf88aa0ff653c1bfaf1237a0ede4ec84b0393e1f530`.

Minimum closure: before any mkdir/publication, reject symlinked existing staging/declaration ancestors and physical overlap with existing authority/channel/input/configuration/projection/provenance/evidence roots. Keep the subsequently used output path bound to its pinned parent/root rather than merely resolving/checking a path and later writing through a replacement alias. Add a real-API ancestor-alias regression asserting that existing authority's complete files, directories and physical facts remain unchanged. Preserve this report and counterexample; review corrected source in a separate successor closure record.

## Finite B/D and source-binding implementation

The seven recipes are fixed, with positive typed minima enforced against one clean two-candidate baseline. They derive a new budget ID/campaign, native activation/frozen-plan events, native selection plan and updated readable campaign policy. Parent Ledger seed files, execution bindings and frozen data are retained. The derivation is read-only; plan publication is a separate fresh-root operation.

| Recipe | Fixed exercise / stop |
| --- | --- |
| `request_allowance` | request cap 1; schema-invalid trial; `PROTOCOL_EXHAUSTED` |
| `research_attempts` | research agent-run cap 1 and request cap 1; `BUDGET_EXHAUSTED` |
| `campaign_submissions` | campaign submission cap 2 across R1/R2; `PROTOCOL_EXHAUSTED` |
| `request_submissions` | two distinct rejected frames fill per-request cap; `PROTOCOL_EXHAUSTED` |
| `trial_allowance` | fixed trial/distinct/execution/validation minima; schema-invalid trial; `BUDGET_EXHAUSTED` |
| `execution_allowance` | one native execution and validation; `BUDGET_EXHAUSTED` |
| `compute_allowance` | native reservation rejected at workload allowance 1; no execution; `RESEARCH_RESERVATION_EXHAUSTED` |

Staging constructs a separate B→L→C→I0→D before running the fixed worker. The variant reader rederives expected B from the supplied original parent, requires exact canonical equality, compares parent/child installation and runtime fields, checks child install/provenance/projection inventories and rereads both exact parent declaration copies. Configuration changes for the new B and the child clone's provenance-inventory hash are intentionally not compared as if identical to the parent; the child inventories and native bindings still have to verify. The helper-only positive checks below do **not** instantiate seven actual D profiles.

The parent export retains full paths under `qualification-deployments/Q06/<case>/...`. The subset reader strips only that exact child's prefix, excludes other children, and demands exact snapshot/sidecar/process paths relative to the independently read child root. It rechecks original and copied raw inventories/directories, actual final child authority, original prelaunch/completion/program/argv/kernel/namespace/principal evidence, and all three source-phase waitpid records. Labels, a producer PASS or synthetic kernel records cannot replace these gates. The management executable only accepts its finite case and profile; no new research RPC capability, clock or root argument was exposed.

The native scenario verifier rebuilds protocol/business state and native budgets, completed steps, bottom-up execution/Validation evidence, events and Ledger/full-file closure. It binds fixed frame receipts/principal/time, charges, bounded prepublished exhaustion receipts, both fresh recoveries and exact projected status. Exhausted research stays `FAILED / NOT_EVALUATED`, with no selection report and native unavailable-usage limitations. Recovery copies must have the exact exercise file/directory inventory. Native execution's three permitted empty directories are derived only from independently verified execution identities; unknown directories remain forbidden.

The new `hosted_q06_verification.verify_q06` requires exactly **44 named roots** (four lifecycle × four phases plus seven budgets × four phases) and calls both complete source-bound subsets. `verify_case` now dispatches Q06 only with source evidence. An empty historical Q06 record remains NOT_EVALUATED. A subset, missing phase or extra root cannot award Q06.

## Independent component evidence and retained failures

New `/tmp/hm-q06-budget-independent01-root` controls completed with **57 negative checks rejected**:

- Each of seven B derivations was repeated byte-for-byte; all seven B/campaign identities differed, with native plan/budget links and unchanged parent input inventories. For each variant, five changed child runtime/install fields and relabelled original B were rejected (42 checks).
- Unknown recipe and non-frozen baseline minima were rejected; lifecycle-only, budget-only, one missing phase and extra phase matrices were rejected (six checks). A mocked dispatch-order check confirms both subsets are called; it is not source-origin evidence or qualification.
- One fresh **nonexecution `request_submissions` native accounting component** used the existing synthetic factory, real fork/FD consumption and three fresh applications. Two unique rejected frames were charged; 32 over-cap submissions reused one exhaustion receipt and seen bytes retained their original receipt. Its existing five record negatives passed. Nine additional independent checks rejected changed bootstrap/clock/parent/execute/network claims, a recomputed-hash claimed charge reset, an extra empty directory, a valid native object at an orphan path, and missing protocol specs. Verification did not rebuild missing directories or change the copied files/directories.

Execute, Qlib Workflow and socket connects were denied in this independent nonexecution component, with zero observed calls. It did not exercise the installed execution variant or seven installed namespace workers. Read-only original attempt17 input data were used solely for pure B derivation; its historical D was not relabelled or upgraded.

Independent driver hash: `85dda951db24bb70ea3028750ad3a04ed983d8548931e1805c1a20a249c3037b`; log `/tmp/hm-q06-budget-independent01.log`: `7cb112f0b9a87bca22f8285ec7b01481129f6da1658243ff640add9e91a97f20`; summary: `0f03f37353a50c9efa77a495bb1f30bcbee0718ef700c6b26938335e798909d9`.

The retained native e2e06/07/08/09 failures remain failures: receipt-dict hash test error (85.50s), mismatched test adapter campaign/budget (104.76s), omitted native prepublished exhaustion receipts (57.98s), and omitted legal native empty directories (168.61s). E2e10's retained log reports **1 passed / 208.15s**, covering four native lifecycle cases, seven budget components and 35 budget-record mutations. Its source/factory/kernel boundaries are component-level; later probe directory guards and manager timeout changes are not retrospectively proven by that process. Log10 hash: `4bd6ec6ccb58c706a96d0a63e3e989d6f9b2b0f4229cca8bad4766c16dfe6c17`.

The default management test run01 retains 1 failure/63 passes (`/proc/73/status` unavailable in that sandbox's process view); it was not bypassed by PID guessing. Run02 in the real management/proc environment reports **73 passed / 37.57s**; log hash `317569a53536b04dd4d9b5541a2657ebde11fe7795cdb4bfb1bee0c6eb797e0d`. Neither substitutes for the complete installed matrix.

## Bounded management timeout addition

The reviewed later manager branch gives Q05 a finite 14400s outer deadline and Q06's sole native execution recipe 7200s; other Q06 cases remain 300s. The native fault child deadline becomes 7200s; the budget native child remains 3600s. These are management wall-clock bounds and do not change frozen native workload accounting or refund rules.

The fault timeout branch kills/reaps its actual child, persists the actual `os.waitstatus_to_exitcode(status)` phase/PID tuple, then raises failure. It does not fabricate success or a completion observation. Independently rerunning the real fork/SIGKILL/reap control gave **1 passed / 5.66s**, checked exit `-SIGKILL`, no remaining waitable child and no observation file. `/tmp/hm-q06-budget-timeout-independent01.log` hash: `32f46f7ae64f712d2ac08a7389189a28477fb804003dfad5f4f120a35ca7d2fb`.

The old actual93 execution-prepared run's return1, incomplete child-record set and original log are not changed or accepted by this addition. The twelve atomic windows previously reviewed remain a separate scope. No full Q05 matrix claim is made here.

## Exact reviewed successor bytes

Paths are under `src/quantos/infrastructure/`; source copies/diff records are retained in `/tmp/hm-q06-budget-review-source01` and `...source02`.

| Source | SHA-256 |
| --- | --- |
| `hosted_budget_cases.py` | `f9028d93aaf9a73617d954b6f304c72839c6792b1c135d860456782c6cda0c7b` |
| `hosted_budget_deployment.py` — open P1 | `e2ccd9b6f7884c88716f6f2ba41430d2023d623bafc1436fb26be34341157199` |
| `hosted_budget_probe.py` — initial read | `20129f5cf3d42e937c0c1d7aa1243cd534d480fa50335a13926d4cf6a9c68784` |
| `hosted_budget_probe.py` — added recovery-directory guards | `9c08388180e04253ac7270e272661cbd1dc595da203dc4e151b25614925b4030` |
| `hosted_budget_verification.py` — native directory attribution | `3fe23c84da7657b25dfb5ec5c8c709aa5d568b607154c515fcf3709e9df815e1` |
| `hosted_manager.py` — final reviewed timeout/fresh-variant branch | `4789438a4a365d9cb103612148b1d6f504c98251ed9f62475ee46502aa23a35b` |
| `hosted_negative_origin.py` | `211305c1376f96a68429ca05a8f0ff44d22abbe2c64b4a7eb98cc2d23cb026de` |
| `hosted_q06_verification.py` | `cc96e6a1f6f206c2e3e5ba74db7a25c4dc7e5a9ff3f75c8860779dfc158da7fc` |
| `hosted_verification.py` — Q06 dispatch | `840d39ee1cb61ab59751418baa2b4c88f66634bc2ae4156f8b391eebf68389e4` |
| `hosted_fault_probe.py` — bounded timeout and exit retention only | `e8d52ff89ad51c38bb614fd48d14cc5d7b681e405a2b26fcff037c5670e05f30` |

The final captured tracked-diff hash is `b1d2316d5c561151313abea468e67e92590ee13f229241b5d845df7971e04e53`; new untracked modules are separately preserved and hashed above. The staging P1 remains open for those original reviewed bytes even if successor code changes while this report is being delivered. Full installed seven-variant/source/kernel evidence and independent final qualification remain outstanding.
