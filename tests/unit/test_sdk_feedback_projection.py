"""Existing immutable feedback is presentation context only; no SDK/model execution."""

import json
from datetime import UTC, datetime

import pytest
from test_discovery_comparison_regression import predicted as predicted
from test_discovery_offline_regression import design as design
from test_discovery_offline_regression import durable as durable
from test_discovery_recovery_regression import staged as staged
from test_registry_service import _evidence, _publish_report
from test_sdk_campaign_producer import setup as setup
from test_sdk_capture_v3 import _successor
from test_sdk_prompt_projection import _content, successor_v4

from quantos.application.sdk_prompt import prompt_projection
from quantos.contracts.base import sha256_bytes
from quantos.contracts.validation import (
    ReproducibilityComparison,
    RobustnessCaseResult,
    ValidationMetric,
    ValidationReport,
)


@pytest.fixture
def feedback_probe(setup, tmp_path):
    spec, request, *_ = _successor(setup, tmp_path)
    spec, request = successor_v4(spec, request)
    return spec, request


def test_validation_feedback_projection_retains_hashes_and_not_evaluated(feedback_probe, tmp_path):
    spec, request = feedback_probe
    root, _ = _publish_report(tmp_path, experiment_id="synthetic-feedback")
    report = ValidationReport.model_validate_json((root / "report.json").read_bytes())
    metric = ValidationMetric(
        metric="oos_sharpe", value=-0.1, source=_evidence(), detail="synthetic feedback only"
    )
    case = RobustnessCaseResult(
        kind="COST_STRESS",
        case_id="synthetic-case",
        dimensions=("cost",),
        observation_count=3,
        metrics=(metric,),
        evidence=(_evidence(),),
    )
    reproducibility = ReproducibilityComparison(
        left=_evidence(),
        right=_evidence(),
        exact_content_hash=True,
        exact_fields_checked=1,
        float_fields_checked=1,
        max_absolute_error=0,
        absolute_tolerance=1e-12,
        relative_tolerance=1e-9,
        passed=True,
        detail="synthetic exact comparison",
    )
    values = {
        key: getattr(report, key) for key in type(report).model_fields if key != "report_hash"
    }
    values.update(
        metrics=(metric,),
        robustness_cases=(case,),
        reproducibility=reproducibility,
        created_at=datetime.now(UTC),
    )
    report = ValidationReport.create(**values)
    raw = report.canonical_bytes()
    projection = json.loads(
        prompt_projection(_content(request, raw, "VALIDATION_REPORT"), spec.sdk_profile)
    )
    item = projection["business_request"]["context_pack"]["items"][0]
    shown = item["presentation"]
    assert item["original_object_hash"] == report.report_hash == sha256_bytes(raw)
    assert shown["verdict"] == "REJECT"
    assert shown["metrics"][0]["value"] == -0.1
    assert shown["metrics"][0]["source_sha256"] == _evidence().sha256
    assert shown["robustness_cases_count"] == 1 and "robustness_cases" not in shown
    assert shown["files_count"] == 4 and "files" not in shown
    assert shown["reproducibility"]["exact_content_hash_matches"] is True
    assert "ORIGINAL_FULL_EVIDENCE_IS_AUTHORITY" in projection["presentation_authority"]
    assert report.canonical_bytes() == raw


def test_research_feedback_projection_keeps_metrics_and_original_identity(
    feedback_probe, predicted
):
    spec, request = feedback_probe
    manifest = predicted.built.manifest
    raw = manifest.canonical_bytes()
    projection = json.loads(
        prompt_projection(_content(request, raw, "RESEARCH_RESULT"), spec.sdk_profile)
    )
    item = projection["business_request"]["context_pack"]["items"][0]
    assert item["original_object_hash"] == manifest.artifact_hash
    assert item["presentation"]["files_count"] == len(manifest.files)
    assert item["presentation"]["source_files_count"] == len(manifest.source_files)
    assert item["presentation"]["metrics"] == json.loads(raw)["metrics"]
    assert manifest.canonical_bytes() == raw


def test_failed_trial_feedback_never_becomes_a_success_claim(feedback_probe):
    from quantos.contracts.campaign import CampaignTrial

    spec, request = feedback_probe
    trial = CampaignTrial(
        trial_id="synthetic-feedback",
        idempotency_key="a" * 64,
        proposal_hash="b" * 64,
        candidate_hash="c" * 64,
        segment="DEVELOPMENT",
        outcome="EXECUTION_FAILED",
        execution_requested=True,
        compute_seconds=18,
    )
    raw = trial.canonical_bytes()
    projection = json.loads(
        prompt_projection(_content(request, raw, "CAMPAIGN_TRIAL"), spec.sdk_profile)
    )
    item = projection["business_request"]["context_pack"]["items"][0]
    assert item["presentation"]["outcome"] == "EXECUTION_FAILED"
    assert item["original_object_hash"] == trial.content_hash
