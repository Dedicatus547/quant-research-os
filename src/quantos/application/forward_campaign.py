"""Operator scheduler for one frozen finite campaign; no accounting or signal engine."""

from __future__ import annotations

import argparse
import json
import signal
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from quantos.application.personal_observation import SnapshotArrivalV2
from quantos.application.personal_product import personal_product
from quantos.application.personal_research import PersonalDatasetBinding
from quantos.application.personal_server_config import make_trusted_service
from quantos.artifacts.store import (
    atomic_write_bytes,
    exclusive_directory_lock,
    sha256_file,
    verify_file,
)
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.forward import ForwardDatasetAdmission
from quantos.contracts.hs300_lifecycle import HS300LifecycleDatasetManifest
from quantos.infrastructure.forward_acquisition_job import acquire_job
from quantos.research.personal_signal import dataset_binding_hash

SHANGHAI = ZoneInfo("Asia/Shanghai")


def write_new(path: Path, value: Any) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError("immutable campaign record already exists")
    atomic_write_bytes(path, canonical_json_bytes(value))


def reference(path: Path) -> dict[str, str]:
    return {"path": str(path.absolute()), "sha256": sha256_file(path)}


def read_ref(ref: dict[str, str]) -> dict[str, Any]:
    path = Path(ref["path"])
    verify_file(path, ref["sha256"])
    return json.loads(path.read_bytes())


def binding(registration: dict[str, Any]) -> PersonalDatasetBinding:
    manifest = HS300LifecycleDatasetManifest.model_validate(
        read_ref({"path": registration["manifest_path"], "sha256": registration["manifest_sha256"]})
    )
    return PersonalDatasetBinding(
        manifest=manifest,
        provider_root=Path(registration["provider_root"]),
        panel_path=Path(registration["panel_path"]),
        pit_evidence_path=Path(registration["pit_evidence_path"]),
        snapshot_path=Path(registration["snapshot_path"]),
        lifecycle_path=Path(registration["lifecycle_path"]),
        field_mapping_profile="canonical-personal-fields/v1",
    )


def arrival_registration(
    root: Path, result: dict[str, Any], previous_hash: str | None
) -> dict[str, Any]:
    data = binding(result["catalog"])
    day = result["day"]
    assessment = result["assessment"]
    identity = day + "-" + sha256_bytes(canonical_json_bytes(assessment))[:16]
    evidence = {
        "schema_version": "forward-arrival-evidence/v2",
        "snapshot_hash": data.manifest.snapshot_hash,
        "inputs": result["action_inputs"],
        "assessment": assessment,
    }
    evidence_path = root / ("arrival-evidence-" + identity + ".json")
    write_new(evidence_path, evidence)
    snapshot = json.loads((Path(result["catalog"]["snapshot_path"]) / "manifest.json").read_bytes())
    arrival = SnapshotArrivalV2(
        acquired_at=datetime.fromisoformat(snapshot["created_at"]),
        source_visible_at=max(
            datetime.fromisoformat(assessment["source_max_received_at"]),
            datetime.fromisoformat(snapshot["created_at"]),
        ),
        received_at=datetime.now(UTC),
        evidence_sha256=sha256_file(evidence_path),
        previous_snapshot_hash=previous_hash,
        corporate_actions=assessment["status"],
        assessment_hash=sha256_bytes(canonical_json_bytes(assessment)),
        assessment_end_date=date.fromisoformat(day),
        fresh_account_start=date.fromisoformat(assessment["fresh_account_start"]),
    )
    path = root / ("arrival-" + identity + ".json")
    write_new(path, arrival.canonical_payload())
    return {
        "schema_version": "personal-arrival-registration/v1",
        "dataset_id": data.manifest.dataset_id,
        "metadata_path": str(path),
        "metadata_sha256": sha256_file(path),
        "evidence_path": str(evidence_path),
    }


