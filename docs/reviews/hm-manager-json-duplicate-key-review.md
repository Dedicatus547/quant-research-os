# Manager JSON capture — independent narrow review

Date: 2026-10-01. Reviewer: independent `gpt-6.1-sol`, high reasoning. Baseline `5026a64171eb95180ffeffc2f27fd74d397ebc8e`, reviewed with uncommitted changes.

**CLOSED only for duplicate-key collapse at the two management JSON entrances. NOT_QUALIFIED remains.** This report does not accept HM09, any Q gate or the MVP. No implementation, old failed root, credential or model endpoint was modified or accessed; no full CI ran.

## Reviewed source identity

| Source | SHA256 |
| --- | --- |
| `src/quantos/infrastructure/hosted_manager.py` | `ab620ffaa519f74c911eb7f1d324f76cad62b727ef4de32a699e8438c887a913` |
| `src/quantos/contracts/hosted.py` | `9c4522543e6f1b97420358c7d2cc941ce6161d18a663c8c6d8074d2b220b4482` |
| `tests/unit/test_hosted_manager_client_capture.py` | `eccadbd07057dbb2f5d408f493a2a141d98a710fe09696dd3502a0a135bf5699` |
| `tests/unit/test_hosted_manager.py`, supporting static read | `dc54289fd3c1b52a4ff72da60cdb98725a3c8d9b868e17ab2729c27cc21f3d34` |

The first three hashes were recorded externally before launching the successor diagnostic and component tests, and verified unchanged after both finished. The initial private-name `_pairs` revision and its test-assertion failure were retained separately; they are not the successor source's execution evidence. These local source-byte checks are not an installed-module/import attestation for a qualified deployment.

## Defect and correction

The original `/tmp/hm-manager-client-capture-unit01.txt` retains seven `duplicate_keys` cases that failed with DID NOT RAISE, one for each fixed CLI operation. Seven additional failures were mistaken network-argument expectations in normal controls. The log has SHA256 `4d8c5704db2ecd3474e1cfa1a1e1de35968c2f681741a428cbfa1a5bcfe7b1ee`; neither group of failures was overwritten or treated as successful evidence.

Previously, ordinary `json.loads` collapsed duplicate keys before canonical serialization. `strict_json_object` then saw an already collapsed object and could not recover the rejected input ambiguity.

Both `restricted_client_call` and `_observe_namespace_child` now decode strictly as UTF-8 and supply `unique_json_object_pairs` to their first `json.loads`. That callback rejects a repeated decoded key in every parsed object, including nested objects and objects inside arrays. The callback is the existing contract parser's duplicate-key logic, renamed publicly with an unchanged body; `strict_json_object` uses the same function. Escaped and literal spellings of the same decoded key are rejected before canonicalization.

Canonicalization remains necessary because legitimate CLI and bubblewrap output may be pretty JSON. Subsequent strict parsing still checks the canonical object and its byte cap. Nonfinite values are rejected by canonical serialization. The existing raw-input caps remain 1,052,672 bytes for CLI capture and 4096 bytes for container information. No namespace, syscall, operation, capability, result-source or kernel identity predicate changed in this correction. The fixed host profile's existing `--share-net` is preserved; this review made no external network request. The nearby Q06 timeout change is outside the JSON closure claim.

## Independent successor evidence

New roots `/tmp/hm-manager-json-independent-review01` and `...review02` were used. Review01 preserves **7 failed, 42 passed in 6.77 seconds**, caused by the stale normal-control expectation that the fixed host profile omitted `--share-net`. It also preserves its first diagnostic. No original failure root was repaired.

The successor review02 independently ran **20 passing controls** against the stable source bytes. Each management entrance was tested with:

- top-level duplicate, escaped duplicate, nested duplicate and duplicate inside an array object;
- invalid UTF-8, UTF-16 input, nonfinite number, nonobject and an over-cap input;
- a valid positive control.

For CLI capture, the process output was an explicit synthetic double. Valid pretty JSON returned its expected object. Every rejection closed the passed private descriptors, and the complete fixture inventory remained unchanged. These cases do not prove actual installed CLI operation or network isolation.

For namespace information, the positive control used an actual `/usr/bin/bwrap --unshare-all` wrapper and a fixed `/usr/bin/sleep 30` child. The manager read its real information fd and `/proc`, checked the actual parent chain, command, executable hash and namespace identities, and accepted bubblewrap's original pretty JSON. Negative information bytes were written only into this new diagnostic's private fd; the parser rejected them. Restoring the original bytes revalidated the same actual service PID. The wrapper was terminated and waited for, and the fd closed. This is a bounded native parser/kernel compatibility component, not evidence of a real hosted deployment's startup or accepted readiness. The original kernel information bytes were held in that private fd during the control, rather than exported as a qualification bundle.

The successor command `.venv/bin/python -m pytest -q tests/unit/test_hosted_manager_client_capture.py --basetemp /tmp/hm-manager-json-independent-review02/pytest` completed **49 passed in 6.63 seconds**. It exercises all seven CLI operations, capture failures, private-fd cleanup and existing probe guards through process doubles.

All following evidence paths are relative to `/tmp/hm-manager-json-independent-review02`:

| Evidence | SHA256 |
| --- | --- |
| `source-before.json` and identical `source-after.json` | `92278e62578a0fd8d544dddacfd678c1889677bf2ea53e1f5005554771fe36db` |
| `independent.py` | `9c8030c7652ec7311f030e7a36c6c4cfb7d21aace378af26b73f111494ea56c8` |
| `independent.txt` | `cde75f01294b66f0699bd8c8ce0f4fb8733bbc8851585085dc1a9ab195a1c57f` |
| `independent-result.json` | `4be1c6c391594425013ea16bcccfe4ce2d1ad780a0690be2ded5507fdd6b8662` |
| `unit.txt` | `4a4ddf9e1c4c10d7914366f743a09fccf318f7d3db5f14c8fefc74d4194fb5ef` |

No remaining blocker was found in the two JSON parsing changes. Formal acceptance still requires new frozen source/install and actual complete manager-origin evidence; functional doubles, native parser controls and preserved historical failures do not grant qualification.
