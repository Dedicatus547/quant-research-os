# Q06 lifecycle subset original narrow review

Assigned model: gpt-6.1-sol; effort: high; independent attempt: 1; observed usage: unavailable. **NOT_QUALIFIED.** The fixed-clock cross-binding P1 below remains a finding against the reviewed original predicate. Corrections require a separate closure record. No complete Q06, seven-budget installed matrix, HM09 or MVP acceptance is granted.

Baseline HEAD: `93fef2875bcf10386badb921f6ede112cf2704c5`. Parallel Q05 attempt18 is a distinct frozen installation and is not reviewed or qualified here. Exact manager/origin diff retained at `/tmp/hm-q06-lifecycle-original-wiring.diff`, SHA-256 `7d7cacb4448d0836d2e69313e488024cb8517f264f44f590879fa0d9d7af7f57`.

| Source observed | SHA-256 |
| --- | --- |
| hosted_lifecycle_cases.py | 665bb328e5ba5bcf8de3120a78868669b2e064006150d2e3c0a8d3abfe43a4be |
| hosted_lifecycle_probe.py | bbd145f19e30ab456154cc3597af7403a911f4861cb1381927053ffdc26795d7 |
| hosted_lifecycle_verification.py, initially | 68824a1c742cf3d57101f293647e15d2736280eefe47e77671da5b725d59d5b4 |
| hosted_lifecycle_verification.py, accounting correction and clock canary | 9e52846552aef6bf02827c5bc1d49d2bd12cc41bb03868cc84999ea7a6b1af8e |
| hosted_manager.py | 44a2d74a11ee13b43baa7aa3a26bc243d6f11a06fa000de152203d706c38de86 |
| hosted_negative_origin.py | c6266d4827a745c1b860f95e3e5ac811d3c2a7a7a53d9d33c635aaff151c6f74 |
| hosted_business_file_closure.py, legal first-expired SUBMIT correction | 4cf0cf225c2a4cfb2501d176ace608132b249378b07b17fbe639d4c6bac1b91c |
| test_hosted_lifecycle_probe.py | b5acd824643915bbab09200908bcdcc2e070d908319509b0a42836b173f5077b |
| test_hosted_lifecycle_e2e.py, initial / corrected nested negative | fb0283e03b54dadb4c0bf1a338d24d79ce881cfd8723136a97e1b07f7831e4a7 / 98e94dc8f772b73da5b914afc17ffa7fde927c0da2d299484b1f8b6056e7407a |

Snapshots are under `/tmp/hm-q06-lifecycle-independent-original-source`. Initial 68824a source changed before the copy completed; reversing only the accounting correction reconstructed bytes with that exact full-file hash, retained separately as hosted_lifecycle_verification-original-68824a.py. Other observed identities are not conflated with subsequent shared-worktree changes.

## P1: fixed TTL clock metadata does not bind native publication time

The original core required process.clock equal request.expires_at, and compared process results with parsed native receipts/reports, but did not require those native receipts, embedded EXPIRED terminal or protocol INTENT to have that exact timestamp. A legal expiration one second later could therefore be presented as the required boundary fixture.

Independent disposable frozen-B17/native-loader component `/tmp/hm-q06-lifecycle-late-clock-independent02-root` advanced the actual HostedProtocolService clock by one second at TTL while leaving the probe's process clock at exact expiry. Real native receipt/terminal/journal bytes were produced and verified; original evidence was not edited. Predicate 9e5284 plus file closure 4cf0cf returned **PASS with 40 hashes**. Clock metadata and expiry were `2026-09-30T20:08:31.480533+00:00`, but the actual native terminal was recorded at `2026-09-30T20:08:32.480533+00:00`. This identifies the source-independent core's omitted fixed-fixture assertion; it does not claim a modified producer passed an installed source gate.