def registry(plan: dict[str, Any], day: str) -> dict[str, Any]:
    root = Path(plan["root"])
    prior = read_ref(plan["initial_registry"])
    prior_ref = plan["initial_registry"]
    if day == prior["day"]:
        return prior
    for session in plan["acquisition_dates"]:
        path = root / "registry" / (session + ".json")
        current = json.loads(path.read_bytes())
        if current["previous_registry"] != prior_ref or current["day"] != session:
            raise PermissionError("campaign registry chain differs")
        for ref in current["configs"].values():
            read_ref(ref)
        read_ref(current["acquisition_result"])
        prior, prior_ref = current, reference(path)
        if session == day:
            return prior
    raise ValueError("day outside finite campaign registry")


def register_successor(
    plan: dict[str, Any], result: dict[str, Any], prior: dict[str, Any]
) -> dict[str, Any]:
    root, day = Path(plan["root"]), result["day"]
    previous = read_ref(prior["acquisition_result"])
    arrival = arrival_registration(root, result, previous["snapshot_hash"])
    entry = ForwardDatasetAdmission(
        dataset_hash=dataset_binding_hash(binding(result["catalog"])),
        previous_dataset_hash=dataset_binding_hash(binding(previous["catalog"])),
        snapshot_hash=result["snapshot_hash"],
        previous_snapshot_hash=previous["snapshot_hash"],
        arrival_hash=sha256_file(Path(arrival["metadata_path"])),
        end_date=date.fromisoformat(day),
    )
    configs: dict[str, dict[str, str]] = {}
    for arm in plan["arms"]:
        config = read_ref(prior["configs"][arm["name"]])
        config["catalog"].append(result["catalog"])
        config["snapshot_arrivals"].append(arrival)
        config["forward_dataset_admissions"].append(entry.canonical_payload())
        path = root / "registrations" / (day + "-" + arm["name"] + ".json")
        write_new(path, config)
        make_trusted_service(Path(arm["product_root"]), Path(plan["repo_root"]), path)
        configs[arm["name"]] = reference(path)
    value = {
        "day": day,
        "previous_registry": reference(root / "registry" / (prior["day"] + ".json")),
        "acquisition_result": reference(root / "days" / day / "acquisition-result.json"),
        "configs": configs,
    }
    write_new(root / "registry" / (day + ".json"), value)
    return value


def core_for(plan: dict[str, Any], state: dict[str, Any], arm: dict[str, Any]) -> Any:
    config = state["configs"][arm["name"]]
    read_ref(config)
    return personal_product(
        make_trusted_service(
            Path(arm["product_root"]), Path(plan["repo_root"]), Path(config["path"])
        )
    )


