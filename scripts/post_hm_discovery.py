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
from quantos.contracts.discovery import DiscoveryBatch, DiscoveryDesign, GenerationRequest
from quantos.contracts.discovery_evaluation import DiscoveryEvaluationDeclaration
from quantos.contracts.harness import HarnessExecutionRequest

_C = TypeVar("_C", bound=CanonicalContract)


def _read(path: Path, kind: type[_C]) -> _C:
    path = confined_regular_file(path.absolute().parent, path.name)
    if path.stat().st_size > 16_777_216:
        raise ValueError("management input exceeds byte bound")
    data = path.read_bytes()
    contract = kind.model_validate_json(data)
    if contract.canonical_bytes() != data:
        raise ValueError("management input must use canonical bytes")
    return contract


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generation-root", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="persist the pre-generation design and requests")
    prepare.add_argument("--design", type=Path, required=True)
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
    freeze = commands.add_parser("freeze", help="freeze all three methods before evaluation")
    freeze.add_argument("--design", type=Path, required=True)
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
            design = _read(args.design, DiscoveryDesign)
            for method in ("llm", "random", "template"):
                store.save_request(
                    design, _read(getattr(args, f"{method}_request"), GenerationRequest)
                )
            result: object = {"design_hash": design.content_hash, "status": "PREPARED"}
        elif args.command == "baselines":
            request = _read(args.request, GenerationRequest)
            design = _read(
                store.root / "requests" / request.content_hash / "design.json", DiscoveryDesign
            )
            proposals = generate_baseline(design, request)
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
        elif args.command == "capture":
            request = _read(args.request, GenerationRequest)
            reservations, _ = store.inventory(request)
            reservation = next(item for item in reservations if item.ordinal == args.ordinal)

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
            except OverflowError:
                response = store.reject_capture(request, reservation, "CAPTURE_OUTPUT_LIMIT")
            except (OSError, ValueError):
                response = store.reject_capture(request, reservation, "CAPTURE_PROVENANCE_REJECTED")
            else:
                response = store.complete(
                    request,
                    reservation,
                    raw_text,
                    producer="OFFLINE_IMPORT" if args.offline_import else "SDK_CAPTURE",
                    agent_run_hash=manifest.content_hash if manifest else None,
                    agent_run=manifest,
                    agent_run_spec=spec,
                    normalized_transcript=transcript,
                    execution_request=execution_request,
                    model_configuration=configuration,
                )
            result = {"response_hash": response.content_hash, "producer": response.producer}
        elif args.command == "freeze":
            batch = store.freeze(_read(args.design, DiscoveryDesign))
            store.verify_frozen(batch)
            result = {"batch_hash": batch.content_hash, "subtasks": len(batch.subtasks)}
        else:
            from quantos.application.discovery_comparison import build_discovery_comparison
            from quantos.application.discovery_execution import DiscoveryExecutionService
            from quantos.application.discovery_report import render_discovery_report
            from quantos.research.qlib.result import research_result_verification_scope

            batch = _read(store.root / "frozen.json", DiscoveryBatch)
            store.verify_frozen(batch)
            service = DiscoveryExecutionService(
                batch=batch,
                snapshot_path=args.snapshot,
                qlib_view_path=args.view,
                output_root=args.output_root,
                workspace=args.workspace,
                generation_root=store.root,
                evaluation_declaration=(
                    _read(args.evaluation_declaration, DiscoveryEvaluationDeclaration)
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
