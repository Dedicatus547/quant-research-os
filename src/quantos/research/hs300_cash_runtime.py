"""Cash-only source/runtime admission around native Qlib generation, before fills.

No project account, order, settlement or entitlement accounting is introduced.
Derived cash ineligibility is separate from Qlib's unavailable rights ledger.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import json
import math
import pickle
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Any, cast

import pandas as pd

from quantos.artifacts.store import atomic_write_bytes, confined_regular_file, sha256_file
from quantos.backtest.strategy import FullReplacementTopKStrategy
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.cash_option_proof import ContinuousCashOptionRule
from quantos.contracts.hs300_adjusted import PreparedHS300AdjustedStudy
from quantos.contracts.hs300_cash import (
    BoundArtifact,
    CashRuntimePolicy,
    ClassicOriginReuse,
    HS300CashDatasetManifest,
    PreparedHS300CashStudy,
    SignalReuseSpec,
)
from quantos.contracts.hs300_lifecycle import (
    NativeBoundaryObservation,
    PreparedHS300LifecycleStudy,
    UnsupportedAccountEvent,
)
from quantos.research.cash_option_proof import derive_continuous_cash_rule
from quantos.research.hs300_lifecycle_data import (
    load_lifecycle_facts,
    verify_hs300_lifecycle_binding,
)
from quantos.research.hs300_native_boundary import (
    LifecycleBoundaryTopKStrategy,
    NativeAccountBoundaryStop,
    evaluate_native_boundary,
    event_check_start,
    native_boundary_runtime_identity,
)


def cash_native_runtime_identity() -> dict[str, str]:
    names = (
        "qlib.backtest.account",
        "qlib.backtest.position",
        "qlib.backtest.executor",
        "qlib.backtest.decision",
        "qlib.backtest.exchange",
        "qlib.backtest.backtest",
        "qlib.backtest.signal",
        "qlib.backtest.utils",
        "qlib.contrib.strategy.order_generator",
        "qlib.contrib.strategy.signal_strategy",
        "qlib.strategy.base",
        "qlib.utils.time",
        "qlib.data.dataset.utils",
        "qlib.utils.resam",
    )
    return {
        name: sha256_file(Path(cast(Any, importlib.import_module(name)).__file__)) for name in names
    }


def signal_compiler_dependency_hashes() -> dict[str, str]:
    """Bind actual compiler inputs without making executor edits compiler changes."""
    from quantos.research import hs300_data, hs300_lifecycle_data, personal_qlib

    return {
        "hs300_data.py": sha256_file(Path(hs300_data.__file__)),
        "hs300_lifecycle_data.py": sha256_file(Path(hs300_lifecycle_data.__file__)),
        **{
            f"personal_qlib.py:{name}": sha256_bytes(
                inspect.getsource(getattr(personal_qlib, name)).encode()
            )
            for name in ("compile_daily_signals", "_rolling20", "_momentum5", "_prior_volume5")
        },
        "pandas": pd.__version__,
    }


def _artifact(root: str, ref: BoundArtifact) -> Path:
    origin = Path(root)
    if not origin.is_absolute():
        raise ValueError("origin root must be explicit absolute operator configuration")
    path = confined_regular_file(origin, ref.path)
    if sha256_file(path) != ref.sha256:
        raise ValueError("origin original hash differs")
    return path


def _same_scientific_inputs(old: Any, new: PreparedHS300CashStudy) -> None:
    if old.dataset_manifest is None or new.dataset_manifest is None:
        raise ValueError("origin dataset is missing")
    before_manifest = old.dataset_manifest.model_dump()
    after_manifest = new.dataset_manifest.model_dump()
    for key in ("cash_rules", "cash_runtime_policy_hash", "native_source_hashes"):
        after_manifest.pop(key, None)
    if isinstance(new, PreparedHS300AdjustedStudy):
        for key in (
            "adjusted_facts",
            "adjusted_unit_policy_hash",
            "adjusted_runtime_source_hashes",
            "future_quote_binding",
        ):
            after_manifest.pop(key)
    for key in ("schema_version", "dataset_id"):
        after_manifest[key] = before_manifest[key]
    if before_manifest != after_manifest:
        raise ValueError("origin scientific dataset dependency differs")
    for key in ("start_date", "end_date", "benchmark", "warmup_start"):
        if getattr(old.request, key) != getattr(new.request, key):
            raise ValueError(f"origin scientific request dependency differs: {key}")
    before = old.request.profile.model_dump()
    after = new.request.profile.model_dump()
    after.pop("cash_runtime_policy_hash", None)
    if isinstance(new, PreparedHS300AdjustedStudy):
        for key in ("valuation_scope", "model_semantics_hash", "adjusted_unit_policy_hash"):
            after.pop(key)
    after["schema_version"] = before["schema_version"]
    if before != after or old.candidates != new.candidates:
        raise ValueError("origin strategy parameters or candidate definitions differ")


def _verified_dependency_manifest(root: str, ref: BoundArtifact, old: Any) -> dict[str, Any]:
    dependencies = json.loads(_artifact(root, ref).read_bytes())
    if sha256_bytes(canonical_json_bytes(dependencies)) != old.code_hash:
        raise ValueError("origin dependency manifest is not the prepared originating code tuple")
    if dependencies["python"] != sys.version or any(
        version(package) != expected for package, expected in dependencies["environment"].items()
    ):
        raise ValueError("origin scientific environment differs")
    return cast(dict[str, Any], dependencies)


def _verify_compiler_origins(spec: SignalReuseSpec, old: Any) -> None:
    dependencies = _verified_dependency_manifest(spec.origin_root, spec.dependency_manifest, old)
    required = {
        "src/quantos/research/hs300_data.py",
        "src/quantos/research/hs300_lifecycle_data.py",
        "src/quantos/research/personal_qlib.py",
    }
    if set(spec.compiler_originals) != required:
        raise ValueError("complete original compiler source inventory is required")
    repo = Path(__file__).resolve().parents[3]
    for logical, ref in spec.compiler_originals.items():
        original = _artifact(spec.origin_root, ref)
        if dependencies["sources"].get(logical) != ref.sha256:
            raise ValueError("compiler original is not anchored in originating dependency tuple")
        if logical.endswith("personal_qlib.py"):
            names = {
                "PersonalPITError",
                "PANEL_COLUMNS",
                "compile_daily_signals",
                "_rolling20",
                "_momentum5",
                "_prior_volume5",
            }

            def selected(path: Path, selected_names: set[str] = names) -> list[str]:
                return [
                    ast.dump(node, include_attributes=False)
                    for node in ast.parse(path.read_bytes()).body
                    if getattr(node, "name", None) in selected_names
                    or (
                        isinstance(node, ast.Assign)
                        and any(
                            isinstance(target, ast.Name) and target.id in selected_names
                            for target in node.targets
                        )
                    )
                ]

            if selected(original) != selected(repo / logical):
                raise ValueError("signal compiler functions, exception or constants changed")
        elif sha256_file(repo / logical) != ref.sha256:
            raise ValueError("signal compiler transitive module changed")
    for logical in ("src/quantos/contracts/base.py", "src/quantos/artifacts/store.py"):
        if sha256_file(repo / logical) != dependencies["sources"].get(logical):
            raise ValueError("compiler canonicalization or artifact dependency changed")


def verify_reused_signal_bindings(
    prepared: PreparedHS300CashStudy, spec: SignalReuseSpec
) -> dict[str, bytes]:
    """Verify every original/compiler/checkpoint binding without deserializing signals."""
    old = PreparedHS300LifecycleStudy.model_validate_json(
        _artifact(spec.origin_root, spec.prepared).read_bytes()
    )
    _same_scientific_inputs(old, prepared)
    _verify_compiler_origins(spec, old)
    if (
        prepared.dataset_manifest is None
        or spec.panel_sha256 != prepared.dataset_manifest.panel_sha256
        or spec.compiler_dependency_hashes != signal_compiler_dependency_hashes()
    ):
        raise ValueError("signal compiler or actual input dependency changed")
    checkpoint = json.loads(_artifact(spec.origin_root, spec.checkpoint).read_bytes())
    hashes = {row["candidate_id"]: row["signal_sha256"] for row in checkpoint["rows"]}
    expected = {candidate.candidate_id for candidate in prepared.candidates}
    if (
        checkpoint.get("task_id") != old.content_hash
        or checkpoint.get("code_hash") != old.code_hash
        or checkpoint.get("panel_sha256") != spec.panel_sha256
        or set(hashes) != expected
        or set(spec.signal_files) != expected
    ):
        raise ValueError("signal checkpoint origin or seven-arm inventory differs")
    signals: dict[str, bytes] = {}
    for candidate, ref in spec.signal_files.items():
        if hashes[candidate] != ref.sha256:
            raise ValueError("signal original differs from independent checkpoint")
        raw = _artifact(spec.origin_root, ref).read_bytes()
        if sha256_bytes(raw) != ref.sha256:
            raise ValueError("signal original changed while reading")
        signals[candidate] = raw
    return signals


def load_reused_signals(
    prepared: PreparedHS300CashStudy, spec: SignalReuseSpec
) -> dict[str, pd.DataFrame]:
    return {
        candidate: pickle.loads(raw)
        for candidate, raw in verify_reused_signal_bindings(prepared, spec).items()
    }


def reused_signal_bytes(spec: SignalReuseSpec, candidate_id: str) -> bytes:
    """Retain original bytes; pandas caches may alter a subsequent pickle encoding."""
    return _artifact(spec.origin_root, spec.signal_files[candidate_id]).read_bytes()


def _verify_classic_executor_origins(spec: SignalReuseSpec) -> None:
    """Keep scientific AST exact after removing only explicit boundary wrappers."""
    original = _artifact(
        spec.origin_root, spec.compiler_originals["src/quantos/research/personal_qlib.py"]
    )
    before = ast.parse(original.read_bytes())
    after = ast.parse(Path(__file__).with_name("personal_qlib.py").read_bytes())

    def function(tree: ast.Module, name: str) -> ast.FunctionDef:
        nodes = [
            node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name
        ]
        if len(nodes) != 1:
            raise ValueError("classic scientific helper is missing or duplicated")
        return nodes[0]

    def config(tree: ast.Module) -> ast.FunctionDef:
        classes = [
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "PersonalQlibExecutor"
        ]
        if len(classes) != 1:
            raise ValueError("classic originating executor class differs")
        nodes = [
            node
            for node in classes[0].body
            if isinstance(node, ast.FunctionDef) and node.name == "_config"
        ]
        if len(nodes) != 1:
            raise ValueError("classic scientific configuration helper differs")
        return nodes[0]

    for name in ("_finite", "_metrics", "_native_order_rows"):
        if ast.dump(function(before, name)) != ast.dump(function(after, name)):
            raise ValueError("classic scientific metric or native-order export helper changed")
    allowed = ast.parse("""