def run(plan_path: Path, expected_hash: str, phase: str) -> dict[str, Any]:
    plan = read_ref({"path": str(plan_path), "sha256": expected_hash})
    root = Path(plan["root"])
    for name, digest in plan["source_hashes"].items():
        verify_file(Path(plan["repo_root"]) / name, digest)
    read_ref(plan["approval"])
    now = datetime.now(SHANGHAI)
    if phase == "preflight":
        state = read_ref(plan["initial_registry"])
        reports = {arm["name"]: core_for(plan, state, arm).scope_status() for arm in plan["arms"]}
        return {
            "state": "READY",
            "plan_hash": expected_hash,
            "first_signal_date": plan["signal_dates"][0],
            "final_execution_date": plan["execution_dates"][-1],
            "scopes": reports,
            "future_observations_performed": 0,
        }
    day = str(now.date() - timedelta(days=1)) if phase == "observe" else str(now.date())
    dates = plan["signal_dates"] if phase == "observe" else plan["acquisition_dates"]
    if day not in dates:
        return {"state": "NO_SCHEDULED_SESSION", "day": day}
    if phase == "acquire" and (now.hour, now.minute) < (22, 30):
        return {"state": "NOT_DUE", "day": day}
    with exclusive_directory_lock(root / "scheduler-lock"):
        if (root / "campaign-stop.json").exists():
            raise PermissionError("campaign stopped; retained evidence requires operator review")
        job = root / "scheduled-jobs" / (day + "-" + phase)
        if (job / "result.json").exists():
            return json.loads((job / "result.json").read_bytes())
        if job.exists():
            raise PermissionError("unfinished scheduled job requires reconciliation, no reissue")
        used_wall = plan["initial_wall_charge_seconds"]
        for previous_job in (root / "scheduled-jobs").glob("*"):
            terminal = previous_job / "result.json"
            if not terminal.exists():
                raise PermissionError("prior scheduler exit requires reconciliation")
            used_wall += json.loads(terminal.read_bytes())["wall_seconds"]
        ceiling = 5400 if phase == "acquire" else 3600
        if used_wall + ceiling > 172800:
            raise PermissionError("total campaign wall budget cannot reserve the next job")
        started = time.monotonic()

        def expired(_signum: int, _frame: Any) -> None:
            raise TimeoutError("campaign orchestration wall ceiling")

        previous_alarm = signal.signal(signal.SIGALRM, expired)
        signal.alarm(ceiling)
        job.mkdir(parents=True)
        write_new(
            job / "intent.json",
            {
                "plan_hash": expected_hash,
                "phase": phase,
                "day": day,
                "started_at": datetime.now(UTC),
                "wall_reserved_seconds": ceiling,
                "used_campaign_wall_seconds": used_wall,
            },
        )
        try:
            outputs: dict[str, Any] = {}
            if phase == "acquire":
                index = plan["acquisition_dates"].index(day)
                prior_day = plan["acquisition_dates"][index - 1] if index else plan["initial_date"]
                prior = registry(plan, prior_day)
                acquire_job(plan, plan_path, Path(prior["acquisition_result"]["path"]), day)
                acquired = json.loads(
                    (root / "days" / day / "acquisition-result.json").read_bytes()
                )
                state = register_successor(plan, acquired, prior)
                if acquired["assessment"]["status"] != "SUPPORTED_IN_DECLARED_SOURCE_SCOPE":
                    raise PermissionError("new action evidence is unsupported or unknown")
                if day in plan["execution_dates"]:
                    signal_day = plan["signal_dates"][plan["execution_dates"].index(day)]
                    observed = json.loads(
                        (
                            root / "scheduled-jobs" / (signal_day + "-observe") / "result.json"
                        ).read_bytes()
                    )
                    for arm in plan["arms"]:
                        product = core_for(plan, state, arm)
                        result = product.advance_shadow(
                            shadow_id=arm["shadow_id"],
                            execution_date=day,
                            observation_record_hash=observed["arms"][arm["name"]]["record_hash"],
                            execution_dataset_id=binding(acquired["catalog"]).manifest.dataset_id,
                        )
                        write_new(job / (arm["name"] + ".json"), result)
                        outputs[arm["name"]] = result
                        if result.get("native_receipt", {}).get("run_status") != "SUCCEEDED":
                            raise RuntimeError("native advance did not complete successfully")
            else:
                state = registry(plan, day)
                acquired = read_ref(state["acquisition_result"])
                for arm in plan["arms"]:
                    product = core_for(plan, state, arm)
                    result = product.observe(
                        observation_id=arm["observation_id"],
                        day=day,
                        dataset_id=binding(acquired["catalog"]).manifest.dataset_id,
                        observed_at=datetime.now(UTC).isoformat(),
                    )
                    write_new(job / (arm["name"] + ".json"), result)
                    outputs[arm["name"]] = result
                    if result.get("status") not in {"EMITTED", "ABSTAIN"} or result.get(
                        "after_the_fact"
                    ):
                        raise RuntimeError("signal missing, late, stopped or failed")
            result = {
                "state": "COMPLETED",
                "day": day,
                "phase": phase,
                "arms": outputs,
                "completed_at": datetime.now(UTC),
                "wall_seconds": time.monotonic() - started,
            }
            write_new(job / "result.json", result)
            return result
        except Exception as error:
            failure = {
                "state": "STOPPED",
                "day": day,
                "phase": phase,
                "error_type": type(error).__name__,
                "recorded_at": datetime.now(UTC),
                "wall_seconds": time.monotonic() - started,
                "partial_results": [str(p) for p in sorted(job.glob("*.json"))],
            }
            write_new(job / "failure.json", failure)
            write_new(root / "campaign-stop.json", failure)
            raise
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous_alarm)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--phase", choices=("acquire", "observe", "preflight"), required=True)
    args = parser.parse_args()
    try:
        result = run(args.plan, args.sha256, args.phase)
        print(canonical_json_bytes(result).decode())
    except Exception as error:
        print(
            canonical_json_bytes({"state": "FAILED", "error_type": type(error).__name__}).decode()
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
