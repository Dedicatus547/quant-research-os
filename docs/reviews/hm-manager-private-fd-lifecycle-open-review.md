# Manager cleanup after readiness — second independent OPEN review

Date: 2026-10-01. Reviewer: independent `gpt-6.1-sol`, high reasoning. Baseline `236955448d4e7683836d8b527625a371dcfed6e5` with the second uncommitted manager correction.

**Information-FD leak CLOSED on these bytes; post-readiness cleanup lifecycle remains OPEN. NOT_QUALIFIED.** The first source's OPEN report is retained unchanged in `hm-manager-private-fd-cleanup-open-review.md`. This second report neither changes failed roots nor grants HM09, D24, D25 or MVP qualification. No authentication, model/provider call or full CI occurred.

| Reviewed file | SHA256 |
| --- | --- |
| `src/quantos/infrastructure/hosted_manager.py` | `8a66a9295bbce5505fe21b34dbae76bc773d4d1cb168101708c7f151637624ee` |
| `tests/unit/test_hosted_manager_start_capture.py` | `dda4ea18d6ca3773d8fe2f429498ab818aecbfc4f40809d5a8f0e70d307a721a` |
| `tests/unit/test_hosted_capability_hydration.py` | `02139db88a8597a495ad2a7156cc080126d270e0cf848f30460528b583b1d9cb` |

Both independent scripts record unchanged manager hashes before/after their controls. A read-only copy of the reviewed 8a66 manager bytes was retained at `/tmp/hm-manager-private-fd-independent-review02/reviewed-hosted_manager.py`. These local hashes/copies do not constitute an installed-module qualification attestation.

## Closed part

The two nested `finally` blocks make information-fd cleanup independent of `listener.close`. In a new root, all seven prior controls now leave no parent memfd open: information allocation failure, actual short capability write, getsockname error, accept error, bind-plus-close error, readiness-plus-close error and successful-readiness-plus-close error. The original three-leak diagnostic in review01 remains unchanged.

The two supplied unit files independently complete **28 passed in 4.99 seconds**. They use real private memfds and explicit socket, process, namespace/readiness and configuration doubles; those successes are not live/kernel isolation evidence.

## Remaining lifecycle defect

In these reviewed bytes, `return _wait_for_managed_service(...)` is inside a try/except that handles readiness errors, but `listener.close` and information-fd cleanup occur in its outer `finally`. If readiness succeeds and listener.close then raises, the exception leaves that finally without entering the already-started process's terminate/wait handler. The pending return is cancelled, so the caller gets an exception rather than the live process object it would need to manage.

A separate bounded control uses **real non-model Python subprocesses**, the original parent's live lifetime, real memfds and declared socket/readiness doubles. The Popen factory explicitly substitutes fixed local Python `time.sleep(60)` for the installed service command; no Codex, model or real hosted service is started. `start_new_session`, private pass-fds and the fixed minimal child environment remain. Readiness returns the actual live Popen object. Its behavior demonstrates ownership, not the authenticity of service readiness or OS isolation.

| Actual native control | Normal listener close | Listener close error after readiness |
| --- | --- | --- |
| Parent capability/information memfds | both closed | both closed |
| Caller receives actual live Popen | yes | no |
| Caller sees exception | no | OSError |
| Actual child still running immediately afterward, while original parent lives | yes, with caller ownership | yes, without returned caller ownership |

The observations use the real Popen poll/waitpid behavior. The source did not terminate or wait for the error-path child. The independent diagnostic retained its own separate Popen reference solely to observe and then clean it up; ordinary callers do not receive that side reference. Its finalizer terminated and waited for both children, leaving no process behind. This is a direct postlaunch failure-handling omission, not a claim that the doubles establish a deployed namespace or scientific authority.

The cleanup block must participate in the same already-launched-process failure boundary as readiness, or use another policy that preserves process ownership explicitly. On a failing cleanup path, a live child must not be hidden behind an exception with no returned owner. Existing successful argv/readiness behavior and retained truthful NOT_QUALIFIED observations need not be changed.

## Evidence

All paths below are relative to `/tmp/hm-manager-private-fd-independent-review02`. The old review01 leak records and all named original root-agent failures were left untouched.

| Evidence | SHA256 |
| --- | --- |
| `reviewed-hosted_manager.py` | `8a66a9295bbce5505fe21b34dbae76bc773d4d1cb168101708c7f151637624ee` |
| `independent.py`, seven parent-fd controls | `29bb85c721f3fe54048146782a0f5e475c3b53b46d5d5a8e990151c5b960463e` |
| `independent.txt` | `a527f5fa6123b5a9354391124a2218450e33462714303ad4160796195165ecc7` |
| `independent-result.json` | `4c507774d301bee12a43ee4184d7e7d0e8efb7d51a9835b0c4354cd723f64297` |
| `native_lifecycle.py` | `837741264692d2cee0b3430b2dcf1f5bc9f476b56439243aa9abdad199648306` |
| `native-lifecycle.txt` | `90a96e6a12ce63b9b55d2a555b1ca5090da608d8f39a1ee4bf12f13297680704` |
| `native-lifecycle-result.json` | `4d68a4157ecb82f4064689d2a223ca6cfa17ee7ba0fe3d432569c029847e9e88` |
| `unit.txt` | `3b12e2e805c8bf79a64b4f2c12edae795221aa07a2e0e2d71569a1cb814bd1ef` |

The evidence hashes were verified against the preserved files before sealing. The native result JSON binds the two actual parent/child PID observations, error/return disposition and parent-fd closure. A later source repair needs a separate new-root closure control; this report remains OPEN for the reviewed 8a66 bytes.

The unchanged ≥85% full CI and complete matrix must run against a newly committed source/wheel/D25. An in-progress D24 run cannot qualify these successor bytes.
