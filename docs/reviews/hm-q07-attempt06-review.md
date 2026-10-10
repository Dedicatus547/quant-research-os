# HM Q07 attempt06 independent boundary successor review

Date: 2026-09-30. Status: **Q07_BOUNDARY_REVIEW_NO_OPEN_P1 / NOT_QUALIFIED**. This is a narrow review of original deployment observations and their verifier. It does not grant Q07 qualification, complete HM-07, or replace the required exact-commit/bundle HM-09 review.

The reviewer was assigned `gpt-6.1-sol/high` under the user's development/review override. Observed model, reasoning effort and usage are unavailable to the reviewer. The frozen research model remains `gpt-6-sol/high`. No additional agents were used. Implementation and frozen records were read only; the only repository addition by this reviewer is this successor record. No real credential contents were read and no commit was made.

## Exact deployment and original evidence

The reviewed HEAD was `9ae5537dcb06cb2f9c6cd1caf85b8b65fa9f8022`. The original manager root was independently specified as `/tmp/hm-stage-9ae5537-attempt06`, rather than selected from uploaded evidence. The deployed profile hash was `b9ff7d3c0986f9e7111cc739dcf5330907a5d3f6dd5b69f3e26835300311db9a`, and the hosted specification hash was `0995c1cec0809530d55cf8fe5bd0d87de0a21d5fe08367c4eb7ec693e05b3e10`.

| Original file or frozen binding | Size / SHA256 |
| --- | --- |
| `evidence/deployment-probes.json` | 22,338 bytes; `59765f155fdd19e3cd4a3b70c3b264af1ce1f3931b7809f88ac9e06e1ee10464` |
| `evidence/service-start-cbc46d6daf0c71de1c83045253082b9a3a9ddae4244db8ac8891bc6547847c63.json` | 3,132 bytes; `95caccf0403705b21b8b4988f85029fd6d1b4bd2734847d161b12ac398eef410` |
| Original service bootstrap observation | 5,434 bytes; `cbc46d6daf0c71de1c83045253082b9a3a9ddae4244db8ac8891bc6547847c63` |
| Install inventory | `07d5c65251570e90fa67622fa80b04611b4109d3734d49d7d3a7ac2b1c4cbf76` |
| Installed and repository probe program | `6e5e6bdb5d6c8dff6ea03170620ba6e08db0653d6494ffb85815d817451c67d3` |
| Source seccomp BPF | `a66ee36d025856553d5516ac52783c18c530b057d18bfadf637e7e3c5605defb` |
| Actual service executable | `6e06066e6b81eae1d2929546f29917435295900b0d272449ea4fdc5c92d3fe9a` |

The original JSON evidence was canonical. The reviewer independently loaded the explicit deployment and executed `verify_deployment_security`; it completed and returned the four expected probe/program/start/bootstrap hashes. This is a local mechanical boundary check, not an independently awarded qualification case.

At inspection, `hosted_case_predicates.py` was untracked and `hosted_verification.py` had an uncommitted Q01/Q11 dispatch addition. Those drafts do not belong to the frozen deployment's reviewed source origin merely because they coexist in the checkout. The overall HM-07 matrix remains unfinished.

Inspected code hashes:

| File | SHA256 |
| --- | --- |
| `hosted_probe.py` | `6e5e6bdb5d6c8dff6ea03170620ba6e08db0653d6494ffb85815d817451c67d3` |
| `hosted_manager.py` | `293b7d4b620107856a43bb3cb35292255e43ab79425010eb606b4d88d9c681a7` |
| `hosted_security_verification.py` | `63d44ad04c4e61f8e4419ebb5a43d10813b9265b46c2629e61b1dfcda4721214` |
| `hosted_qualification_sources.py` | `a994d871288204458ed0ad2b5ca1c12bdd00609bd6c6f4709c51f140b007642b` |
| `hosted_deployment.py` | `4bbe2c3cd1ab8e8c0d33e246918980236736a3272bec5612149863ebd7f05e0f` |
| Draft `hosted_case_predicates.py` | `cf864dadce8cef4c0f62222842a14c5e7da7127dc7dfb1f0baba21876b135835` |
| Working-tree `hosted_verification.py` | `952b26d603659abd8fb0aeffb8beb00b49635811e5af502f6aaf039d0a870699` |

