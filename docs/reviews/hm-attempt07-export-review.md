# HM attempt07 installed request export — independent original-evidence review

Date: 2026-09-30. Review attempt: 1. Result: **INSTALLED_EXPORT_ORIGINALS_VERIFIED / NO_OPEN_P1_IN_SCOPE / NOT_QUALIFIED**.

The explicitly requested development-review model and effort are `gpt-6.1-sol / high`; observed usage is unavailable. This does not change the frozen research profile `gpt-6-sol / high`. This review does not accept HM09 or the full MVP. The reviewer read no real authentication material, invoked no model, read no credential file, started no new service, changed no implementation, and made no commit or push. Only this successor review was added.

## Exact installation and retained originals

The reviewed repository HEAD was `463ec6d50bfd4b262a46964920db1698cb9322ab`; the working tree was clean at the start of this review. The independently selected original manager root is `/tmp/hm-stage-463ec6d-attempt07`. It is separate from the diagnostic export `/tmp/hm-q01-q07-463ec6d-attempt07`.

| Identity | Verified value |
| --- | --- |
| Deployment profile D | `0539efd3a44b42a33d13b454ee0e4ffd1c6e3f9f5855fdfbb03fec05f44db6dc` |
| Frozen business inputs B | `f2237ec3913e9d7ed1d13ac1467261cdf7d7185dd1e1e2c994cd7c5c0ffd52a1` |
| Frozen spec S | `1077bcf1d47c632485fc8c821a2ee728646fd9fe1a1a90b3d784d8456dc23848` |
| Campaign | `dab81ad199fd4fb2b38add47a45c8c722a440aa6cb23b260c0ada24f9bf64f26` |
| Wheel | `ac3d1745ba1648657d3594b4caabe2a53ab5a3cac1cb2886d128e49aa888e17e` |
| Complete install inventory | `fa55d34eab9bfc6b6e4580e712896f720c55d092e8f0c19d09140ba73dac2d2f` |
| Complete provenance inventory | `fc5e13e77ee615974b6f1ef803cf7ddd57d8ede2696fa57c43fd3b9a7f8e4b1b` |
| Native seeded executable | `6e06066e6b81eae1d2929546f29917435295900b0d272449ea4fdc5c92d3fe9a` |
| Probe program | `6e5e6bdb5d6c8dff6ea03170620ba6e08db0653d6494ffb85815d817451c67d3` |
| Source seccomp BPF | `a66ee36d025856553d5516ac52783c18c530b057d18bfadf637e7e3c5605defb` |

The reviewer independently recomputed the wheel hash, complete install inventory and complete provenance inventory. `verify_wheel_provenance` verified the exact project member set and bytes. Additionally, all **139** `quantos/` wheel members were compared both with installed project files and with `git show 463ec6d50bfd4b262a46964920db1698cb9322ab:src/<member>` in the retained provenance checkout. All matched; its HEAD also matched the frozen commit. Thus this request-export implementation is actually inside the frozen wheel and installation, rather than merely present in an editable working tree.

Important installed source hashes:

| Installed module | SHA-256 |
| --- | --- |
| `hosted_host.py` | `bd8dde490cf94efed97e7cb84ddf58f81d2ba0ce10dbbb7f7a28da0063420066` |
| `hosted_manager.py` | `c78820a82685b95e50f77163b98371a767a8993dc951bfb4276f27f4404a2d5c` |
| `hosted_service.py` | `ce86974c11e2a79ac0c0cae711768500b38d66202050872592c6b838b9126d24` |
| `hosted_verification.py` | `30bfb4f8c7d402f79df6ef36ef2e70240f1ad8122c8fa5ce22cb41199f0e2c83` |
| `hosted_case_predicates.py` | `960407f5e234ea7eea1c2893a14662d19e890d2010f47017fee8de5073b9b649` |

## Request export and exact authority bytes

The retained request-export observation is `evidence/request-export-probe-9d32f4221916e6722263f82a8a4fa8fc1939ffd2a15caeaf39823e4a4e4c1818.json`: 13,844 bytes, SHA-256 `9d32f4221916e6722263f82a8a4fa8fc1939ffd2a15caeaf39823e4a4e4c1818`.

The reviewer loaded the original protocol with `recover=False`, found exactly one full HostedAgentRequest, and checked its original object bytes against complete canonical serialization. Request R is `89c2908b46f720dd9c7694496754bed2a4ef0e940acece5fbbcc76adfae91929`; its original bytes are **15,482** bytes with **20** top-level fields. It contains the full business request and ContextPack, with ContextPack hash `1176887c259955b0f81681024a2ba15c4ba50056de5be36723ee287e85602c08`. It is not the four-field public pending summary.

