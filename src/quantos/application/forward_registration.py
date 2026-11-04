"""Check operator-bound successor identities; no tool argument can grant admission."""

from datetime import date, datetime
from pathlib import Path
from typing import Any

from quantos.artifacts.store import confined_regular_file, verify_file
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.forward import ForwardDatasetAdmission, PersonalForwardScopeV2
from quantos.research.personal_signal import dataset_binding_hash


def verify_arrival_assessment(
    arrival: Any, evidence: dict[str, Any], root: Path, binding: Any
) -> None:
    from quantos.data.forward_action_coverage import assess_actions

    if evidence.get("schema_version") != "forward-arrival-evidence/v2":
        raise ValueError("source-scoped arrival requires its versioned evidence")
    assessment = assess_actions(root, evidence["inputs"])
    if (
        sha256_bytes(canonical_json_bytes(assessment)) != arrival.assessment_hash
        or evidence["assessment"] != assessment
        or evidence["snapshot_hash"] != binding.manifest.snapshot_hash
        or evidence["inputs"]["membership"]["sha256"]
        != binding.manifest.source_files["canonical/index_membership.parquet"]
        or assessment["snapshot_end_date"] != str(binding.manifest.end_date)
        or arrival.assessment_end_date != binding.manifest.end_date
        or assessment["fresh_account_start"] != str(arrival.fresh_account_start)
        or assessment["status"] != arrival.corporate_actions
        or datetime.fromisoformat(assessment["source_max_received_at"]) > arrival.source_visible_at
    ):
        raise PermissionError("arrival action assessment disagrees with retained sources")


def verify_dataset_admissions(
    scope: Any,
    admissions: tuple[ForwardDatasetAdmission, ...],
    catalog: dict[str, Any],
    arrivals: dict[str, Any],
) -> None:
    if not admissions:
        return
    if not isinstance(scope, PersonalForwardScopeV2):
        raise PermissionError("successor datasets require v2 scope")
    bindings = {dataset_binding_hash(binding): binding for binding in catalog.values()}
    previous = bindings[scope.allowed_dataset_hashes[0]]
    for index, admission in enumerate(admissions):
        binding = bindings[admission.dataset_hash]
        arrival = arrivals[binding.manifest.dataset_id]
        calendar_file = confined_regular_file(binding.provider_root, "calendars/day.txt")
        verify_file(calendar_file, binding.manifest.qlib_files["calendars/day.txt"])
        sessions = [date.fromisoformat(line) for line in calendar_file.read_text().splitlines()]
        prior_day = previous.manifest.end_date
        step = scope.initial_bridge_sessions if index == 0 else 1
        if (
            admission.previous_dataset_hash != dataset_binding_hash(previous)
            or admission.previous_snapshot_hash != previous.manifest.snapshot_hash
            or admission.snapshot_hash != binding.manifest.snapshot_hash
            or admission.end_date != binding.manifest.end_date
            or admission.arrival_hash != arrival.content_hash
            or arrival.previous_snapshot_hash != admission.previous_snapshot_hash
            or prior_day not in sessions
            or sessions.index(prior_day) + step >= len(sessions)
            or sessions[sessions.index(prior_day) + step] != admission.end_date
            or (index == 0 and admission.end_date != scope.start_date)
            or previous.manifest.kind != binding.manifest.kind
            or previous.manifest.source_vintage != binding.manifest.source_vintage
            or previous.manifest.warmup_start != binding.manifest.warmup_start
            or previous.field_mapping_profile != binding.field_mapping_profile
        ):
            raise PermissionError("registered snapshot successor or actual-session chain differs")
        previous = binding