## Concrete improvements and evidence limits

The attempt addresses the principal missing observations from the earlier probe review. The manager checks expected install, projection, configuration and BPF before launch, and retains before/after inventories afterward. The 21 authority files were unchanged, and actual event and Ledger files existed before the restricted probe. The event and Ledger paths are recorded in the original probe fact. Source, configuration, projection and install inventories are also checked.

The installed host probe ran with uid/gid 1000 and a distinct namespace boundary. It observed isolated Python initialization, ignored environment and user site, safe path, and disabled hash randomization. Its import paths were under `/install`. Real canary files exist at CWD, PYTHONPATH and user-site locations; an ordinary interpreter found the import, whereas the isolated child and probe did not. File writes against installed source, the fixed CLI and a nonexecuting Python binary returned EROFS. Although the executing native launcher's write attempt returned ETXTBSY, the independent `/install` read-only mount observation and other EROFS attempts supply the actual read-only evidence; ETXTBSY is not treated alone as permission isolation.

The effective syscall probes now include a successfully opened self pidfd and an existing private nonsecret target FD before `pidfd_getfd`, and a real one-byte iovec against the manager's nonsecret memory-canary address before `process_vm_readv`. Both returned EPERM, as did ptrace, unshare and setns. The frozen BPF denies the relevant syscall entry points. The target manager is outside the host PID namespace; these observations show denial before useful access, not that a restricted process successfully resolved or read the manager. The `setns` argument remains an invalid FD, so that row alone is not proof of access to a valid external namespace. The BPF binding, real unshare attempt, hidden proc, valid pidfd attempt and mount boundary must be considered together.

The channel replacement test now uses an actual forked process, a start pipe and 128 bounded attempts while the parent issues eight authorized queries. All 128 replacement attempts returned EXDEV; all queries succeeded. EXDEV proves refusal of that cross-filesystem replacement operation and is not itself a read-only permission proof or an exhaustive race proof. Independent symlink and unlink attempts returned EROFS, `/channel` was observed read-only, and the manager retained unchanged authority and source inventories. This combination is adequate for the reviewed deployed boundary. Future reports should not promote the count or EXDEV alone into a broader claim.

Wrong capability and wrong campaign API calls failed, the valid status control succeeded, and the attempted unrestricted `execute`/command header closed without a reply. Sealed/vendor/source canaries, service capability and parent/proc FD/root paths were inaccessible. The canaries are nonsecret; the probe's path access attempt does not read real credential contents.

The external service observation now resolves a real process chain from bubblewrap's private `--info-fd`, rather than accepting a service-supplied PID: wrapper `1270013`, init `1270015`, service `1270017`. The manager validates the wrapper-to-init and init-to-service parent edges, requires a single fixed child command, hashes the kernel `/proc/<pid>/exe` reference, and reads that child's namespaces and process status. The recorded command and executable hash match the frozen native service entry. The external namespace identities match the bootstrap's self-observation:

| Namespace | Service / manager |
| --- | --- |
| net | `net:[4026532409]` / `net:[4026531833]` |
| pid | `pid:[4026532284]` / `pid:[4026532219]` |
| mnt | `mnt:[4026532243]` / `mnt:[4026532216]` |
| user | `user:[4026532483]` / `user:[4026531837]` |

The actual service's external status records uid/gid 1000 in all credential slots, no effective capabilities, `NoNewPrivs=1`, and namespace PID 2. The service has `Seccomp=0`; this record does not claim a service seccomp filter. The research host has seccomp mode 2. Service isolation is supplied by its separately bound namespace, mounts, frozen initialization and production entry. The manager's network listener positive control connected; the service's same-port loopback attempt failed with ECONNREFUSED and its net namespace was externally distinct.

