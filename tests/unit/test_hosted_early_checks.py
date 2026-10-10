"""Development diagnostics reject altered originals and never publish qualification."""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted_qualification import (
    HostedManagerExport,
    HostedManagerExportFile,
    HostedQualificationCase,
    HostedQualificationFile,
    HostedQualificationRoot,
    HostedRawInventory,
)
from quantos.infrastructure.hosted_verification import HostedQualificationError

SPEC = importlib.util.spec_from_file_location(
    "hosted_early_checks", Path(__file__).parents[2] / "scripts/hosted_early_checks.py"
)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)
bind_selected_sources = runner.bind_selected_sources
case_denominators = runner.case_denominators
index_capacity = runner.index_capacity
selected_closure = runner.selected_closure
write_diagnostic = runner.write_diagnostic


def test_native_git_check_disables_index_refresh_and_restores_environment(monkeypatch):
    monkeypatch.setenv("GIT_OPTIONAL_LOCKS", "1")
    assert runner.readonly_git_action(lambda: os.environ["GIT_OPTIONAL_LOCKS"]) == "0"
    assert os.environ["GIT_OPTIONAL_LOCKS"] == "1"
    with pytest.raises(RuntimeError):
        runner.readonly_git_action(lambda: (_ for _ in ()).throw(RuntimeError("check failed")))
    assert os.environ["GIT_OPTIONAL_LOCKS"] == "1"


def test_incomplete_original_failure_records_need_no_bundle_or_authority_reader(tmp_path):
    manager = tmp_path / "manager"
    channel = manager / "qualification-cases/Q05/register-intent_published-1/channel"
    records = channel / "process-records"
    records.mkdir(parents=True)
    failure = {
        "error_type": "ArtifactIntegrityError",
        "failure_locations": [
            {
                "module": "quantos.infrastructure.hosted_service",
                "function": "bootstrap_hosted_service",
                "line": 443,
            }
        ],
        "error_message": "arbitrary untrusted log data must be omitted",
    }
    (records / "recovery-1-failure.json").write_bytes(canonical_json_bytes(failure))
    (records / "recovery-1-exit.json").write_bytes(canonical_json_bytes({"exit_code": 1}))
    result = runner.inspect_original_case(
        SimpleNamespace(root=manager), "Q05", "register-intent_published-1", {}
    )
    assert result["worker_failure_observed"] is True
    assert result["negative_observation_available"] is False
    assert result["gate_evaluation"] == "NOT_EVALUATED"
    assert result["original_record_count"] == 2
    assert "error_message" not in result["original_records"][0]
    fact = next(
        item
        for item in result["original_records"]
        if item["original_source_path"].endswith("-failure.json")
    )
    assert fact["failure_locations"] == failure["failure_locations"]