The original canonical R byte hash, exported-request byte hash, exported-request identity and public pending `request_hash` are identical. The pending campaign and expiry remain bound to that full request by the protocol/Q01 verifier. The independent reverify driver calls the installed `restricted_client_call(..., "request-export")` three times and asserts complete object equality; it parses the full request with the required explicit `max_bytes=1048576` and checks it against the original saved request. The retained observation records the matched byte hash and the unchanged authority interval. It does not independently store three separate stdout transcripts, so this review does not describe three retained transcripts.

The installed manager selects the fixed `/install/python/bin/python3 -I -m quantos.infrastructure.hosted_host hosted request-export` wrapper, with output at the guest-private `/tmp/hosted-request.json`. The wrapper invokes the existing CLI, validates the bounded regular file with strict HostedAgentRequest parsing and returns its exact bytes plus a transport newline. It redirects optional import diagnostics to stderr. No new writable external mount or research-channel import operation was added. The manager's bounded JSON capture reserializes this complete canonical object; equality with the original canonical protocol object was checked, not inferred merely from a producer PASS field.

There are two distinct unchanged-authority intervals. The export observation's before and after inventories each contain **20** files and are equal. Every captured file still matches the current authority. The current authority has **21** files: the sole addition relative to that export interval is `sealed-canary`, created for the subsequent explicit Q07 management probe. There are no deleted or changed captured export files. The later Q01 before and after inventories each contain all **21** files and exactly match the current full authority. This addition is not hidden by claiming the earlier complete inventory equals the later complete inventory.

## Actual service origin, descriptors and process observations

The reviewer inspected all four retained service-start observations and their original bootstrap bytes. `verify_staging` recomputed Q07 through `verify_deployment_security`, which checked the complete installation, exact namespace argv, actual observations and required exported hashes. The source file descriptor values below are captured argv descriptors, not capability contents; no capability bytes were read or disclosed.

The service starts use `--info-fd 6` and `--file 5 /tmp/hosted-service-capability-0`. The actual installed manager launches with only those private staged descriptors, requires an empty stopped channel, and reads bubblewrap's bounded actual container information. Its external `/proc` reader verifies the init's parent is the launched wrapper, obtains exactly one service child, checks that child's parent/argv, hashes its actual `/proc/<pid>/exe`, and reads actual namespace identities and credentials. It does not trust a child-proposed PID or recover by guessing a PID. The retained process chains are:

| Bootstrap observation hash | Wrapper → init → service |
| --- | --- |
| `e3c7beae34ed6c108b416e66f93b98b368827196215d46fa72a2cdb7b2df94f9` | `1296142 → 1296143 → 1296144` |
| `9445b298def7c6a61083dd666b17be14d2dc915e00cef1f46463c34318d8435f` | `1296617 → 1296618 → 1296619` |
| `903f238fc6dd71acbcee1a74d81b8fc2b23895573a8bc5e631d5a104fefa57b6` | `1297030 → 1297031 → 1297032` |
| `72c3c169cc3c6d029c7f6a8fef9caaf8e8e74a39cb76fa48aab551dacd40ed36` | `1297160 → 1297161 → 1297162` |

The request-export observation's wrapper `1296617` binds to the corresponding actual service-start record. The restart diagnostic binds wrappers `1297030` and `1297160` to two distinct corresponding records. Each service executable hash equals the installed native seeded executable hash above. Observed service UID/GID are 1000, effective capabilities are zero, and NoNewPrivs is 1. The service's recorded Seccomp mode is 0: its approved boundary is the unshared namespaces and mounts, while the restricted research subject is actually mode 2. This review does not mislabel service Seccomp 0 as mode 2.

The service bootstrap reports the installed service module, `/install/python-seeded`, seed environment `0`, and actual flags isolated=1, ignore_environment=1, no_user_site=1, safe_path=true, hash_randomization=0. Its actual net/pid/mnt/user identities match the external process observations and differ from the manager's corresponding namespace identities. Manager loopback connection controls succeeded; the service's connection to that actual manager listener failed in its separate network namespace. These are retained observations from the actual starts; stopped historical processes were not claimed to be live-reobserved by this read-only review.

The retained deployment probe is 23,062 bytes with SHA-256 `684a5b7993a25be896cd6d5868d1c10100dee217ecd91c8770a993c901d96501`. Its original observation includes actual denied ptrace/process-memory/pidfd/namespace escape syscalls; the pidfd canary uses an opened valid self pidfd and valid private target descriptor, and the parent-memory check uses the nonsecret manager canary. All recorded calls returned EPERM. The real forked replacement race records 128 EXDEV results alongside eight successful authorized channel queries. Channel unlink/symlink operations return EROFS, and actual mounts are read only. EXDEV alone is not used as proof of a read-only mount. The executing launcher returns ETXTBSY, while nonexecuting installed binaries return EROFS; ETXTBSY alone is not used as read-only proof. Empty read-only research `/proc`, import-canary positive control/isolated rejection, wrong capability/campaign rejection, and closed management-API escape are also retained. Same UID and a producer PASS label are not substituted for these observations.