Matching UID is therefore not the proof. The proof combines a frozen launcher and install, an initially empty controlled channel, an actual externally observed new child, matching original bootstrap bytes and distinct namespaces with denied host syscalls/API operations. No producer `PASS` field is used to decide this local predicate.

## Original-manager export boundary

`verify_manager_export` requires the caller's independently supplied absolute `--manager-root`, rejects equal/nested source and upload roots, and compares the uploaded export record with its exact retained content-addressed original. It binds the profile, exact commit, lock, install and provenance inventories to the original deployment. The exact manifest file set is matched to export mappings; every mapping is checked against original source-path bytes and uploaded bytes using descriptor-anchored, non-following regular-file traversal. `root_origin` requires each root file to retain its suffix under one original source prefix.

These checks do not inspect an uploaded `TRUSTED_EXTERNAL_MANAGER` string as proof. The source unit fixture deliberately includes that label and a self-reported PASS; changed source, upload, retained record, file set or installation still fails. The model-source verifier separately rechecks original request/response/exchange/receipt and direct launcher-capture/projection/isolation bindings; exact copying is not by itself proof of a real model call.

The trust anchor remains an operator boundary: the verifier caller must choose the original manager root independently from the restricted host and uploaded manifest. Absoluteness and being outside the upload directory do not authenticate an arbitrary attacker-created directory. A wrapper must not derive `--manager-root` from uploaded source labels or metadata. Original manager roots and retained records must remain outside research-host write authority and remain available for future verification. This review found no uploaded-label shortcut in the inspected export implementation.

The Q01/Q11 draft consumes these verified source mappings and typed original facts; it does not complete the other Q predicates. No completed live model source, scenario matrix or qualification bundle was produced by this review. No new clear P1 in these two draft predicates was established within this boundary review; that is not a full implementation approval.

## Independent execution and remaining blockers

The reviewer executed the local security predicate against the original attempt06 root once; it completed successfully. The origin and manager unit suites were also run twice in different environments:

- Default tool sandbox: **16 passed, 1 failed**. The real child-identity test attempted to observe an early info-fd child PID after the child disappeared, raising FileNotFoundError. A bounded direct reproduction captured the reason: bubblewrap exited with code 1 and `bwrap: loopback: Failed to create NETLINK_ROUTE socket: Operation not permitted`. The default process's own `getpid` and `/proc/self/status` PID were consistent; an inconsistent self PID/proc view was not demonstrated and is not asserted here.
- Authorized external execution matching the actual manager environment: **17 passed in 4.81 seconds**. It used only the offline nonsecret sleep/namespace and origin fixtures. Its own process PID, proc PID and NSpid were also consistent.

The failed environment attempt is retained in this record. The manager checks process liveness and rejects observation exceptions; an unavailable child or unsuitable management environment must not be repaired by guessing a PID. These tests establish the distinction between the supported actual management environment and the restricted tool sandbox, not a waiver for unsupported deployment environments.

There is no new open Q07 boundary P1 established for the exact attempt06 artifacts. Qualification remains blocked by the incomplete overall Q01–Q12 mechanical matrix, complete immutable bundle/export mapping and failure-attempt retention, live/replay scenarios as separately required, full CI, and the mandatory independent exact-commit/bundle acceptance review. Subsequent source/profile/probe changes require fresh matching deployment evidence. No model calls or profitability claims were part of this review.

Frozen hashes remained unchanged: contract `14704b9cbbe0f0ca281751833bc08248820da0c277a281a140bfd12bc6b102df`; acceptance `e5877b503259f6e758f22a6feb9307efdc45397155a9229527b2a8ae5dbfc55e`; freeze manifest `ac5a4c5e01e8c064906342607ff2ef9f3e9e9b98429188689e6873f76b2ee52e`.