def test_actual_git_status_preserves_original_index_bytes_and_mtime(tmp_path):
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("frozen contents\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "tracked.txt"], check=True)
    index = tmp_path / ".git/index"
    before = (index.read_bytes(), index.stat().st_mtime_ns)
    info = tracked.stat()
    os.utime(tracked, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
    runner.readonly_git_action(
        lambda: subprocess.run(
            ["git", "-C", str(tmp_path), "status", "--porcelain", "--untracked-files=all"],
            check=True,
            capture_output=True,
        )
    )
    assert (index.read_bytes(), index.stat().st_mtime_ns) == before


def test_intentional_crash_and_unattributed_global_failure_do_not_invent_recovery_failure(tmp_path):
    manager = tmp_path / "manager"
    records = (
        manager / "qualification-cases/Q05/register-intent_published-1/channel/process-records"
    )
    records.mkdir(parents=True)
    (records / "crash-exit.json").write_bytes(canonical_json_bytes({"exit_code": 73}))
    (records / "recovery-1-exit.json").write_bytes(canonical_json_bytes({"exit_code": 0}))
    (manager / "negative-staging-failure.json").write_bytes(
        canonical_json_bytes({"error_type": "ArtifactIntegrityError"})
    )
    result = runner.inspect_original_case(
        SimpleNamespace(root=manager), "Q05", "register-intent_published-1", {}
    )
    assert result["worker_failure_observed"] is False
    global_fact = next(
        item
        for item in result["original_records"]
        if item["original_source_path"] == "negative-staging-failure.json"
    )
    assert global_fact["record_scope"] == "DEPLOYMENT_WIDE_UNATTRIBUTED"


@pytest.mark.parametrize("damage", [None, "missing_record", "missing_exit_code", "worker_failure"])
def test_complete_worker_doctor_success_does_not_grant_a_qualification_gate(tmp_path, damage):
    manager = tmp_path / "manager"
    channel = manager / "qualification-cases/Q05/register-intent_published-1/channel"
    for folder in ("phase-inventories", "process-records"):
        (channel / folder).mkdir(parents=True)
    for phase in ("before", "crashed", "recovered", "after"):
        (channel / "phase-inventories" / f"{phase}.json").write_bytes(b"{}")
    for phase, code in (("crash", 73), ("recovery-1", 0), ("recovery-2", 0)):
        (channel / "process-records" / f"{phase}.json").write_bytes(b"{}")
        (channel / "process-records" / f"{phase}-exit.json").write_bytes(
            canonical_json_bytes({"exit_code": code})
        )
    observation = {
        "case": "register-intent_published-1",
        "case_family": "Q05",
        "deployment_profile_hash": "d" * 64,
        "campaign_hash": "b" * 64,
    }
    (channel / "negative-observation.json").write_bytes(canonical_json_bytes(observation))
    if damage == "missing_record":
        (channel / "process-records/recovery-2.json").unlink()
    elif damage == "missing_exit_code":
        (channel / "process-records/recovery-2-exit.json").write_bytes(b"{}")
    elif damage == "worker_failure":
        (channel / "process-records/recovery-2-exit.json").write_bytes(b'{"exit_code":1}')
    deployment = SimpleNamespace(
        root=manager,
        profile=SimpleNamespace(content_hash="d" * 64),
        bundle=SimpleNamespace(campaign=SimpleNamespace(content_hash="b" * 64)),
    )
    result = runner.inspect_original_case(deployment, "Q05", "register-intent_published-1", {})
    outcome = runner.original_case_outcome(result)
    assert outcome == (
        "NO_PROBLEM_OBSERVED"
        if damage is None
        else "PROBLEM_FOUND"
        if damage == "worker_failure"
        else "NOT_EVALUATED"
    )
    assert result["gate_evaluation"] == "NOT_EVALUATED"
    assert result["formal_frozen_verification"] == "NOT_PERFORMED"


def test_original_change_guard_rejects_native_mutation_without_repair(tmp_path):
    original = tmp_path / "original.json"
    original.write_bytes(b"{}")
    facts = {}
    with pytest.raises(HostedQualificationError, match="ORIGINAL_TREE_CHANGED"):
        runner.check_guarded_action((tmp_path,), lambda: original.write_bytes(b"[]"), facts, {})
    assert facts["changed_roots"] == [str(tmp_path)]
    assert original.read_bytes() == b"[]"


def _source_fixture(tmp_path: Path):
    bundle, manager = tmp_path / "bundle", tmp_path / "manager"
    bundle.mkdir()
    (manager / "evidence").mkdir(parents=True)
    profile = SimpleNamespace(content_hash="d" * 64, exact_commit="c" * 40, lock_hash="a" * 64)
    records = []
    files = []
    for path in ("selected.json", "unselected.json"):
        data = b"{}"
        (bundle / path).write_bytes(data)
        (manager / "evidence" / path).write_bytes(data)
        records.append(
            HostedManagerExportFile(
                bundle_path=path,
                source_path="evidence/" + path,
                sha256=sha256_bytes(data),
                size_bytes=len(data),
            )
        )
        files.append(
            HostedQualificationFile(
                logical_path=path, sha256=sha256_bytes(data), size_bytes=len(data)
            )
        )
    exported = HostedManagerExport(
        exact_commit=profile.exact_commit,
        deployment_profile_hash=profile.content_hash,
        files=tuple(records),
    )
    (manager / "evidence" / exported.content_hash).write_bytes(exported.canonical_bytes())
    manifest = SimpleNamespace(
        manager_export_hash=exported.content_hash,
        exact_commit=profile.exact_commit,
        lockfile_hash=profile.lock_hash,
        files=files,
    )
    deployment = SimpleNamespace(root=manager, profile=profile)
    return bundle, manager, exported, manifest, deployment


@pytest.mark.parametrize("damage", [None, "original", "bundle", "symlink", "retained_index"])
def test_selected_closure_binds_original_bytes_and_excludes_unchecked_records(tmp_path, damage):
    bundle, manager, exported, manifest, deployment = _source_fixture(tmp_path)
    if damage in {"original", "bundle"}:
        root = manager / "evidence" if damage == "original" else bundle
        (root / "selected.json").write_bytes(b"[]")
    elif damage == "symlink":
        original = manager / "evidence/selected.json"
        original.unlink()
        original.symlink_to(bundle / "selected.json")
    elif damage == "retained_index":
        (manager / "evidence" / exported.content_hash).write_bytes(b"{}")
    # Damage outside this declared closure must remain unchecked and unavailable.
    (manager / "evidence/unselected.json").write_bytes(b"altered outside selected scope")
    if damage is None:
        sources = bind_selected_sources(bundle, manifest, exported, deployment, {"selected.json"})
        assert set(sources.files) == {"selected.json"}
        assert "unselected.json" not in sources.files
    else:
        with pytest.raises((HostedQualificationError, ValueError, OSError, RuntimeError)):
            bind_selected_sources(bundle, manifest, exported, deployment, {"selected.json"})


def test_case_closure_includes_every_root_file_and_inventory_sidecar(tmp_path):
    inventory = HostedRawInventory(
        files=(HostedQualificationFile(logical_path="object.json", sha256="f" * 64, size_bytes=2),)
    )
    (tmp_path / "inventory.json").write_bytes(inventory.canonical_bytes())
    case = HostedQualificationCase(
        case_id="Q03",
        evidence_paths=("observation.json",),
        roots=(
            HostedQualificationRoot(
                name="before",
                logical_path="cases/Q03/before/authority",
                campaign_hash="b" * 64,
                raw_inventory_path="inventory.json",
            ),
        ),
    )
    assert selected_closure(tmp_path, case) == {
        "observation.json",
        "inventory.json",
        "cases/Q03/before/authority/object.json",
    }


def test_capacity_keeps_measured_full_denominator_separate_from_assumed_layout(tmp_path):
    _, _, exported, _, _ = _source_fixture(tmp_path)
    inventory = HostedRawInventory(
        files=(HostedQualificationFile(logical_path="object.json", sha256="f" * 64, size_bytes=2),)
    )
    result = index_capacity(exported, inventory, additional_authorities=3)
    assert result["actual_record_count"] == 2
    assert result["actual_encoded_bytes"] == len(exported.canonical_bytes())
    estimate = result["layout_estimate"]
    assert estimate["projected_total_record_count"] == 5
    assert estimate["scope"] == "SYNTHETIC_SIZE_ESTIMATE_ONLY_NOT_EVIDENCE"
    assert estimate["original_source_validation"] == "NOT_PERFORMED"
    assert estimate["projected_encoded_bytes"] > result["actual_encoded_bytes"]
    assert case_denominators()["captured_scenario_count"] == 106
    assert case_denominators()["case_count"] == 12


def test_diagnostic_output_refuses_original_or_existing_destination(tmp_path):
    protected = tmp_path / "original"
    protected.mkdir()
    payload = {"schema_version": "hosted-development-diagnostic/v1", "eligibility": "NOT_QUALIFIED"}
    with pytest.raises(HostedQualificationError):
        write_diagnostic(protected / "diagnostic.json", payload, (protected,))
    output = tmp_path / "diagnostic.json"
    write_diagnostic(output, payload, (protected,))
    with pytest.raises(HostedQualificationError):
        write_diagnostic(output, payload, (protected,))
    assert not (protected / "qualification-manifest.json").exists()
    assert not (protected / "verifier-result.json").exists()
