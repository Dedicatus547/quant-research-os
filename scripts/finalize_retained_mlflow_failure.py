#!/usr/bin/env python3
"""Offline failure receipt publication and accounting; never SDK or science execution."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "workspace",
        "live-root",
        "metadata-root",
        "controller-directory",
        "management-module",
        "output-root",
        "authorization",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    for name in (
        "expected-operator-hash",
        "expected-management-source-hash",
        "expected-spec-hash",
        "expected-config-hash",
        "expected-authorization-hash",
        "expected-exit-hash",
        "expected-loaded-hash",
        "expected-controller-request-hash",
        "started-intent-hash",
        "reservation-hash",
        "baseline-hash",
        "deadline-utc",
    ):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args()

    def pinned(path: Path, digest: str) -> bytes:
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("offline finalization pinned input differs")
        return data

    pinned(Path(__file__), args.expected_operator_hash)
    pinned(args.management_module, args.expected_management_source_hash)
    pinned(args.authorization, args.expected_authorization_hash)
    deadline = datetime.fromisoformat(args.deadline_utc)
    if deadline.tzinfo is None or datetime.now(UTC) >= deadline:
        raise ValueError("offline finalization authorized deadline elapsed")
    sys.path.insert(0, str(args.workspace / "src"))
    from quantos.application.autonomous_execution import QuantosResearchExecutionAdapter
    from quantos.application.hosted_inputs import load_hosted_campaign_application
    from quantos.application.hosted_protocol import HostedProtocolService
    from quantos.artifacts.store import atomic_write_bytes, exclusive_directory_lock
    from quantos.contracts.base import canonical_json_bytes
    from quantos.contracts.hosted import parse_hosted_contract
    from quantos.contracts.hosted_inputs import HostedBusinessLoaderConfiguration
    from quantos.contracts.sdk_producer import SdkCampaignSpec
    from quantos.infrastructure.hosted_store import HostedProtocolStore

    module_spec = importlib.util.spec_from_file_location(
        "quantos_offline_failure_finalization_v1", args.management_module
    )
    if module_spec is None or module_spec.loader is None:
        raise ValueError("offline management module cannot load")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    module.require_durable_execution_root(args.output_root)
    module.require_durable_execution_root(args.live_root)
    if (
        not Path(sys.modules[QuantosResearchExecutionAdapter.__module__].__file__)
        .resolve()
        .is_relative_to(args.workspace / "src")
    ):
        raise ValueError("offline finalizer imports different scientific source")

    def write(name: str, value: object) -> None:
        atomic_write_bytes(args.output_root / name, canonical_json_bytes(value))

    def prohibit_execution(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("offline failure finalization forbids scientific execution")

    with (
        exclusive_directory_lock(args.output_root),
        patch.object(QuantosResearchExecutionAdapter, "execute", prohibit_execution),
    ):
        write(
            "start.json",
            {
                "schema_version": "offline-failure-finalization-operation/v1",
                "started_utc": datetime.now(UTC).isoformat(),
                "operator_hash": args.expected_operator_hash,
                "management_source_hash": args.expected_management_source_hash,
                "authorization_hash": args.expected_authorization_hash,
                "scientific_workspace": str(args.workspace),
                "original_controller": str(args.controller_directory),
                "started_intent_hash": args.started_intent_hash,
                "reservation_hash": args.reservation_hash,
                "baseline_hash": args.baseline_hash,
                "deadline_utc": args.deadline_utc,
                "scientific_execution_forbidden": True,
                "sdk_calls": 0,
            },
        )
        try:
            config = parse_hosted_contract(
                pinned(args.metadata_root / "loader-config.json", args.expected_config_hash),
                HostedBusinessLoaderConfiguration,
                max_bytes=65536,
            )
            spec = parse_hosted_contract(
                pinned(args.metadata_root / "sdk-campaign-spec.json", args.expected_spec_hash),
                SdkCampaignSpec,
                max_bytes=1048576,
            )
            if config.provenance_workspace != str(args.workspace):
                raise ValueError("offline failure finalization provenance workspace differs")
            holder = []
            protocol = HostedProtocolService(
                HostedProtocolStore(args.live_root / "protocol"),
                verify_inputs=lambda candidate: holder[0].verify_registered_inputs(candidate),
            )
            service = load_hosted_campaign_application(
                config,
                protocol,
                args.live_root / "business-locks",
                deployment_profile_hash=spec.deployment_profile_hash,
                sdk_spec=spec,
            )
            holder.append(service)
            state = protocol.store.snapshot(spec.campaign_hash, recover=False)
            facts = service.verify_research_facts(state)
            if (
                not facts.steps
                or facts.steps[-1].content_hash != args.started_intent_hash
                or facts.budgets[-1].content_hash != args.reservation_hash
            ):
                raise ValueError("offline closure target is not the current STARTED reservation")
            adapter = service._registered(spec.campaign_hash).orchestrator.execution_port
            if not isinstance(adapter, QuantosResearchExecutionAdapter):
                raise ValueError("offline closure requires existing native execution adapter")
            objects = args.live_root / "protocol" / "campaigns" / spec.campaign_hash / "objects"
            if datetime.now(UTC) >= deadline:
                raise TimeoutError("offline failure finalization deadline elapsed")
            result = module.finalize_retained_mlflow_failure(
                adapter,
                started_intent_path=objects / f"{args.started_intent_hash}.json",
                started_intent_hash=args.started_intent_hash,
                reservation_path=objects / f"{args.reservation_hash}.json",
                reservation_hash=args.reservation_hash,
                baseline_path=objects / f"{args.baseline_hash}.json",
                baseline_hash=args.baseline_hash,
                controller_directory=args.controller_directory,
                expected_exit_hash=args.expected_exit_hash,
                expected_loaded_hash=args.expected_loaded_hash,
                expected_controller_request_hash=args.expected_controller_request_hash,
                expected_management_source_hash=args.expected_management_source_hash,
            )
            write("execution-result.json", result.model_dump(mode="json"))
            # A genuine terminal receipt exists before the unchanged STARTED branch
            # performs accounting continuation. execute remains hard forbidden.
            status = service.resume(spec.campaign_hash)
            after = service.verify_research_facts(protocol.store.snapshot(spec.campaign_hash))
            completed = tuple(
                item
                for item in after.steps
                if item.request_hash == facts.steps[-1].request_hash and item.phase == "COMPLETED"
            )
            if len(completed) != 1 or after.budgets[-1].phase != "SETTLED":
                raise ValueError("terminal failed receipt did not settle original reservation")
            write("completed-intent.json", completed[0].model_dump(mode="json"))
            write("settled-budget.json", after.budgets[-1].model_dump(mode="json"))
            write("settled-status.json", status.model_dump(mode="json"))
            write(
                "exit.json",
                {
                    "exit_code": 0,
                    "finished_utc": datetime.now(UTC).isoformat(),
                    "sdk_calls": 0,
                    "scientific_reexecutions": 0,
                    "outcome": "FAILED_NOT_EVALUATED",
                },
            )
            return 0
        except Exception as error:
            write(
                "exit.json",
                {
                    "exit_code": 1,
                    "finished_utc": datetime.now(UTC).isoformat(),
                    "error_class": type(error).__name__,
                    "failure_frames": [
                        {
                            "filename": Path(frame.filename).name,
                            "function": frame.name,
                            "line": frame.lineno,
                        }
                        for frame in traceback.extract_tb(error.__traceback__)[-32:]
                    ],
                    "sdk_calls": 0,
                    "scientific_reexecutions": 0,
                },
            )
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
