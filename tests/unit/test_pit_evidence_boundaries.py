"""Reject incomplete cross sections and future availability at serialized boundaries."""

from datetime import timedelta

import pytest
from pydantic import ValidationError
from test_discovery_offline_regression import design as design
from test_discovery_offline_regression import durable as durable
from test_discovery_recovery_regression import staged as staged
from test_discovery_variant_regression import pit_fixture

from quantos.contracts.research_execution import (
    PITCrossSectionEvidenceCollection,
    PITCrossSectionEvidenceCollectionV3,
)


@pytest.fixture
def compact(staged):
    return pit_fixture(staged)[1]


def versioned(compact, version):
    value = compact.model_dump()
    if version == 3:
        value.update(
            schema_version="pit-cross-section-evidence-collection/v3",
            execution_profile="frozen-field-study/v1",
        )
        for bundle in value["bundles"]:
            bundle["schema_version"] = "pit-cross-section-evidence-bundle/v3"
            for source in bundle["source_sets"]:
                source["schema_version"] = "pit-source-set-evidence/v3"
    kind = (
        PITCrossSectionEvidenceCollection if version == 2 else PITCrossSectionEvidenceCollectionV3
    )
    assert kind.model_validate(value).bundles
    return kind, value


@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize(
    "attack",
    [
        "expression",
        "delay",
        "duplicate_delay",
        "empty",
        "duplicate_bundle",
        "snapshot",
        "universe",
        "sources",
        "rows",
        "presence",
        "window",
        "members",
        "duplicate_member",
        "membership_count",
        "duplicate_source",
        "missing_source",
        "window_count",
        "gates",
        "failed_gate",
        "future_output",
        "future_membership",
    ],
)
def test_compact_proof_rejects_partial_or_inconsistent_serialized_evidence(
    compact, version, attack
):
    kind, value = versioned(compact, version)
    bundle = value["bundles"][0]
    source = bundle["source_sets"][0]
    if attack == "expression":
        value["expression_spec_hash"] = "f" * 64
    elif attack == "delay":
        value["operator_delays"] = ()
    elif attack == "duplicate_delay":
        value["operator_delays"] *= 2
    elif attack == "empty":
        value["bundles"] = ()
    elif attack == "duplicate_bundle":
        value["bundles"] *= 2
    elif attack == "snapshot":
        value["snapshot_hash"] = "f" * 64
    elif attack == "universe":
        value["universe_index"] = "000905.SH"
    elif attack == "sources":
        bundle["source_sets"] = bundle["source_sets"][1:]
    elif attack == "rows":
        source["expected_row_count"] += 1
        source["present_row_count"] += 1
    elif attack == "presence":
        source["maximum_temporal"] = None
    elif attack == "window":
        bundle["source_window"] = ()
    elif attack == "members":
        bundle["members"] = ("unsupported",)
    elif attack == "duplicate_member":
        bundle["members"] *= 2
    elif attack == "membership_count":
        bundle["membership_set"]["row_count"] += 1
    elif attack == "duplicate_source":
        bundle["source_sets"] *= 2
    elif attack == "missing_source":
        bundle["source_sets"] = ()
    elif attack == "window_count":
        bundle["required_observations"] += 1
    elif attack == "gates":
        bundle["gates"] = bundle["gates"][:-1]
    elif attack == "failed_gate":
        bundle["gates"][0]["verdict"] = "HARD_REJECT"
    elif attack == "future_output":
        bundle["output_temporal"]["available_at"] = bundle["schedule"]["signal_time"] + timedelta(
            days=1
        )
    else:
        bundle["membership_set"]["maximum_temporal"]["available_at"] = bundle["schedule"][
            "decision_time"
        ] + timedelta(days=1)
    with pytest.raises(ValidationError):
        kind.model_validate(value)


@pytest.mark.parametrize(
    "attack",
    [
        "future_window",
        "unknown_source",
        "future_source",
        "unknown_membership",
        "unknown_output",
        "physical_mapping",
        "counts",
    ],
)
def test_field_study_requires_known_available_physical_sources(compact, attack):
    kind, value = versioned(compact, 3)
    bundle = value["bundles"][0]
    source = bundle["source_sets"][0]
    if attack == "future_window":
        bundle["source_window"] = tuple(
            day + timedelta(days=100) for day in bundle["source_window"]
        )
    elif attack == "unknown_source":
        source["maximum_temporal"]["evidence_level"] = "UNKNOWN"
    elif attack == "future_source":
        source["maximum_temporal"]["available_at"] = bundle["schedule"]["signal_time"] + timedelta(
            days=1
        )
    elif attack == "unknown_membership":
        bundle["membership_set"]["maximum_temporal"]["evidence_level"] = "UNKNOWN"
    elif attack == "unknown_output":
        bundle["output_temporal"]["evidence_level"] = "UNKNOWN"
    elif attack == "physical_mapping":
        source["source_field_name"] = "close"
    else:
        source["missing_row_count"] += 1
    with pytest.raises(ValidationError):
        kind.model_validate(value)
