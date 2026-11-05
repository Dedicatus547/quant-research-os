"""Legacy per-instrument PIT reports remain bound across bundle serialization."""

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError
from tests.integration.test_signal_artifact import _build_view, _evidence_and_resolved

from quantos.contracts.pit import CanonicalPITAuditRequest
from quantos.contracts.research_execution import (
    PITAuditEvidenceBundle,
    PITAuditEvidenceCollection,
    PITAuditEvidenceItem,
)


@pytest.fixture(scope="module")
def evidence(tmp_path_factory):
    with pytest.MonkeyPatch.context() as patch:
        snapshot, view = _build_view(tmp_path_factory.mktemp("legacy-pit"), patch)
        return _evidence_and_resolved(snapshot, view)[0]


@pytest.mark.parametrize(
    "attack", ["request", "snapshot", "expression", "schedule", "instrument", "universe"]
)
def test_a_valid_report_from_another_request_cannot_be_adopted(evidence, attack):
    value = evidence.bundles[0].items[0].model_dump()
    report = value["report"]
    if attack in {"request", "snapshot", "expression"}:
        report[
            {
                "request": "canonical_request_hash",
                "snapshot": "snapshot_hash",
                "expression": "expression_spec_hash",
            }[attack]
        ] = "f" * 64
    elif attack == "instrument":
        report["instrument_id"] = "600999.SH"
    elif attack == "universe":
        report["universe_index"] = "000905.SH"
    else:
        report["schedule"]["execution_time"] += timedelta(days=1)
    with pytest.raises(ValidationError):
        PITAuditEvidenceItem.model_validate(value)


@pytest.mark.parametrize("level", ["bundle", "collection"])
@pytest.mark.parametrize(
    "attack", ["empty", "duplicate", "snapshot", "expression", "universe", "order"]
)
def test_pit_bundle_and_collection_preserve_exact_sorted_denominators(evidence, level, attack):
    original = evidence.bundles[0] if level == "bundle" else evidence
    value = original.model_dump()
    items = "items" if level == "bundle" else "bundles"
    if attack == "empty":
        value[items] = ()
    elif attack == "duplicate":
        value[items] *= 2
    elif attack == "order":
        if level == "bundle":
            second = original.items[0].model_dump()
            second["request"]["instrument_id"] = "600999.SH"
            second["report"]["instrument_id"] = "600999.SH"
            second["report"]["canonical_request_hash"] = CanonicalPITAuditRequest.model_validate(
                second["request"]
            ).content_hash
            assert PITAuditEvidenceItem.model_validate(second)
        else:
            second = original.bundles[0].model_dump()
            for key, instant in second["schedule"].items():
                if isinstance(instant, datetime):
                    second["schedule"][key] = instant + timedelta(days=1)
            for item in second["items"]:
                item["request"]["schedule"] = second["schedule"]
                item["report"]["schedule"] = second["schedule"]
                item["report"]["canonical_request_hash"] = CanonicalPITAuditRequest.model_validate(
                    item["request"]
                ).content_hash
            assert PITAuditEvidenceBundle.model_validate(second)
        value[items] = (second, *value[items])
    elif attack == "snapshot":
        value["snapshot_hash"] = "f" * 64
    elif attack == "expression":
        value["expression_spec_hash"] = "f" * 64
    else:
        value["universe_index"] = "000905.SH"
    kind = PITAuditEvidenceBundle if level == "bundle" else PITAuditEvidenceCollection
    with pytest.raises(ValidationError):
        kind.model_validate(value)