if isinstance(prepared, PreparedHS300CashStudy):
    config["strategy"]["class"] = "CashRuntimeBoundaryTopKStrategy"
    config["strategy"]["module_path"] = "quantos.research.hs300_cash_runtime"
    config["strategy"]["kwargs"].update(
        {
            "cash_rules": [rule.model_dump(mode="json") for rule in manifest.cash_rules],
            "native_source_hashes": manifest.native_source_hashes,
        }
    )
""").body[0]
    current = config(after)
    additions = [
        node
        for node in ast.walk(current)
        if isinstance(node, ast.If) and ast.dump(node.test) == ast.dump(cast(ast.If, allowed).test)
    ]
    if len(additions) != 1 or ast.dump(additions[0]) != ast.dump(allowed):
        raise ValueError("cash successor config branch exceeds the reviewed audit-wrapper scope")
    adjusted = ast.parse("""
if isinstance(prepared, PreparedHS300AdjustedStudy):
    config["strategy"]["class"] = "AdjustedUnitBoundaryTopKStrategy"
    config["strategy"]["module_path"] = "quantos.research.hs300_adjusted_runtime"
    config["strategy"]["kwargs"].update(
        {
            "adjusted_facts": manifest.adjusted_facts.model_dump(mode="json"),
            "adjusted_unit_policy_hash": manifest.adjusted_unit_policy_hash,
            "adjusted_runtime_source_hashes": manifest.adjusted_runtime_source_hashes,
            "future_quote_binding": manifest.future_quote_binding.model_dump(mode="json"),
            "provider_root": str(binding.provider_root.absolute()),
        }
    )
