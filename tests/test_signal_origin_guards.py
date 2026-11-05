"""Synthetic origin tampering cases; projected source is not historical evidence."""

import ast
import sys
from copy import deepcopy
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace

import pytest

from quantos.artifacts.store import ArtifactIntegrityError, sha256_file
from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.hs300_cash import BoundArtifact, SignalReuseSpec
from quantos.research import hs300_cash_runtime as runtime

REPO = Path(__file__).resolve().parents[1]
COMPILERS = (
    "src/quantos/research/hs300_data.py",
    "src/quantos/research/hs300_lifecycle_data.py",
    "src/quantos/research/personal_qlib.py",
)


@pytest.fixture
def origin(tmp_path):
    def put(name, raw):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return BoundArtifact(path=name, sha256=sha256_file(path))

    refs = {name: put("originals/" + name, (REPO / name).read_bytes()) for name in COMPILERS}
    dependencies = {
        "python": sys.version,
        "environment": {"pyqlib": version("pyqlib")},
        "sources": {
            name: sha256_file(REPO / name)
            for name in (
                *COMPILERS,
                "src/quantos/contracts/base.py",
                "src/quantos/artifacts/store.py",
            )
        },
    }
    placeholder = put("unused.json", b"{}")

    def bind():
        dep = put("dependencies.json", canonical_json_bytes(dependencies))
        spec = SignalReuseSpec(
            origin_root=str(tmp_path),
            prepared=placeholder,
            checkpoint=placeholder,
            dependency_manifest=dep,
            compiler_originals=refs,
            signal_files={},
            compiler_dependency_hashes={},
            panel_sha256="a" * 64,
        )
        return spec, SimpleNamespace(code_hash=dep.sha256)

    return SimpleNamespace(root=tmp_path, put=put, refs=refs, dependencies=dependencies, bind=bind)


def test_compiler_adoption_checks_original_bytes_and_transitive_identity(origin):
    spec, old = origin.bind()
    runtime._verify_compiler_origins(spec, old)
    assert (
        runtime._verified_dependency_manifest(spec.origin_root, spec.dependency_manifest, old)
        == origin.dependencies
    )
    artifact = origin.put("signals/classic.pkl", b"synthetic opaque signal; never unpickled")
    spec = spec.model_copy(update={"signal_files": {"classic": artifact}})
    assert (
        runtime.reused_signal_bytes(spec, "classic") == (origin.root / artifact.path).read_bytes()
    )
    (origin.root / artifact.path).write_bytes(b"changed")
    with pytest.raises(ValueError, match="original hash differs"):
        runtime.reused_signal_bytes(spec, "classic")
    with pytest.raises(ValueError, match="absolute operator"):
        runtime._artifact("relative", artifact)


@pytest.mark.parametrize("change", ["python", "package", "prepared_hash"])
def test_dependency_record_cannot_change_its_origin_or_environment(origin, change):
    if change == "python":
        origin.dependencies["python"] = "different interpreter"
    elif change == "package":
        origin.dependencies["environment"]["pyqlib"] = "0.0.0"
    spec, old = origin.bind()
    if change == "prepared_hash":
        old.code_hash = "b" * 64
    with pytest.raises(ValueError, match=r"(environment differs|originating code tuple)"):
        runtime._verified_dependency_manifest(spec.origin_root, spec.dependency_manifest, old)


@pytest.mark.parametrize(
    "attack",
    ["inventory", "anchor", "compiler", "transitive", "canonicalizer", "missing", "symlink"],
)
def test_compiler_reuse_rejects_incomplete_or_changed_dependencies(origin, attack):
    name = COMPILERS[2] if attack == "compiler" else COMPILERS[0]
    if attack == "inventory":
        origin.refs.pop(name)
    elif attack == "anchor":
        origin.dependencies["sources"][name] = "b" * 64
    elif attack in {"compiler", "transitive"}:
        raw = (REPO / name).read_bytes()
        raw = (
            raw.replace(b"rolling(20", b"rolling(19")
            if attack == "compiler"
            else raw + b"\n# changed origin\n"
        )
        ref = origin.put("originals/" + name, raw)
        origin.refs[name] = ref
        origin.dependencies["sources"][name] = ref.sha256
    elif attack == "canonicalizer":
        origin.dependencies["sources"]["src/quantos/contracts/base.py"] = "b" * 64
    else:
        path = origin.root / origin.refs[name].path
        path.unlink()
        if attack == "symlink":
            path.symlink_to(REPO / name)
    spec, old = origin.bind()
    with pytest.raises((ValueError, ArtifactIntegrityError)):
        runtime._verify_compiler_origins(spec, old)


