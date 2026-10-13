#!/usr/bin/env python3
"""Management-only entry for bounded generation capture and offline full-chain research."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import TypeVar

from quantos.application.discovery_baselines import generate_baseline
from quantos.application.discovery_generation import GenerationStore
from quantos.artifacts.store import atomic_write_bytes, confined_regular_file
from quantos.contracts.agent import AgentRunManifestV3, AgentRunSpecV3
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.discovery import (
    DiscoveryBatch,
    DiscoveryDesignContract,
    DiscoveryDesignReader,
    GenerationRequest,
    SequentialDiscoveryBatch,
    SequentialPolicyContract,
    SequentialPolicyReader,
)
from quantos.contracts.discovery_evaluation import (
    DiscoveryEvaluationDeclaration,
    ScientificEvaluationDeclaration,
    parse_discovery_evaluation_declaration,
)
from quantos.contracts.discovery_hosted import (
    HostedGenerationOrigin,
    HostedSequentialGenerationOrigin,
)
from quantos.contracts.harness import HarnessExecutionRequest

_C = TypeVar("_C", bound=CanonicalContract)


def _input_bytes(path: Path) -> bytes:
    path = confined_regular_file(path.absolute().parent, path.name)
    if path.stat().st_size > 16_777_216:
        raise ValueError("management input exceeds byte bound")
    return path.read_bytes()


def _read(path: Path, kind: type[_C]) -> _C:
    data = _input_bytes(path)
    contract = kind.model_validate_json(data)
    if contract.canonical_bytes() != data:
        raise ValueError("management input must use canonical bytes")
    return contract


def _read_design(path: Path) -> DiscoveryDesignContract:
    data = _input_bytes(path)
    contract = DiscoveryDesignReader.model_validate_json(data)
    if contract.canonical_bytes() != data:
        raise ValueError("management design must use canonical bytes")
    return contract


def _read_policy(path: Path) -> SequentialPolicyContract:
    data = _input_bytes(path)
    contract = SequentialPolicyReader.model_validate_json(data)
    if contract.canonical_bytes() != data:
        raise ValueError("management policy must use canonical bytes")
    return contract


def _read_evaluation(
    path: Path,
) -> DiscoveryEvaluationDeclaration | ScientificEvaluationDeclaration:
    path = confined_regular_file(path.absolute().parent, path.name)
    if path.stat().st_size > 2_097_152:
        raise ValueError("evaluation declaration exceeds its byte bound")
    return parse_discovery_evaluation_declaration(path.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generation-root", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="persist the pre-generation design and requests")
    prepare.add_argument("--design", type=Path, required=True)
    prepare.add_argument("--sequential-policy", type=Path)
    for method in ("llm", "random", "template"):
        prepare.add_argument(f"--{method}-request", type=Path, required=True)
    baselines = commands.add_parser("baselines", help="generate both fixed cheap baselines")
    baselines.add_argument("--request", type=Path, required=True)
    reserve = commands.add_parser("reserve", help="charge an attempt before external handoff")
    reserve.add_argument("--request", type=Path, required=True)
    reserve.add_argument("--revision-of")
    capture = commands.add_parser("capture", help="retain one captured response and provenance")
    capture.add_argument("--request", type=Path, required=True)
    capture.add_argument("--ordinal", type=int, required=True)
    capture.add_argument("--text", type=Path, required=True)
    capture.add_argument("--agent-run", type=Path)
    capture.add_argument("--agent-run-spec", type=Path)
    capture.add_argument("--normalized-transcript", type=Path)
    capture.add_argument("--execution-request", type=Path)
    capture.add_argument("--model-configuration", type=Path)
    capture.add_argument("--offline-import", action="store_true")
    capture.add_argument("--hosted-origin", type=Path)
    history = commands.add_parser(
        "history", help="read and reconstruct the immutable history for one retained attempt"
    )
    history.add_argument("--request", type=Path, required=True)
    history.add_argument("--ordinal", type=int, required=True)
    recover = commands.add_parser(
        "recover-hosted",
        help="recover one completed launcher capture from retained originals; no new model call",
    )
    recover.add_argument("--request", type=Path, required=True)
    recover.add_argument("--ordinal", type=int, required=True)
    commands.add_parser(
        "workload-quote",
        help="quote frozen singleton shapes; no science launch or dataset reads",
    )
    freeze = commands.add_parser("freeze", help="freeze all three methods before evaluation")
    freeze.add_argument("--design", type=Path, required=True)
    analysis = commands.add_parser(
        "generation-analysis", help="verify frozen generation originals and report static counts"
    )
    analysis.add_argument("--output-root", type=Path, required=True)
    for name in ("quote", "run", "resume", "report"):
        command = commands.add_parser(name)
        command.add_argument("--snapshot", type=Path, required=True)
        command.add_argument("--view", type=Path, required=True)
        command.add_argument("--output-root", type=Path, required=True)
        command.add_argument("--workspace", type=Path, required=True)
        command.add_argument("--evaluation-declaration", type=Path)
        if name in ("run", "resume"):
            command.add_argument("--expected-new-bytes", type=int, required=True)
    args = parser.parse_args()
    store = GenerationStore(args.generation_root)
    try:
        if args.command == "prepare":
            design = _read_design(args.design)
            if args.sequential_policy is not None:
                store.save_sequential_policy(_read_policy(args.sequential_policy))
            for method in ("llm", "random", "template"):
                store.save_request(
                    design, _read(getattr(args, f"{method}_request"), GenerationRequest)
                )
            result: object = {"design_hash": design.content_hash, "status": "PREPARED"}
        elif args.command == "baselines":
            request = _read(args.request, GenerationRequest)
            design = _read_design(store.root / "requests" / request.content_hash / "design.json")
            policy = store.sequential_policy()
            if policy is None:
                proposals = generate_baseline(design, request)
            else:
                from quantos.application.discovery_sequential import sequential_baseline

                proposals = sequential_baseline(design, request, policy)
            retained, _ = store.inventory(request)
            # Reserved interrupted attempts remain in the denominator; never invent their response.
            for text in proposals[len(retained) :]:
                reservation = store.reserve(request)
                store.complete(request, reservation, text, producer="BASELINE")
            result = {
                "request_hash": request.content_hash,
                "attempts": len(store.inventory(request)[0]),
            }
        elif args.command == "reserve":
            reservation = store.reserve(_read(args.request, GenerationRequest), args.revision_of)
            result = reservation.model_dump(mode="json")
        elif args.command == "recover-hosted":
            from quantos.application.discovery_hosted import recover_generation_capture

            request = _read(args.request, GenerationRequest)
            reservations, _ = store.inventory(request)
            reservation = next(item for item in reservations if item.ordinal == args.ordinal)
            response = recover_generation_capture(store.root, request, reservation)
            result = {
                "response_hash": response.content_hash,
                "producer": response.producer,
                "new_model_calls": 0,
            }
        elif args.command == "history":
            request = _read(args.request, GenerationRequest)
            reservations, _ = store.inventory(request)
            reservation = next(item for item in reservations if item.ordinal == args.ordinal)
            result = store.read_attempt(request, reservation).model_dump(mode="json")
        elif args.command == "capture":
            request = _read(args.request, GenerationRequest)
            reservations, _ = store.inventory(request)
            reservation = next(item for item in reservations if item.ordinal == args.ordinal)
            if args.offline_import and args.hosted_origin:
                raise ValueError("offline import cannot claim Hosted provenance")

            def read_capture_bytes(path: Path | None) -> bytes | None:
                if path is None:
                    return None
                file = confined_regular_file(path.absolute().parent, path.name)
                if file.stat().st_size > 2_097_152:
                    raise OverflowError("capture original exceeds byte bound")
                return file.read_bytes()

            try:
                text_path = confined_regular_file(args.text.absolute().parent, args.text.name)
                if text_path.stat().st_size > 65_536:
                    raise OverflowError("response exceeds byte bound")
                raw_text = text_path.read_text(encoding="utf-8")
                manifest = _read(args.agent_run, AgentRunManifestV3) if args.agent_run else None
                spec = _read(args.agent_run_spec, AgentRunSpecV3) if args.agent_run_spec else None
                execution_request = (
                    _read(args.execution_request, HarnessExecutionRequest)
                    if args.execution_request
                    else None
                )
                transcript = read_capture_bytes(args.normalized_transcript)
                configuration = read_capture_bytes(args.model_configuration)
                hosted_origin = None
                if args.hosted_origin is not None:
                    data = read_capture_bytes(args.hosted_origin)
                    if data is None:
                        raise ValueError("Hosted original is absent")
                    value = json.loads(data)
                    kind = (
                        HostedSequentialGenerationOrigin
                        if value.get("schema_version") == "hosted-sequential-generation-origin/v2"
                        else HostedGenerationOrigin
                    )
                    hosted_origin = _read(args.hosted_origin, kind)
            except OverflowError:
                response = store.reject_capture(request, reservation, "CAPTURE_OUTPUT_LIMIT")
            except (OSError, ValueError):
                response = store.reject_capture(request, reservation, "CAPTURE_PROVENANCE_REJECTED")
            else:
                response = store.complete(
                    request,
                    reservation,
                    raw_text,
                    producer=(
                        "HOSTED_HANDOFF"
                        if hosted_origin is not None
                        else "OFFLINE_IMPORT"
                        if args.offline_import
                        else "SDK_CAPTURE"
                    ),
                    hosted_origin=hosted_origin,
                    agent_run_hash=manifest.content_hash if manifest else None,
                    agent_run=manifest,
                    agent_run_spec=spec,
                    normalized_transcript=transcript,
                    execution_request=execution_request,
                    model_configuration=configuration,
                )
            result = {"response_hash": response.content_hash, "producer": response.producer}
        elif args.command == "workload-quote":
            from quantos.application.discovery_execution import quote_discovery_tasks

            frozen = (
                _read(store.root / "frozen.json", SequentialDiscoveryBatch)
                if store.sequential_policy() is not None
                else _read(store.root / "frozen.json", DiscoveryBatch)
            )
            store.verify_frozen(frozen)
            batch = frozen.batch if isinstance(frozen, SequentialDiscoveryBatch) else frozen
            tasks = quote_discovery_tasks(batch)
            result = {
                "batch_hash": batch.content_hash,
                "generation_authority_hash": frozen.content_hash,
                "full_batch_compute_units": sum(tasks.values()),
                "tasks": tasks,
                "scientific_execution_authorized_by_quote": False,
                "historical_balance_transferred": False,
            }
        elif args.command == "freeze":
            batch = store.freeze(_read_design(args.design))
            store.verify_frozen(batch)
            result = {
                "batch_hash": batch.content_hash,
                "subtasks": len(
                    batch.batch.subtasks
                    if isinstance(batch, SequentialDiscoveryBatch)
                    else batch.subtasks
                ),
            }
        elif args.command == "generation-analysis":
            from quantos.application.discovery_generation_report import build_generation_analysis
            from quantos.application.discovery_report import render_generation_analysis

            destination = args.output_root.absolute().resolve()
            if destination.is_relative_to(store.root.resolve()) or any(
                destination.is_relative_to(root) for root in (Path("/tmp"), Path("/var/tmp"))
            ):
                raise ValueError("generation analysis output must be durable and outside authority")
            frozen = _read(store.root / "frozen.json", SequentialDiscoveryBatch)
            report = build_generation_analysis(frozen, store)
            encoded = canonical_json_bytes(report)
            report_root = destination / "generation-analysis" / f"sha256-{sha256_bytes(encoded)}"
            atomic_write_bytes(report_root / "report.json", encoded)
            atomic_write_bytes(
                report_root / "report.md", render_generation_analysis(report).encode("utf-8")
            )
            result = {"report_hash": sha256_bytes(encoded), "path": str(report_root)}
        else:
            from quantos.application.discovery_comparison import build_discovery_comparison
            from quantos.application.discovery_execution import DiscoveryExecutionService
            from quantos.application.discovery_report import render_discovery_report
            from quantos.research.qlib.result import research_result_verification_scope

            frozen = (
                _read(store.root / "frozen.json", SequentialDiscoveryBatch)
                if store.sequential_policy() is not None
                else _read(store.root / "frozen.json", DiscoveryBatch)
            )
            store.verify_frozen(frozen)
            sequential_batch = frozen if isinstance(frozen, SequentialDiscoveryBatch) else None
            batch = frozen.batch if isinstance(frozen, SequentialDiscoveryBatch) else frozen
            service = DiscoveryExecutionService(
                batch=batch,
                sequential_batch=sequential_batch,
                snapshot_path=args.snapshot,
                qlib_view_path=args.view,
                output_root=args.output_root,
                workspace=args.workspace,
                generation_root=store.root,
                evaluation_declaration=(
                    _read_evaluation(args.evaluation_declaration)
                    if args.evaluation_declaration is not None
                    else None
                ),
            )
            with research_result_verification_scope():
                if args.command in ("run", "resume"):
                    service.run(
                        expected_new_bytes=args.expected_new_bytes,
                        resume_failed_attempts=args.command == "resume",
                    )
                if args.command in ("run", "resume", "report"):
                    report = build_discovery_comparison(batch, service)
                    if sequential_batch is not None:
                        from quantos.application.discovery_generation_report import (
                            attach_verified_comparison_counts,
                            generation_counts_from_verified_batch,
                        )

                        report = {
                            **report,
                            "schema_version": "discovery-comparison/v2",
                            "sequential_batch_hash": sequential_batch.content_hash,
                            "generation_counts": attach_verified_comparison_counts(
                                generation_counts_from_verified_batch(sequential_batch),
                                sequential_batch,
                                report,
                            ),
                        }
                    encoded = canonical_json_bytes(report)
                    report_root = (
                        service.output_root / "comparison" / f"sha256-{sha256_bytes(encoded)}"
                    )
                    atomic_write_bytes(report_root / "report.json", encoded)
                    atomic_write_bytes(
                        report_root / "report.md", render_discovery_report(report).encode("utf-8")
                    )
                    result = {"report_hash": sha256_bytes(encoded), "path": str(report_root)}
                else:
                    result = {"batch_hash": batch.content_hash, "compute_units": service.quote()}
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        # Raw exceptions can contain source/proposal text or credential-bearing paths.
        print(json.dumps({"status": "FAILED", "error_type": type(error).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
