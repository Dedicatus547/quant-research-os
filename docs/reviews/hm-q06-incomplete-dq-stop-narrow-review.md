# Q06 incomplete DQ stop independent narrow review

Assigned model: gpt-6.1-sol. Effort: high. Independent review attempt: 1. Observed usage: unavailable. Outcome: no P1 identified in the bounded implementation reviewed below; **NOT_QUALIFIED**. This is not Q06, Q11, HM09 or overall deployment acceptance.

## Source identity and scope

Baseline HEAD: `77c129f11e9fc65f76a64fa978cc6d06e9164554`. Only the uncommitted `hosted_campaign.py` implementation and its campaign tests were reviewed. Source snapshots and diffs are preserved under `/tmp/hm-q06-incomplete-dq-review-source`. No frozen contracts, implementation, historical authority, installed worktrees or authentication was changed. No provider/model was called. The requested new review document is the only repository file written by this reviewer.

| Source | SHA-256 |
| --- | --- |
| application/hosted_campaign.py | cd4de6187d14d08d8b472e7c840102240833d5f87f22b0a1930e31dcdde53a37 |
| initially reviewed test_hosted_campaign.py | 7a6b27eb29ba583c63d5907b60b6f5d65726f6c00eb8a72df3ff6f9403fa871a |
| initial bounded diff | 3f16a95218608ef559a194549b3ff926edf91b0a346d6e9f53bb4d6737c9474e |
| later tests including complete-denominator control, before test repair | 9a0bcb10d252a78e46afb9810346eaffb5236be44c65f8a89d4d449593c97429 |
| repaired complete-denominator test file | b4eea9061cc5ffb2e24ca9e898bf2596b3ab81ce3c0d70d3c4877acd013afe00 |
| bounded diff with repaired test | 760f9a78592e83f3620e3914d55fa71a333fc5a8705cd054e7eb7d0c0dbc0c94 |

The implementation hash remained unchanged throughout the independent runs. Later test-only changes are not reassigned to the earlier test identities.

## Bounded behavior

The selection bypass requires exact equality with the frozen `P14DQ_REPORT_ONLY_FINALIZATION_PROFILE`, one of CANCELLED/EXPIRED/EXHAUSTED, and an incomplete candidate trial set. RECOVERY_REQUIRED retains its previous separate path; COMPLETED and a complete denominator do not enter the new bypass. No selection exception is caught or converted into this branch. Other finalization profiles retain the existing selection handoff.

The incomplete-stop report preserves all manifest candidates, attempted/remaining candidates, requests, exchanges, trials, events, Ledger and budget references. It has no selection report hash and explicitly reports FAILED / NOT_EVALUATED, with the additional exact limitation `P14DQ_INCOMPLETE_DENOMINATOR_SELECTION_NOT_PERFORMED`. This describes stopped accounting, not a P14c selection result or research success. The contract retains NOT_QUALIFIED eligibility.

On resumed evidence, `_verify_report` recomputes the branch from the bound orchestrator and loaded events, checks the exact limitation tuple, rejects selection hashes or successful run/verdict claims for incomplete stops, and retains the existing native event/Ledger and completed-step prepare/finish/execution checks. The frozen DQ preselection method still requires the full candidate denominator and corresponding native receipts; neither that method nor P14c was changed.

## Independent checks

The initial controls covering the three incomplete DQ stops and existing default-profile stop paths passed: 9 passed in 25.05 seconds. Log `/tmp/hm-q06-incomplete-dq-independent-controls01.log`, SHA-256 `ca7174c2afdd568421a482839f247c5277a8026fd97d9c4a222ba121be9a6633`.

A separate disposable fixture completed one component EXECUTION_FAILED trial, then cancelled the second request. Its report retained one trial and the remaining candidate while reporting FAILED / NOT_EVALUATED without selection. Seven contract-valid report mutations were rejected: missing marker, missing base limitation, extra limitation, duplicate limitation, reordered limitations, a false selection hash, and a false SUCCEEDED/SELECTED claim with a self-consistent forged denominator. A fresh application resume returned the same status and left the complete fixture tree, including inputs, events and Ledger as well as authority files, byte and directory inventories unchanged.

The same independent script consumed both candidates in a second fixture. Complete-denominator finalization reached the existing selection handoff and raised `AutonomousOrchestrationError: DQ preselection verifier is unavailable`, because the component execution port deliberately has no native DQ verifier. No final report was published. This is a fail-closed negative proving the new branch does not swallow that gate; it is not a positive native DQ qualification.

Script `/tmp/hm_q06_incomplete_dq_all_evidence_independent.py` SHA-256 `ad300ee5a6468384a58e3b963cb88c3a90a9401100ac0a1eef8683a2b29a2467`; successful log `/tmp/hm-q06-incomplete-dq-all-evidence-independent01.log` SHA-256 `a6ddb6e6252f502bfd4aa8552b475c7e01088fb8f85be34b29f9f981a944d5ba`.

The later repository control run is preserved accurately: 9 passed and 1 failed in 33.05 seconds. The new complete-denominator test correctly asserted the original gate exception and absence of reports, then failed on a test-only reference to nonexistent `inputs.governor`. Log `/tmp/hm-q06-incomplete-dq-independent-controls02.log`, SHA-256 `d67a6e619aa76ef3c37f48dae41e24e12966ad1bbab15d1f07fdd2be420c3282`. After the author replaced that trailing assertion with two verified COMPLETED research steps, the reviewer independently reran that test: 1 passed in 12.12 seconds (`/tmp/hm-q06-complete-dq-test-followup-independent01.log`, SHA-256 `b70e52575084aefb6cbb74d6f54b04872e401186ec3b6dda5de70b8da5b5cafe`). The original failure log remains unchanged.

## Limits

These are synthetic-input component checks using the explicitly test-only disk execution producer, not source-bound installed native Qlib evidence. They establish the narrow failed accounting behavior and its report guards. Q06's full budget, concurrent cancel/submit, TTL, deployment/source and actual restart matrix remain required; Q11's genuine live source and strict P14c evidence are not obtained through this report branch. No historical attempt or existing installation is retrospectively qualified.