## Restart/query diagnostic and independent recomputation

`evidence/q01-diagnostic-attempt07.json` is 18,272 bytes with SHA-256 `aa4079fc8e2f6b2f745c75cbab4696f14c3715cefe40ff2ff9dde11f51d6cbca`. It contains six actual query results spanning the two distinct service wrappers. The two pending summaries preserve the same full request identity, campaign and expiry; the status results preserve one issued request, zero unique submissions, the original budget/journal identities and WAITING_FOR_AGENT. Its before/after full authority inventories are equal and match current authority exactly. Protocol verification binds the full original R, issued/expiry times and reservation, rather than interpreting the summary as a new request. No native research execution or model response is established by this diagnostic.

The reviewer independently recomputed `verify_manager_export` and `verify_staging` against the original manager root and diagnostic exported bytes. All **80** exported files matched retained original source bytes and the exact export file set; original installation/provenance identities also matched. Results were:

| Artifact | SHA-256 / identity |
| --- | --- |
| Qualification diagnostic manifest | `f4f1a35be3c4d4067053c9ad4a2f91660e61b85928f0976e1176ed0dbd2c78a4` |
| Original retained manager export | `0096f1966a0a94de2e8a4ded9e7507b63e5627d4df4b4413aa3b7aa529e162e2` |
| Independently reproduced result bytes | `0dfd7782c07e7313e49e85f703d03a565c67abed46760a29608d6f5428fde71f` |

The manifest canonical bytes and result canonical bytes matched the saved bytes exactly. Q01 and Q07 are PASS; Q02–Q06 and Q08–Q12 are NOT_EVALUATED. Eligibility is **NOT_QUALIFIED**.

The reviewer also invoked the unmodified formal `verify_bundle` on the existing diagnostic path. It correctly rejected `/tmp/hm-q01-q07-463ec6d-attempt07` with `qualification manifest bytes or path disagree`, because the basename is not `sha256-<qualification_hash>`. No directory was renamed or copied to evade this check, and no formal published-bundle verification was claimed. The independent lower-level staging result is a diagnostic and remains so.

## Retained first failure and limitations

The original staging attempt's `TypeError` remains in `staging-failure.json`: 70 bytes, SHA-256 `44e0bd27b468ddb0e62fe143c9c5c05b28f8aeadba37259a9219aff769b634e1`. `/tmp/hm-stage-463ec6d-attempt07.log` remains SHA-256 `44a18daee2736e457c86db5b9a25fc8cbb355ca0c8de7fd498faf3f8f16a5b43`. It records frozen inputs/deployment and a service reaching WAITING_FOR_AGENT before the TypeError. The developer reported the cause as its diagnostic request parser omitting mandatory `max_bytes`; the retained compact failure record alone does not contain a traceback proving that cause. The inspected corrected driver supplies the required argument. The failure was not overwritten or described as a successful first run.

The inspected independent driver `/tmp/hm_installed_export_reverify.py` has SHA-256 `185b3dac25a311e54756af5fd4859b15fcae588315448531e5f0e84750717d0f`; it supplies the explicit bound and invokes only installed query/export/probe operations, not authentication/model calls. The later `/tmp/hm-stage-463ec6d-attempt07-reverify.log`, SHA-256 `e193de7b65d693614cb3c2981e8921ccb7042814c3a7ce6ddca9778e4c08b212`, records successful installed request export and successful actual restricted probe. These management diagnostics were read, not rerun by this reviewer. They are not immutable model transcripts or Q09/Q10 native reexecution records.

Frozen contract, acceptance and HM02 freeze hashes were independently rechecked as unchanged: `14704b9cbbe0f0ca281751833bc08248820da0c277a281a140bfd12bc6b102df`, `e5877b503259f6e758f22a6feb9307efdc45397155a9229527b2a8ae5dbfc55e`, and `ac5a4c5e01e8c064906342607ff2ef9f3e9e9b98429188689e6873f76b2ee52e` respectively.

The diagnostic manifest's `failed_attempt_hashes` is empty and its exported file set does not include the staging failure/log above. Those original failures remain externally retained and explicitly recorded here; this diagnostic is not a claim that the final qualification failure ledger is complete.

No open P1 was found in this installed-export/original-evidence scope. Real live model origin, completed natural research denominator, receipt reuse, two fresh native reexecutions, other scenario gates, final formal publication and independent HM09 review remain unestablished here. **NOT_QUALIFIED** is retained.