""").body[0]
    adjusted_additions = [
        node
        for node in ast.walk(current)
        if isinstance(node, ast.If) and ast.dump(node.test) == ast.dump(cast(ast.If, adjusted).test)
    ]
    if len(adjusted_additions) != 1 or ast.dump(adjusted_additions[0]) != ast.dump(adjusted):
        raise ValueError("adjusted-unit config branch exceeds the reviewed audit-wrapper scope")

    class RemoveReviewedCashBranch(ast.NodeTransformer):
        def visit_If(self, node: ast.If) -> ast.AST | None:
            if node is additions[0] or node is adjusted_additions[0]:
                return None
            return self.generic_visit(node)

    projected = RemoveReviewedCashBranch().visit(current)
    if ast.dump(config(before)) != ast.dump(cast(ast.AST, projected)):
        raise ValueError("classic scientific execution configuration changed")


def verify_classic_origin(
    prepared: PreparedHS300CashStudy, origin: ClassicOriginReuse
) -> dict[str, Any]:
    old = PreparedHS300LifecycleStudy.model_validate_json(
        _artifact(origin.origin_root, origin.prepared).read_bytes()
    )
    _same_scientific_inputs(old, prepared)
    assert old.dataset_manifest is not None
    receipt_path = _artifact(origin.origin_root, origin.receipt)
    receipt = json.loads(receipt_path.read_bytes())
    outcome = json.loads(_artifact(origin.origin_root, origin.outcome).read_bytes())
    for ref in (*origin.dependencies, *origin.source_refs):
        _artifact(origin.origin_root, ref)
    dependency_refs = [
        ref
        for ref in origin.dependencies
        if sha256_bytes(
            canonical_json_bytes(json.loads(_artifact(origin.origin_root, ref).read_bytes()))
        )
        == old.code_hash
    ]
    if len(dependency_refs) != 1:
        raise ValueError("classic origin requires its original prepared dependency manifest")
    dependencies = _verified_dependency_manifest(origin.origin_root, dependency_refs[0], old)
    repo = Path(__file__).resolve().parents[3]
    for logical, digest in dependencies["sources"].items():
        if logical.startswith("qlib/"):
            module_name = logical.removesuffix(".py").replace("/", ".")
            if module_name.endswith(".__init__"):
                module_name = module_name.removesuffix(".__init__")
            actual = Path(cast(Any, importlib.import_module(module_name)).__file__)
        elif logical in {
            "src/quantos/backtest/strategy.py",
            "src/quantos/research/hs300_exchange.py",
            "src/quantos/research/hs300_native_boundary.py",
            "src/quantos/research/qlib/workflow.py",
            "src/quantos/contracts/base.py",
            "src/quantos/artifacts/store.py",
        }:
            actual = repo / logical
        else:
            continue
        if sha256_file(actual) != digest:
            raise ValueError(f"classic native execution dependency changed: {logical}")
    if (
        receipt.get("prepared_hash") != old.content_hash
        or outcome.get("prepared_hash") != old.content_hash
        or receipt.get("candidate_id") != "classic"
        or receipt.get("run_status") != "SUCCEEDED"
        or receipt.get("qlib_version") != "0.9.7"
        or receipt.get("native_boundary_status") != "CLEARED_ZERO_EXPOSURE"
        or not any(
            row.get("candidate_id") == "classic"
            and row.get("receipt_hash") == origin.receipt.sha256
            and row.get("run_status") == "SUCCEEDED"
            for row in outcome.get("receipts", ())
        )
    ):
        raise ValueError("completed classic originating tuple is unproven")
    if prepared.signal_reuse is None:
        raise ValueError("classic reuse requires separately verified identical signal inputs")
    signal_ref = prepared.signal_reuse.signal_files.get("classic")
    if signal_ref is None or receipt.get("signal_sha256") != signal_ref.sha256:
        raise ValueError("classic receipt signal differs from adopted signal")
    _verify_compiler_origins(prepared.signal_reuse, old)
    _verify_classic_executor_origins(prepared.signal_reuse)
    for logical, digest in receipt.get("files", {}).items():
        if sha256_file(confined_regular_file(receipt_path.parent, logical)) != digest:
            raise ValueError("classic native original export differs")
    boundaries = receipt.get("boundary_receipts", ())
    if not boundaries:
        raise ValueError("classic origin lacks native boundary originals")
    facts = None
    for ref in origin.source_refs:
        path = _artifact(origin.origin_root, ref)
        if path.suffix == ".json":
            value = json.loads(path.read_bytes())
            if value.get("schema_version") == "hs300-lifecycle-facts/v1":
                facts = load_lifecycle_facts(path, old.dataset_manifest.lifecycle_manifest_hash)
    if facts is None:
        raise ValueError("classic reuse requires the originating lifecycle facts original")
    native_hashes = native_boundary_runtime_identity()
    for ref in boundaries:
        if receipt["files"].get(ref["file"]) != ref["sha256"]:
            raise ValueError("classic boundary original is not bound in native exports")
        value = json.loads(confined_regular_file(receipt_path.parent, ref["file"]).read_bytes())
        observation = NativeBoundaryObservation.model_validate(value["observation"])
        due = [event for event in facts.events if event_check_start(event) <= observation.session]
        expected = [
            evaluate_native_boundary(event, observation, facts.policy).model_dump(mode="json")
            for event in due
        ]
        if (
            value["lifecycle_manifest_hash"] != facts.content_hash
            or value["events"] != {event.event_id: event.content_hash for event in due}
            or value["decisions"] != expected
            or any(item["status"] != "CLEARED_ZERO_EXPOSURE" for item in expected)
            or observation.native_source_hashes != native_hashes
        ):
            raise ValueError("classic origin boundary path is not unchanged v1 admissible")
    return cast(dict[str, Any], receipt)


def verify_hs300_cash_binding(binding: Any) -> None:
    verify_hs300_lifecycle_binding(binding)
    manifest = binding.manifest
    if not isinstance(manifest, HS300CashDatasetManifest):
        raise ValueError("cash runtime requires its explicit successor dataset")
    if manifest.cash_runtime_policy_hash != CashRuntimePolicy().content_hash:
        raise ValueError("cash runtime policy hash differs")
    if manifest.native_source_hashes != cash_native_runtime_identity():
        raise ValueError("reviewed native order-generation runtime differs")
    if binding.cash_rules_path is None:
        raise ValueError("cash runtime rules original is missing")
    bundle = json.loads(binding.cash_rules_path.read_bytes())
    if (
        bundle.get("schema_version") != "hs300-cash-rules/v1"
        or set(bundle) != {"schema_version", "rules"}
        or tuple(ContinuousCashOptionRule.model_validate(value) for value in bundle["rules"])
        != manifest.cash_rules
    ):
        raise ValueError("cash runtime rule bundle differs from immutable dataset")
    facts = load_lifecycle_facts(binding.lifecycle_path, manifest.lifecycle_manifest_hash)
    if len({rule.instrument_id for rule in manifest.cash_rules}) != len(manifest.cash_rules):
        raise ValueError("duplicate cash rule")
    for rule in manifest.cash_rules:
        if facts.source_vintage != "synthetic":
            if (
                derive_continuous_cash_rule(
                    facts, binding.lifecycle_path.parent, rule.instrument_id
                )
                != rule
            ):
                raise ValueError("cash source rule differs from official original")
        elif not any(
            source.source_id == rule.source_id and source.sha256 == rule.source_sha256
            for source in facts.sources
        ):
            raise ValueError("synthetic rule source binding differs")


def evaluate_cash_boundary(
    event: UnsupportedAccountEvent,
    observation: NativeBoundaryObservation,
    rule: ContinuousCashOptionRule,
    *,
    phase: str,
    actual_target: dict[str, float] | None,
    locked_proof_hash: str | None,
) -> dict[str, Any]:
    """Necessary-condition cash proof; never modifies observed native rights."""
    affected = {
        code[-2:] + code[:6] for code in (event.instrument_id, *event.related_instrument_ids)
    }
    reasons: list[str] = []
    unknown = not (
        observation.native_classes_verified
        and observation.fresh_cash_no_initial_holdings_no_external_flow
        and observation.sequential_history_complete
        and observation.all_holdings is not None
        and observation.previous_unfilled_orders is not None
        and observation.current_generated_orders is not None
    )
    exposed = bool(affected.intersection(observation.observed_pending_rights or ()))
    if exposed:
        reasons.append("known independent affected rights override stock-absence inference")
    if (
        observation.pending_rights_observability == "OBSERVABLE"
        and observation.observed_pending_rights is None
    ):
        unknown = True
    if any(not math.isfinite(v) for v in (observation.all_holdings or {}).values()):
        unknown = True
    if unknown:
        reasons.append("complete ordinary native account lineage or current observations missing")
    if locked_proof_hash is None:
        if (
            event.event_type != "CASH_OPTION"
            or event.instrument_id != rule.instrument_id
            or event.entitlement_window_start != rule.window_start
            or rule.source_id not in event.source_ids
            or not rule.window_start <= observation.session <= rule.window_end
        ):
            unknown = True
            reasons.append("source-bound necessary continuous-holding window is unavailable")
        if affected.intersection(observation.all_holdings or {}):
            exposed = True
            reasons.append("affected security remains in current native position support")
        for orders in (observation.previous_unfilled_orders, observation.current_generated_orders):
            if orders is not None and any(
                order.qlib_id in affected and order.amount > order.deal_amount for order in orders
            ):
                exposed = True
                reasons.append("affected pending or actual generated native order")
        if phase == "generated":
            if actual_target is None or any(
                not math.isfinite(weight) or weight < 0 for weight in actual_target.values()
            ):
                unknown = True
                reasons.append("actual native target invocation was not observed")
            elif affected.intersection(actual_target):
                exposed = True
                reasons.append("actual target supports an affected security")
    status = (
        "HARD_STOP_EXPOSURE"
        if exposed
        else "HARD_STOP_UNKNOWN"
        if unknown
        else "CLEARED_DERIVED_CASH_INELIGIBILITY"
        if locked_proof_hash or phase == "generated"
        else "PENDING_ACTUAL_GENERATION"
    )
    return {
        "event_id": event.event_id,
        "event_hash": event.content_hash,
        "observation_hash": observation.content_hash,
        "policy_hash": CashRuntimePolicy().content_hash,
        "rule_hash": rule.content_hash,
        "status": status,
        "rights_conclusion": "DERIVED_THIS_CASH_RIGHT_ZERO"
        if status == "CLEARED_DERIVED_CASH_INELIGIBILITY"
        else "UNPROVEN",
        "native_rights_observability": observation.pending_rights_observability,
        "locked_proof_hash": locked_proof_hash,
        "reasons": reasons,
        "covers_merger_or_delisting": False,
    }


class CashRuntimeBoundaryTopKStrategy(LifecycleBoundaryTopKStrategy):
    def __init__(
        self,
        *,
        cash_rules: list[dict[str, Any]],
        native_source_hashes: dict[str, str],
        **kwargs: Any,
    ) -> None:
        if native_source_hashes != cash_native_runtime_identity():
            raise ValueError("cash runtime native source identity differs")
        self._cash_rules = {
            rule.instrument_id: rule
            for rule in (ContinuousCashOptionRule.model_validate(value) for value in cash_rules)
        }
        self._cash_locked: dict[str, str] = {}
        self._actual_target: dict[str, float] | None = None
        self._cash_runtime_hashes = native_source_hashes
        super().__init__(**kwargs)

    def generate_target_weight_position(self, *args: Any, **kwargs: Any) -> dict[str, float]:
        target = super().generate_target_weight_position(*args, **kwargs)
        self._actual_target = dict(target)
        return target

    def _cash_boundaries(
        self,
        events: list[UnsupportedAccountEvent],
        observation: NativeBoundaryObservation,
        phase: str,
    ) -> None:
        decisions: list[dict[str, Any]] = []
        for event in events:
            rule = self._cash_rules.get(event.instrument_id)
            if event.event_type == "CASH_OPTION" and rule is not None:
                decision = evaluate_cash_boundary(
                    event,
                    observation,
                    rule,
                    phase=phase,
                    actual_target=self._actual_target,
                    locked_proof_hash=self._cash_locked.get(event.event_id),
                )
            else:
                decision = evaluate_native_boundary(
                    event, observation, self._facts.policy
                ).model_dump(mode="json")
            decisions.append(decision)
        payload = {
            "schema_version": "hs300-native-boundary-receipt/v2",
            "events": {event.event_id: event.content_hash for event in events},
            "observation": observation,
            "decisions": decisions,
            "actual_target": self._actual_target if phase == "generated" else None,
            "phase": phase,
            "lifecycle_manifest_hash": self._facts.content_hash,
            "cash_runtime_policy_hash": CashRuntimePolicy().content_hash,
            "native_source_hashes": self._cash_runtime_hashes,
            "native_rights_observability": "UNAVAILABLE_IN_QLIB_0_9_7",
        }
        raw = canonical_json_bytes(payload)
        atomic_write_bytes(
            self._boundary_root / f"{observation.session.isoformat()}-{phase}.json", raw
        )
        for decision in decisions:
            if decision["status"] == "CLEARED_DERIVED_CASH_INELIGIBILITY":
                self._cash_locked.setdefault(decision["event_id"], sha256_bytes(raw))
        stopped = next((item for item in decisions if item["status"].startswith("HARD_STOP")), None)
        if stopped is not None:
            account = cast(Any, self).common_infra.get("trade_account")
            for name, value in (
                ("position", account.current_position),
                ("portfolio", account.get_portfolio_metrics()),
                ("indicator", account.get_trade_indicator()),
            ):
                atomic_write_bytes(
                    self._boundary_root / f"{observation.session.isoformat()}-partial-{name}.pkl",
                    pickle.dumps(value, protocol=4),
                )
            raise NativeAccountBoundaryStop(stopped["event_id"])

    def generate_trade_decision(self, execute_result: Any = None) -> Any:
        calendar = cast(Any, self).trade_calendar
        step = int(calendar.get_trade_step())
        session, _ = calendar.get_step_time(step)
        if step != self._last_step + 1:
            self._complete_history = False
        pre = self._observation(step, session, execute_result, ())
        due = [
            event
            for event in self._facts.events
            if event_check_start(event) <= pd.Timestamp(session).date()
        ]
        self._actual_target = None
        if due:
            self._cash_boundaries(due, pre, "before")
        # Call the original target/native-order path directly; v1's earlier
        # unobservable-rights stop is superseded only by the cash check above.
        decision = cast(Any, FullReplacementTopKStrategy).generate_trade_decision(
            self, execute_result
        )
        post = self._observation(step, session, execute_result, decision.get_decision())
        if due:
            self._cash_boundaries(due, post, "generated")
        self._last_step = step
        return decision
