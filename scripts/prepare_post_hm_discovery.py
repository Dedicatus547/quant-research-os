#!/usr/bin/env python3
"""Prepare bounded management inputs; no generation, freezing or scientific execution."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Literal, TypeVar, cast

import quantos.application.autonomous_execution as execution
from quantos.application.provenance import verify_code_provenance
from quantos.artifacts.store import atomic_write_bytes, confined_regular_file
from quantos.contracts.autonomous import AutonomousExecutionBindings
from quantos.contracts.base import CanonicalContract, canonical_json_bytes, sha256_bytes
from quantos.contracts.campaign import ResearchCampaignEvent, TrialOutcome
from quantos.contracts.discovery import (
    CompositionGenerationPolicy,
    DiscoveryCompositionDesign,
    DiscoveryDesign,
    GenerationRequest,
    SequentialGenerationPolicy,
)
from quantos.contracts.hosted_deployment import HostedLauncherConfiguration
from quantos.contracts.hosted_inputs import HostedFrozenBusinessInputs
from quantos.contracts.ledger import ResearchLedgerSearchPolicy
from quantos.contracts.pit import SafeExpressionNode, SafeQlibExpressionSpec, SafeQlibOperator
from quantos.contracts.provenance import CodeProvenance
from quantos.contracts.qlib_view import QlibViewManifest
from quantos.contracts.research import ExperimentAuthoringSpec
from quantos.contracts.snapshot import DataSnapshotManifest
from quantos.security import validate_secret_free

_C = TypeVar("_C", bound=CanonicalContract)
_BUNDLE_HASH = "4d577d6521d7413202f41c1d8260b2bace2cebb82e0b33438220b6a004deb829"
_SNAPSHOT_HASH = "6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9"
_VIEW_HASH = "fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b"
_EVENT_HASHES = (
    "a5479a94252bae534c42ef05a0aba2a6b2c6a66c66ff3991cc2420e90ac0570d",
    "5da6bb23cc0e44a4a01db0b3aa5ffa7503e3e208a973b7519f6f075e21afb332",
)
_MAX_INPUT_BYTES = 2_097_152
_MAX_MANIFEST_BYTES = 16_777_216


def _scan_view(value: object) -> object:
    if isinstance(value, dict):
        item = dict(cast(dict[str, object], value))
        if item.get("schema_version") == "code-provenance/v1":
            provenance = CodeProvenance.model_validate(item)
            item.pop("commit_hash")
            item["commit_identity"] = provenance.commit_hash
        elif item.get("schema_version") == "autonomous-execution-bindings/v1":
            bindings = AutonomousExecutionBindings.model_validate(item)
            item.pop("code_commit_hash")
            item["code_commit_identity"] = bindings.code_commit_hash
        elif item.get("schema_version") == "research-ledger-search-policy/v1":
            policy = ResearchLedgerSearchPolicy.model_validate(item)
            item.pop("tokenizer_id")
            item["text_segmentation_identity"] = policy.tokenizer_id
        return {key: _scan_view(child) for key, child in item.items()}
    if isinstance(value, list):
        return [_scan_view(child) for child in cast(list[object], value)]
    return value


def _read_bytes(path: Path, *, max_bytes: int = _MAX_INPUT_BYTES) -> bytes:
    file = confined_regular_file(path.absolute().parent, path.name)
    if file.stat().st_size > max_bytes:
        raise ValueError("management original exceeds byte bound")
    data = file.read_bytes()
    validate_secret_free(_scan_view(json.loads(data)), file_name="discovery-input.json")
    return data


def _read_contract(path: Path, kind: type[_C]) -> tuple[_C, bytes]:
    data = _read_bytes(
        path,
        max_bytes=_MAX_MANIFEST_BYTES
        if kind in (DataSnapshotManifest, QlibViewManifest)
        else _MAX_INPUT_BYTES,
    )
    contract = kind.model_validate_json(data)
    if canonical_json_bytes(contract.model_dump(mode="python")) != data:
        raise ValueError("management original is not canonical")
    return contract, data


def prepare_inputs(
    *,
    workspace: Path,
    code_commit: str,
    lockfile_hash: str,
    source_bundle: Path,
    historical_event_root: Path,
    snapshot_manifest: Path,
    view_manifest: Path,
    launcher_configuration: Path,
    output_root: Path,
    generation_policy: Literal["legacy-v1", "sequential-v2", "composition-v3"] = "legacy-v1",
    max_compute_units: int | None = None,
    opportunities: int | None = None,
) -> Path:
    """Write immutable input originals bound to the code actually running this function."""
    if generation_policy in ("sequential-v2", "composition-v3"):
        if max_compute_units is None or max_compute_units <= 0:
            raise ValueError(
                "successor preparation requires an explicit positive compute design cap"
            )
        declared_compute_units = max_compute_units
    else:
        if max_compute_units not in (None, 360):
            raise ValueError("legacy preparation retains its original compute design cap")
        declared_compute_units = 360
    if generation_policy == "composition-v3":
        if opportunities is not None and opportunities <= 0:
            raise ValueError("composition opportunities must be positive")
        declared_opportunities = opportunities or 3
    else:
        if opportunities is not None:
            raise ValueError("opportunities is only supported by composition-v3")
        declared_opportunities = 5
    workspace = workspace.resolve()
    output_root = output_root.resolve()
    if any(output_root.is_relative_to(path) for path in (Path("/tmp"), Path("/var/tmp"))):
        raise ValueError("management evidence requires durable storage")
    historical_event_root = historical_event_root.absolute()
    if historical_event_root.resolve(strict=True) != historical_event_root or any(
        historical_event_root.is_relative_to(path) for path in (Path("/tmp"), Path("/var/tmp"))
    ):
        raise ValueError("historical event originals require a durable canonical root")
    if (
        Path(__file__).resolve() != workspace / "scripts/prepare_post_hm_discovery.py"
        or Path(execution.__file__).resolve()
        != workspace / "src/quantos/application/autonomous_execution.py"
    ):
        raise ValueError("preparation must run from the bound source workspace")
    provenance = verify_code_provenance(
        workspace, expected_commit_hash=code_commit, expected_lockfile_hash=lockfile_hash
    )
    bundle, bundle_bytes = _read_contract(source_bundle, HostedFrozenBusinessInputs)
    if (
        sha256_bytes(bundle_bytes) != _BUNDLE_HASH
        or code_commit == bundle.code_provenance.commit_hash
    ):
        raise ValueError("source bundle or successor code identity differs")
    snapshot, snapshot_bytes = _read_contract(snapshot_manifest, DataSnapshotManifest)
    view, view_bytes = _read_contract(view_manifest, QlibViewManifest)
    if (
        snapshot.content_hash != _SNAPSHOT_HASH
        or view.content_hash != _VIEW_HASH
        or bundle.campaign.snapshot_hash != _SNAPSHOT_HASH
        or bundle.campaign.qlib_view_hash != _VIEW_HASH
        or view.source_snapshot_hash != _SNAPSHOT_HASH
    ):
        raise ValueError("retained data manifest identities differ")
    configuration, configuration_bytes = _read_contract(
        launcher_configuration, HostedLauncherConfiguration
    )
    if (
        configuration.model != "gpt-6.1-sol"
        or configuration.reasoning_effort != "high"
        or configuration.extraction_rule != "codex-jsonl-single-final/v2"
        or configuration.proposal_byte_cap > 65_536
    ):
        raise ValueError("launcher configuration differs from declared discovery profile")

    authority = (
        source_bundle.absolute().parent.parent / "authority/business" / bundle.campaign.content_hash
    )
    originals: dict[str, bytes] = {
        "source-bundle.json": bundle_bytes,
        "snapshot-manifest.json": snapshot_bytes,
        "view-manifest.json": view_bytes,
        "code-provenance.json": provenance.canonical_bytes(),
        "launcher-configuration.json": configuration_bytes,
        "ledger-snapshot.json": bundle.initial_ledger_snapshot.canonical_bytes(),
    }
    contexts: dict[str, bytes] = {}
    for object_hash in bundle.campaign.evidence_hashes:
        reference = next(item for item in bundle.initial_ledger_files if item.sha256 == object_hash)
        data = _read_bytes(authority / "ledger" / reference.logical_path)
        if sha256_bytes(data) != object_hash or len(data) != reference.size_bytes:
            raise ValueError("retained evidence original differs")
        contexts[object_hash] = data
    events: list[ResearchCampaignEvent] = []
    for sequence, event_hash in enumerate(_EVENT_HASHES, 3):
        event, data = _read_contract(
            historical_event_root / f"{sequence:08d}-sha256-{event_hash}.json",
            ResearchCampaignEvent,
        )
        if (
            event.content_hash != event_hash
            or event.sequence != sequence
            or event.campaign_hash != bundle.campaign.content_hash
            or event.trial is None
            or event.trial.outcome is not TrialOutcome.SOFT_REJECT
            or event.previous_event_hash
            != (events[-1].content_hash if events else bundle.initial_events[-1].content_hash)
        ):
            raise ValueError("historical exposure event binding differs")
        events.append(event)
        originals[f"historical-events/sha256-{event_hash}.json"] = data

    policy = bundle.research_policy
    if (
        (policy.train.start, policy.train.end) != (date(2015, 1, 1), date(2019, 12, 31))
        or (policy.validation.start, policy.validation.end)
        != (date(2020, 1, 1), date(2022, 12, 31))
        or (policy.test.start, policy.test.end) != (date(2023, 1, 1), date(2025, 12, 30))
        or (
            policy.random_seed,
            policy.num_threads,
            policy.num_boost_round,
            policy.early_stopping_rounds,
            policy.purge_trading_days,
            policy.label_horizon_trading_sessions,
        )
        != (1729, 1, 100, 20, 5, 1)
        or policy.model != "LGBModel"
        or (bundle.campaign.sealed_confirmation.start, bundle.campaign.sealed_confirmation.end)
        != (date(2026, 1, 1), date(2026, 1, 30))
    ):
        raise ValueError("retained scientific period or model policy differs")
    exposure = (
        "Historical train 2015-2019, validation 2020-2022 and test 2023-2025 windows were "
        "already consumed by prior research; this comparison is retrospective exploratory.",
        f"Historical source bundle {_BUNDLE_HASH}; two retained SOFT_REJECT validation "
        f"events {_EVENT_HASHES[0]} and {_EVENT_HASHES[1]} were visible in this session.",
        "Sealed 2026-01-01 through 2026-01-30 is a retained declaration; this preparation "
        "does not access its data. No new sealed access is authorized by these inputs.",
    )
    if generation_policy in ("sequential-v2", "composition-v3"):
        exposure += (
            "First Discovery report "
            "b96c14eeee6637bd7ca67b02dbc2ff148aaddec385057e6ca51a76f8028d33be "
            "was consumed by this successor design; the 2023-2025 period remains "
            "retrospective exploratory, not an independent confirmation window.",
        )
    if generation_policy == "composition-v3":
        exposure += (
            "Second Discovery comparison "
            "0d0f925443dc0b129bf6cab9b6c778c615550c7cb23cdd1c84fb83dc471206a0 "
            "and its scientific report were already visible in this session; the old evaluation "
            "period is not newly unexposed. No model/science results from this B2 round are "
            "fed back into generation.",
        )
    methodology: dict[str, object] = {
        "schema_version": (
            "discovery-shared-context/v3"
            if generation_policy == "composition-v3"
            else "discovery-shared-context/v1"
        ),
        "research_policy": policy.model_dump(mode="json"),
        "primary_metric": "Rank IC",
        "direction": "maximize",
        "grammar": (
            "price-return-volatility-trend/v1"
            if generation_policy == "composition-v3"
            else "field-window-optional-ratio-abs/v1"
        ),
        "field": "adjusted_close",
        "window_operators": (
            ["return", "rolling_mean", "rolling_std"]
            if generation_policy == "composition-v3"
            else ["rank", "return", "rolling_mean", "rolling_std"]
        ),
        "windows": [1, 5, 10, 20, 60] if generation_policy == "composition-v3" else [5, 10, 20],
        "max_nodes": 8 if generation_policy == "composition-v3" else 4,
        **({"max_depth": 4} if generation_policy == "composition-v3" else {}),
        "input_lag_trading_days": bundle.authoring.strategy.input_lag_trading_days,
        "rank_semantics": "Qlib Rank(x,N) is a time-window operator, not cross-sectional rank.",
        "composition": (
            "C=Return(adjusted_close,w); N=Mean or Std(Return(adjusted_close,a),b); "
            "emit C, N, C/N or C*N; "
            "w,a,b from {1,5,10,20,60}; at most 8 nodes and depth 4."
            if generation_policy == "composition-v3"
            else "Exactly one field and one window node; optional abs, or "
            "divide(adjusted_close, rolling_mean(adjusted_close, window)), optionally abs."
        ),
        "opportunities_per_method": declared_opportunities,
        **(
            {
                "composition_order": {
                    "short_windows": [5, 10, 20, 1, 60],
                    "outer_windows": [20, 60, 10, 5, 1],
                    "inner_windows": [1, 5, 10, 20, 60],
                    "volatility_operator_order": ["rolling_std", "rolling_mean"],
                    "root_operator_order": ["divide", "multiply"],
                    "template_traversal": "composition-component-round-robin/v1",
                    "random_selection": "structural-uniform-without-replacement/v1",
                    "random_seed": 1729,
                }
            }
            if generation_policy == "composition-v3"
            else {}
        ),
        "maximum_compute_units": declared_compute_units,
        "baseline_seed": 1729,
        "exposure_history": list(exposure),
        "past_events_are_source_records_not_new_validation": True,
    }
    for value in (methodology, SafeQlibExpressionSpec.model_json_schema()):
        data = canonical_json_bytes(value)
        contexts[sha256_bytes(data)] = data
    if sum(map(len, contexts.values())) > 65_536:
        raise ValueError("shared context exceeds the frozen bound")
    placeholder = SafeQlibExpressionSpec(
        schema_version="safe-qlib-expression/v2",
        expression_id="discovery_authoring_placeholder",
        nodes=(
            SafeExpressionNode(
                node_id="close", operator=SafeQlibOperator.FIELD, field_name="adjusted_close"
            ),
        ),
        output_node_id="close",
        input_lag_trading_days=bundle.authoring.strategy.input_lag_trading_days,
    )
    authoring = ExperimentAuthoringSpec.model_validate(
        {
            **bundle.authoring.model_dump(mode="python"),
            "experiment_id": (
                "post_hm_discovery_composition_base_v3"
                if generation_policy == "composition-v3"
                else "post_hm_discovery_singleton_base_v1"
            ),
            "expression": placeholder,
        }
    )
    bindings = execution.build_autonomous_execution_bindings(
        snapshot=snapshot,
        qlib_view=view,
        research_policy=policy,
        validation_policy=bundle.validation_policy,
        authoring=authoring,
        cost_policy=bundle.cost_policy,
        backtest_policy=bundle.backtest_policy,
        code_commit_hash=provenance.commit_hash,
        lockfile_hash=provenance.lockfile_hash,
    )
    design_fields = dict(
        research_question=(
            "Within the finite bounded price-return-volatility-trend grammar, compare LLM, "
            "structurally uniform random and component-round-robin template proposals by "
            "retrospective test Rank IC."
            if generation_policy == "composition-v3"
            else "Within the declared common bounded price-expression grammar, "
            "compare LLM, seeded random and fixed template proposals by retrospective test Rank IC."
        ),
        snapshot_hash=_SNAPSHOT_HASH,
        qlib_view_hash=_VIEW_HASH,
        ledger_snapshot_hash=bundle.initial_ledger_snapshot.content_hash,
        evidence_hashes=tuple(sorted(bundle.campaign.evidence_hashes)),
        context_hashes=tuple(sorted(contexts)),
        exposure_history=exposure,
        authoring=authoring,
        research_policy=policy,
        sealed_confirmation=bundle.campaign.sealed_confirmation,
        validation_policy=bundle.validation_policy,
        cost_policy=bundle.cost_policy,
        backtest_policy=bundle.backtest_policy,
        bindings=bindings,
        allowed_operators=tuple(
            sorted(
                (
                    SafeQlibOperator.FIELD,
                    SafeQlibOperator.RETURN,
                    SafeQlibOperator.ROLLING_MEAN,
                    SafeQlibOperator.ROLLING_STD,
                    SafeQlibOperator.DIVIDE,
                    *(
                        (SafeQlibOperator.MULTIPLY,)
                        if generation_policy == "composition-v3"
                        else ()
                    ),
                    *(
                        (SafeQlibOperator.RANK, SafeQlibOperator.ABS)
                        if generation_policy != "composition-v3"
                        else ()
                    ),
                ),
                key=str,
            )
        ),
        max_compute_units=declared_compute_units,
    )
    if generation_policy == "composition-v3":
        design = DiscoveryCompositionDesign.model_validate(
            {
                **design_fields,
                "candidate_grammar": "price-return-volatility-trend/v1",
                "allowed_windows": (1, 5, 10, 20, 60),
                "max_nodes": 8,
                "max_depth": 4,
                "evaluation_opportunities_per_method": declared_opportunities,
                "baseline_sampling": "structural-uniform-without-replacement/v1",
                "template_order": "composition-component-round-robin/v1",
            }
        )
    else:
        design = DiscoveryDesign.model_validate(design_fields)
    originals["design.json"] = design.canonical_bytes()
    if generation_policy == "composition-v3":
        prompt = (
            "Return exactly one canonical safe-qlib-expression/v2 JSON AST as a proposal. "
            "Use only the finite price-return-volatility-trend/v1 grammar and adjusted_close. "
            "Choose w,a,b from {1,5,10,20,60}; C=Return(adjusted_close,w); "
            "N=Mean or Std(Return(adjusted_close,a),b); emit C, N, C/N or C*N. "
            "The complete AST has at most 8 nodes "
            "and depth at most 4. Use only FIELD, RETURN, ROLLING_STD, ROLLING_MEAN, DIVIDE, "
            "MULTIPLY. The finite grammar contains 555 canonical structures at the declared "
            "limits. No other field, operator, grammar production, data, tool or code; do not "
            "access the sealed period, use scientific feedback, or claim validated evidence. "
            "Use only the same-method static proposal history supplied for this reserved slot; "
            "never use evaluation results or another method's history. "
            f"There are {declared_opportunities} fresh opportunities per method; failures, "
            "duplicates and interruptions consume their slot. The authoring expression is an "
            "execution placeholder and will be replaced.\n"
            "Shared context originals (each SHA256 refers to the exact following UTF-8 bytes):\n"
            + "\n".join(
                f"{digest}: {data.decode('utf-8')}" for digest, data in sorted(contexts.items())
            )
        )
    else:
        prompt = (
            "Return exactly one canonical safe-qlib-expression/v2 JSON AST as a proposal. "
            "Use only the shared declared grammar, operators, windows and input lag. Do not access "
            "data, tools, code or sealed periods. Do not claim validated evidence. Each attempt "
            "is one of five fixed opportunities; failed, duplicate and interrupted "
            "attempts remain. "
            "The authoring expression is only an execution placeholder and will be replaced. "
            "A proposal must contain exactly one allowed window node; the placeholder "
            "is inadmissible."
            "\nShared context originals (each SHA256 refers to the exact following UTF-8 bytes):\n"
            + "\n".join(
                f"{digest}: {data.decode('utf-8')}" for digest, data in sorted(contexts.items())
            )
        )
    if generation_policy == "sequential-v2":
        prompt += (
            "\nUse the versioned same-method static history supplied with each attempt. "
            "Avoid prior structural duplicates. No scientific feedback is available."
        )
    elif generation_policy not in ("legacy-v1", "composition-v3"):
        raise ValueError("unsupported generation policy")
    request_hashes: dict[str, str] = {}
    methods: tuple[Literal["LLM", "RANDOM", "TEMPLATE"], ...] = ("LLM", "RANDOM", "TEMPLATE")
    for method in methods:
        config_bytes = (
            configuration_bytes
            if method == "LLM"
            else canonical_json_bytes(
                {
                    "schema_version": (
                        "discovery-baseline-configuration/v3"
                        if generation_policy == "composition-v3"
                        else "discovery-baseline-configuration/v2"
                        if generation_policy == "sequential-v2"
                        else "discovery-baseline-configuration/v1"
                    ),
                    "method": method,
                    "seed": 1729,
                    "generator": (
                        (
                            "quantos.application.discovery_baselines.bounded_composition_structural_uniform"
                            if method == "RANDOM"
                            else "quantos.application.discovery_baselines."
                            "composition_component_round_robin"
                        )
                        if generation_policy == "composition-v3"
                        else "quantos.application.discovery_baselines.generate_sequential_baseline"
                        if generation_policy == "sequential-v2"
                        else "quantos.application.discovery_baselines.generate_baseline"
                    ),
                    "max_attempts": declared_opportunities,
                    "space": (
                        "price-return-volatility-trend/v1"
                        if generation_policy == "composition-v3"
                        else "field-window-optional-ratio-abs/v1"
                    ),
                }
            )
        )
        request = GenerationRequest(
            design_hash=design.content_hash,
            method=method,
            max_attempts=declared_opportunities,
            seed=None if method == "LLM" else 1729,
            model_identifier=configuration.model if method == "LLM" else None,
            reasoning_effort=configuration.reasoning_effort if method == "LLM" else None,
            configuration_hash=sha256_bytes(config_bytes),
            prompt=prompt,
            input_hashes=design.context_hashes,
        )
        originals[f"{method.lower()}-request.json"] = request.canonical_bytes()
        originals[f"{method.lower()}-configuration.json"] = config_bytes
        request_hashes[method] = request.content_hash
    if generation_policy in ("sequential-v2", "composition-v3"):
        policy_fields: dict[str, object] = {
            "design_hash": design.content_hash,
            "request_hashes": (
                request_hashes["LLM"],
                request_hashes["RANDOM"],
                request_hashes["TEMPLATE"],
            ),
        }
        if generation_policy == "composition-v3":
            policy_fields["max_attempts_per_method"] = declared_opportunities
            policy = CompositionGenerationPolicy.model_validate(policy_fields)
        else:
            policy = SequentialGenerationPolicy.model_validate(policy_fields)
        originals["sequential-policy.json"] = policy.canonical_bytes()
    for digest, data in contexts.items():
        originals[f"contexts/sha256-{digest}.json"] = data
    inventory: dict[str, object] = {
        "schema_version": (
            "discovery-input-preparation/v3"
            if generation_policy == "composition-v3"
            else "discovery-input-preparation/v2"
            if generation_policy == "sequential-v2"
            else "discovery-input-preparation/v1"
        ),
        "status": "MANAGEMENT_INPUTS_ONLY",
        "design_hash": design.content_hash,
        "request_hashes": request_hashes,
        "code_provenance": provenance.model_dump(mode="json"),
        "historical_source_bundle_hash": _BUNDLE_HASH,
        "historical_event_root": str(historical_event_root),
        "qualification": "NOT_EVALUATED",
        "provider_observation": "UNKNOWN",
        "launcher_configuration_status": "REQUESTED_CONFIGURATION",
        "human_cost": None,
        "monetary_cost": None,
        "manifest_check_scope": "CANONICAL_METADATA_IDENTITY_ONLY; NOT DATA_REVERIFICATION",
        "files": {
            name: {"bytes_hash": sha256_bytes(data), "size_bytes": len(data)}
            for name, data in sorted(originals.items())
        },
    }
    inventory_bytes = canonical_json_bytes(inventory)
    destination = output_root / f"sha256-{sha256_bytes(inventory_bytes)}"
    for name, data in {**originals, "preparation.json": inventory_bytes}.items():
        validate_secret_free(_scan_view(json.loads(data)), file_name=Path(name).name)
        path = destination / name
        if path.exists():
            if _read_bytes(path, max_bytes=_MAX_MANIFEST_BYTES) != data:
                raise ValueError("immutable preparation original conflicts")
        else:
            atomic_write_bytes(path, data, expected_sha256=sha256_bytes(data))
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "workspace",
        "source-bundle",
        "historical-event-root",
        "snapshot-manifest",
        "view-manifest",
        "launcher-configuration",
        "output-root",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument(
        "--generation-policy",
        choices=("legacy-v1", "sequential-v2", "composition-v3"),
        default="legacy-v1",
    )
    parser.add_argument(
        "--max-compute-units",
        type=int,
        help="explicit successor design cap; grants no execution authority",
    )
    parser.add_argument(
        "--opportunities",
        type=int,
        help="composition-v3 opportunities per method; defaults to 3 and grants no run authority",
    )
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--lockfile-hash", required=True)
    args = parser.parse_args()
    try:
        result = prepare_inputs(**vars(args))
    except (OSError, RuntimeError, ValueError, StopIteration):
        print(json.dumps({"status": "FAILED", "reason": "INPUT_PREPARATION_REJECTED"}))
        return 1
    print(json.dumps({"status": "MANAGEMENT_INPUTS_ONLY", "directory": str(result)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