Script `/tmp/hm_q06_lifecycle_late_clock_independent02.py`, SHA-256 `5996313ddd7bf8b0541740af9a27c83fa0235e9604350a4f4e58e1d75c09a95a`; log `/tmp/hm-q06-lifecycle-late-clock-independent02.log`, SHA-256 `855cb01598a9b3dc37a8942305387bc93f04665bcb97968b1069e4294196b979`. Driver attempt01 used the wrong spec budget attribute and remains preserved as a driver failure. The correction belongs in the fixed lifecycle predicate: bind R1 issuance, each native SUBMIT/TERMINATE publication and exact principal, and recovery R2 issuance/cancellation to the prescribed start/expiry chronology. Ordinary production expiration remains legal after its deadline; the global native protocol must not be changed to demand exact-boundary time.

## Lock, accounting and source observations

The probe forks actual winner and loser processes. Winner holds the native campaign-directory flock while blocked at intent_published. Loser reaches the same inode's real LOCK_EX call through a recording wrapper; parent opens another descriptor and requires LOCK_EX|LOCK_NB rejection and loser waitpid WNOHANG `(0,0)` before releasing winner. Durable SUBMIT/TERMINATE order is checked in both arrangements. This is a real flock test, not a thread-lock substitution. Its signal marks entry immediately before the blocking syscall, and is interpreted with the pinned inspector and durable order, not as independent kernel syscall tracing.

Seen bytes and the fixed response are repeated through fresh private-FD bootstrap at TTL; worker requires unchanged raw bytes and exact receipt hashes. Native governor/event/Ledger verification recomputes charges. Schema-invalid accepted admission consumes one trial and one validation round, zero execution/compute; rejection consumes no trial. Final report remains FAILED/NOT_EVALUATED with no selection and explicit unavailable internal host usage. The second fresh resume must preserve all files/directories and the native status/report. Copy-root inode facts do not stand in for the source lock inode: source wrapper opens the original retained campaign directory and checks all process lock identities.

The source wrapper requires all four finite cases/four phases, exact snapshot/sidecar origins, original after authority bytes/directories, installed worker/native program, profile/campaign/finite argv, prelaunch/completion, kernel namespace/credential/PID binding and exact phase-specific exit files. Races also require the separately source-bound original barrier. Manager-only finite case selection adds no research RPC testing capability. The helper never grants the complete Q06 gate.

Independent functional fork/flock controls: **5 passed in 23.57s**, `/tmp/hm-q06-lifecycle-independent-controls01.log`, SHA-256 `7642b9aad643dae19f7a5f9da19d1f13c3e609e3a12fac8e18f0d64ca87d0f85`. A separate shared Q06 source-gate synthetic baseline passed; campaign/profile/exit/kernel/program/family/command/namespace/unknown-case mutations all rejected. Script `/tmp/hm_q06_source_gate_independent.py`, SHA-256 `310317bff2d15873b75b388f38a06eebe91f025fa1c148e2ee22997eae640abf`; log `/tmp/hm-q06-source-gate-independent01.log`, SHA-256 `fcf9f1efd66ca92f8c11eace3bc595413f4043cc993f896426895b195bdb3634`. Those kernel records are synthetic and do not establish original installed provenance.

Two genuine positive failures remain preserved: native-e2e01 **1 failed/26.18s** because validation rounds were incorrectly required zero, and native-e2e02 **1 failed/36.02s** because native first-expired SUBMIT `(budget, terminal, receipt)` was absent from file closure. The finite correction rebuilds the exact service EXPIRED terminal only when no prior acceptance/terminal exists and time is at/after expiry; exact canonical tuple checking still rejects arbitrary extra/wrong terminal publications. Source execution/protocol logic was unchanged. Native-e2e03 then **1 passed/51.14s** with four synthetic native scenarios and twenty mutations; that supplied positive is not closure of the independent +1s counterexample. Its log SHA-256 is `ecd29b5f76d5b6cf5ffc19a2a9d9f6f4189f63c2fcf7a65c14680a219da49687`.

The frozen-B17 component01's original old-module failure remains unchanged. No complete installed original-source lifecycle observation or seven-budget matrix is available here. The reviewer changed no implementation, historical roots, frozen worktree, credentials or provider/model; only new review documents and disposable independent components were written. Successor clock closure must be recorded separately.
