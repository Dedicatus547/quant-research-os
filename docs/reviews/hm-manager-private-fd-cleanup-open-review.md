# Manager private FD cleanup — initial independent OPEN review

Date: 2026-10-01. Reviewer: independent `gpt-6.1-sol`, high reasoning. Baseline `236955448d4e7683836d8b527625a371dcfed6e5` with the originally supplied uncommitted correction.

**OPEN: information memfd cleanup still depends on listener.close succeeding. NOT_QUALIFIED.** This report binds the original reviewed bytes below; a later repair requires a separate closure review. No implementation, old failed deployment root or original diagnostic was modified. No authentication, model/provider call, full CI or HM09 acceptance was performed.

| Reviewed file | SHA256 |
| --- | --- |
| `src/quantos/infrastructure/hosted_manager.py` | `0ff8c99fbfbd762fa949e40ba0ff9e8af3a684089669e32c41dc33c8f472afa0` |
| `tests/unit/test_hosted_capability_hydration.py` | `02139db88a8597a495ad2a7156cc080126d270e0cf848f30460528b583b1d9cb` |
| `tests/unit/test_hosted_manager_start_capture.py` | `83ffb56cf6811826dfc0b05e47b40019f401c8f96bf815e7553f1f3a7d3b3bb4` |
| `src/quantos/infrastructure/hosted_service.py`, supporting read | `e0f64903e047f1b2dacad12c11674aba576974e66992adc2cc533188d52bb42c` |
| `tests/unit/test_hosted_manager_client_capture.py`, fixture supporting read | `eccadbd07057dbb2f5d408f493a2a141d98a710fe09696dd3502a0a135bf5699` |

The supplied manager hash was observed before and after the independent seven-control diagnostic; its result file records identical before/after hashes. The manager subsequently changed while this OPEN report was being prepared. A source-copy attempt rejected the changed hash before writing any copy; no later source bytes are represented as the original 0ff8c99f revision.

## Finding

The `_memory` correction properly closes its real private descriptor on write errors, short writes and seek errors. The expanded startup try block also closes allocated descriptors on the tested information-fd allocation, socket construction, bind/listen/control-connection and other preparation errors.

However, in the supplied source both cleanup locations call `listener.close()` followed by `os.close(info_fd)` sequentially. If the first close raises, the second close is skipped. The outer `finally` still closes the capability fd, so this is specifically an information memfd ownership leak.

An explicit close-error listener double and real memfds independently reproduce the omission in three paths:

| Scenario | Capability memfd | Information memfd |
| --- | --- | --- |
| bind error, then listener close error in preparation except | closed | still open |
| readiness error, then listener close error in terminal finally | closed | still open |
| readiness return, then listener close error in terminal finally | closed | still open |

For the readiness-error case, the process double received terminate and wait before the remaining information-fd leak was observed. The successful-readiness case also propagates the cleanup error; this fixture does not establish behavior of a genuine service process. Each leaked descriptor was checked open with real `os.fstat`, with `st_nlink == 0`, then closed by the independent diagnostic itself. The close-error and process/readiness behaviors are declared doubles; this is not a syscall/OS or live deployment qualification.

The two independent cleanup operations must be exception-independent, for example through nested `finally`, so failure of listener.close cannot skip information-fd closure. The reported defect is within the private-FD ownership repair, not a change request for fixed argv, namespace rules or service readiness.

## Independent evidence and limits

New root: `/tmp/hm-manager-private-fd-independent-review01`.

The other four independent controls pass: failure to allocate the second information fd, an actual partial write of the capability bytes, getsockname failure and accept failure. They leave no staged memfd open. The bounded current unit command for the two supplied test files completes **25 passed in 4.99 seconds**. These tests do not include listener-close errors and therefore do not close this finding.

| Evidence relative to the new root | SHA256 |
| --- | --- |
| `independent.py` | `b1733cbe80aedb99321ddc197595985ea5e78a7c6c0cd9b7290587aa971ee9a8` |
| `independent.txt` | `3e348f00df1693a6a153d1268fa5eeddab94b938c473b613208d8f20234fda22` |
| `independent-result.json` | `8221d90a6796a7448e275d476554f83272c1844d892227205ef04349a6d7b907` |
| `unit.txt` | `58148a42bdebe188876ce093f5d26d7cf650780f75bcf53849bb7bd06aeb7aae` |

The original `/tmp/hm-manager-start-unit02.txt` remains **4 failed, 8 passed**, SHA256 `eb4f4f5ab6710469fe665648e1940359a8284779c70386ec63360a45bb0bf82d`. Its four socket/bind/listen/connect failures are genuine original FD-leak controls. The original command-order fixture failure `/tmp/hm-manager-start-unit03.txt` also remains; SHA256 `aed5f5acc3e2d35e37728d27bbde2dfd395f95c36be1dde5ea0ed0da6bcfd75e`. Existing successor component logs `/tmp/hm-manager-private-fd-unit01.txt` and `...unit02.txt` were read only, not substituted for an independent closure control.

No failed root was repaired, no native authority root was borrowed, and no old D24 result can qualify this changed source. A separate repaired-source review, new commit/wheel/D25, complete CI with the original ≥85% threshold and complete matrix remain required.