def projected_predecessor():
    tree = ast.parse((REPO / COMPILERS[2]).read_bytes())

    class Predecessor(ast.NodeTransformer):
        def visit_If(self, node):
            if (
                isinstance(node.test, ast.Call)
                and isinstance(node.test.func, ast.Name)
                and node.test.func.id == "isinstance"
                and len(node.test.args) == 2
            ):
                kind = node.test.args[1]
                if isinstance(kind, ast.Name) and kind.id in {
                    "PreparedHS300CashStudy",
                    "PreparedHS300AdjustedStudy",
                }:
                    return None
            return self.generic_visit(node)

    return ast.unparse(Predecessor().visit(tree)).encode()


def test_only_reviewed_wrappers_are_removed_from_scientific_config(origin):
    origin.refs[COMPILERS[2]] = origin.put("predecessor.py", projected_predecessor())
    spec, _ = origin.bind()
    runtime._verify_classic_executor_origins(spec)


@pytest.mark.parametrize(
    "attack", ["metrics", "missing_helper", "missing_class", "missing_config", "price"]
)
def test_classic_reuse_rejects_scientific_helper_or_execution_changes(origin, attack):
    raw = projected_predecessor().decode()
    changes = {
        "metrics": ("wealth.iloc[-1] - 1", "wealth.iloc[-1] - 2"),
        "missing_helper": ("def _finite(", "def _renamed_finite("),
        "missing_class": ("class PersonalQlibExecutor:", "class DifferentExecutor:"),
        "missing_config": ("def _config(", "def _different_config("),
        "price": ("'deal_price': '$open'", "'deal_price': '$close'"),
    }
    before, after = changes[attack]
    assert before in raw
    origin.refs[COMPILERS[2]] = origin.put("predecessor.py", raw.replace(before, after).encode())
    spec, _ = origin.bind()
    with pytest.raises(ValueError, match="classic"):
        runtime._verify_classic_executor_origins(spec)


@pytest.fixture
def scientific_pair():
    def wrapped(value):
        return SimpleNamespace(model_dump=lambda: deepcopy(value))

    dataset = {"schema_version": "old", "dataset_id": "before", "snapshot_hash": "a" * 64}
    profile = {"schema_version": "old", "buy_cost": 0.001, "risk_degree": 0.9}
    args = {
        "start_date": "2024-01-03",
        "end_date": "2024-01-05",
        "benchmark": "SH000300",
        "warmup_start": "2023-11-01",
    }
    old = SimpleNamespace(
        dataset_manifest=wrapped(dataset),
        request=SimpleNamespace(**args, profile=wrapped(profile)),
        candidates=("fixed",),
    )
    new = SimpleNamespace(
        dataset_manifest=wrapped(
            {
                **dataset,
                "schema_version": "cash",
                "dataset_id": "after",
                "cash_rules": [],
                "cash_runtime_policy_hash": "b" * 64,
                "native_source_hashes": {},
            }
        ),
        request=SimpleNamespace(
            **args,
            profile=wrapped(
                {**profile, "schema_version": "cash", "cash_runtime_policy_hash": "b" * 64}
            ),
        ),
        candidates=old.candidates,
    )
    return old, new, wrapped


def test_versioned_identity_change_does_not_change_scientific_inputs(scientific_pair):
    old, new, _ = scientific_pair
    runtime._same_scientific_inputs(old, new)


@pytest.mark.parametrize(
    "field",
    [
        "missing",
        "snapshot_hash",
        "start_date",
        "end_date",
        "benchmark",
        "warmup_start",
        "candidates",
        "buy_cost",
        "risk_degree",
    ],
)
def test_reuse_rejects_changed_scientific_inputs(scientific_pair, field):
    old, new, wrapped = scientific_pair
    if field == "missing":
        new.dataset_manifest = None
    elif field == "snapshot_hash":
        new.dataset_manifest = wrapped({**new.dataset_manifest.model_dump(), field: "b" * 64})
    elif field == "candidates":
        new.candidates = ("different",)
    elif field in {"buy_cost", "risk_degree"}:
        new.request.profile = wrapped({**new.request.profile.model_dump(), field: 0.2})
    else:
        setattr(new.request, field, "different")
    with pytest.raises(ValueError, match="origin"):
        runtime._same_scientific_inputs(old, new)
