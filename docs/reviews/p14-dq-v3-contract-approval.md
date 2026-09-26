# P14-DQ v3 contract approval record

Status: **APPROVED CONTRACT — append-only review record**

This record binds the independent contract approval that activates the P14-DQ v3
engineering acceptance amendment. It is immutable historical evidence: it must not be
edited to change a hash, a verdict or a claimed authority. Any later amendment needs its
own review record and its own clean implementation commit.

Loading this record does not by itself qualify P14-DQ. Qualification requires a separate
clean-commit, independent double-root run plus full bottom-up verification, and then an
independent acceptance review of that run's evidence.

## Approved bindings

approved_contract_sha256:
563b1c44ff8e3b87822902c1f70183de2ddd97b007550f2028990bb37f858e17

approved_contract_path:
docs/p14-dq-qualification-contract-v3-draft.md

approved_implementation_commit:
0130faa5d78d857d34bd12af99027d2bcd23ee16

review_verdict:
APPROVE

review_harness:
Codex

review_model:
GPT-6 Sol

review_reasoning:
High

review_context:
fresh independent context; not a continuation of any earlier reviewer session

authority:
v3 contract may serve as P14-DQ clean-commit qualification baseline

non_claim:
approval itself is not P14-DQ qualification

## Rejection and fix chain

rejected_v3_commit:
4d97b2452dfccdda30f93f0492fd8c02f33f7cb6

rejected_v3_reason:
zero-eligible acceptance was decided by the aggregate SOFT_REJECT / HARD_REJECT trial
outcome, so a PIT, data-quality, reproducibility, artifact-integrity or evidence gate
rejection could have been laundered into an engineering PASS

fix_commit:
0130faa5d78d857d34bd12af99027d2bcd23ee16

fix_summary:
the zero-eligible exception is now decided by a positive allowlist over each candidate's
complete verified ValidationReport gates: SUCCEEDED with verdict REJECT, exactly the
frozen eleven gates in frozen order with frozen severities, G0/G1/G2/G4/G9/G10 PASS, no
NOT_EVALUATED gate, and every REJECT gate a SOFT gate in {G3,G5,G6,G7,G8} with
reason_code SOFT_THRESHOLD_NOT_MET, with at least one such genuine research-threshold
rejection. The aggregate TrialOutcome remains historical run evidence only.

## Retained history and non-claims

- The v2 failed attempt at
  `artifacts/qualification/p14-dq/attempts/sha256-c9db27763e6b39be70fe96fe1047cd3f39f593b891f035f999864b0567eeeed0`
  remains an immutable historical `FAILED / NOT_EVALUATED / SOURCE_INCOMPLETE` record.
  It is not promoted, relabelled or superseded by this approval.
- The rejected v3 bytes remain non-authoritative and produced no qualification report.
- v3 is an engineering acceptance amendment adopted after observing the v2 zero-eligible
  natural outcome. It changes no research semantics.
- This approval creates no alpha authority, no profitability authority, no
  candidate-selection authority, no sealed-confirmation authority, no live-Agent
  authority, no FR-03 authority, no unrestricted autonomous research authority and no
  vendor-vintage PIT claim.
- P14c eligibility, Validation thresholds and gates, PIT rules, the frozen family and
  candidate denominator, the multiple-testing procedure and the sealed/OOS rules are
  unchanged by the approved amendment.
- Approval pins the exact contract bytes above. Editing
  `docs/p14-dq-qualification-contract-v3-draft.md` produces different, unapproved bytes
  and invalidates this record.
