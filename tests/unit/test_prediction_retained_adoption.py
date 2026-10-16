"""Offline prior-report adoption boundaries with real immutable file/hash checks."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from test_discovery_offline_regression import design as design
from test_discovery_offline_regression import durable as durable
from test_discovery_recovery_regression import staged as staged
from test_prediction_native_contract import import_probe as import_probe
from test_prediction_native_contract import native_probe as native_probe

from quantos.application import discovery_prediction as prediction
from quantos.application import discovery_prediction_adoption as adoption
from quantos.artifacts.store import sha256_file
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.discovery_prediction import PredictionFileSource
from quantos.contracts.discovery_prediction_adoption import (
    PredictionEvidenceAdoption,
    RetainedPredictionEvidence,
)


def pin(path, value):
    raw = (
        value.canonical_bytes()
        if hasattr(value, "canonical_bytes")
        else canonical_json_bytes(value)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return PredictionFileSource(path=str(path), sha256=sha256_bytes(raw))


@pytest.fixture
def retained_probe(import_probe, staged, monkeypatch):
    p = import_probe
    root = staged.service.workspace / "prior-report"
    published = prediction.publish_prediction_evidence(
        p.source, p.profile, root / "evidence", base_authoring=p.base
    )
    evidence_hash = published.name.removeprefix("sha256-")
    # The verifier is a separate clean synthetic checkout with the actual locked
    # dependency bytes; it is not the original producer checkout or a new verdict.
    workspace = staged.service.workspace / "prior-verifier"
    workspace.mkdir()
    identity = json.loads((published / "verifier-identity.json").read_bytes())
    package = Path(prediction.__file__).parents[1]
    for item in identity["dependencies"]:
        target = workspace / "src/quantos" / item["logical_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(package / item["logical_path"], target)
    (workspace / "uv.lock").write_bytes(b"synthetic verifier lock\n")

    def git(*args):
        return subprocess.check_output(["git", "-C", str(workspace), *args], text=True).strip()

    git("init", "-q")
    git("add", ".")
    git(
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "fixture",
    )
    commit = git("rev-parse", "HEAD")
    control = root.parent / "prior-controls"
    control.mkdir()
    inventory = pin(control / "inventory.json", {"files": identity["dependencies"]})
    capsule = pin(
        control / "capsule.json",
        {
            "workspace": str(workspace),
            "actual_commit": commit,
            "lockfile_hash": sha256_file(workspace / "uv.lock"),
            "source_inventory_hash": inventory.sha256,
        },
    )
    request = json.loads(Path(p.source.request.path).read_bytes())
    cohort = pin(control / "cohort.json", {"requests": {"synthetic": request}})
    policy = pin(
        control / "policy.json",
        {
            "min_defined_fraction": p.profile.min_defined_fraction,
            "min_common_days": p.profile.min_common_days,
            "expected_test_dates": [d.isoformat() for d in p.profile.expected_dates],
        },
    )
    configuration = pin(
        control / "configuration.json",
        {
            "report_output": str(root),
            "expected_report_verifier_identity_hash": p.profile.verifier_identity_hash,
            "comparison_policy_authority": {"sha256": policy.sha256},
            "cohort_authority": {"sha256": cohort.sha256},
            "report_verifier_capsule": {"sha256": capsule.sha256},
            "report_verifier_inventory": {"sha256": inventory.sha256},
        },
    )
    operator = pin(control / "operator.json", {"synthetic": "offline operator identity"})
    prelaunch = pin(
        control / "prelaunch.json",
        {
            "argv": [
                operator.path,
                "compare",
                "--configuration",
                configuration.path,
                "--configuration-sha256",
                configuration.sha256,
                "--expected-operator-hash",
                operator.sha256,
            ]
        },
    )
    exit_ref = pin(control / "exit.json", {"actual_exit": 0})
    profile = pin(root / "profile.json", p.profile)
    report = {
        "schema_version": "b2-common-day-report/v1",
        "profile_hash": p.profile.content_hash,
        "comparison_policy_hash": policy.sha256,
        "sources": [
            {
                "status": "IMPORTED",
                "request_hash": p.source.request.sha256,
                "evidence_hash": evidence_hash,
                "source_hash": p.source.content_hash,
            }
        ],
    }
    report_hash = sha256_bytes(canonical_json_bytes(report))
    report_ref = pin(root / f"report-{report_hash}.json", report)
    record = PredictionEvidenceAdoption(
        prior_report=report_ref,
        prior_report_exit=exit_ref,
        prior_report_prelaunch=prelaunch,
        prior_operator=operator,
        prior_configuration=configuration,
        prior_profile=profile,
        prior_cohort=cohort,
        comparison_policy=policy,
        prior_verifier_capsule=capsule,
        prior_verifier_inventory=inventory,
        retained=(
            RetainedPredictionEvidence(
                execution_request_hash=p.source.request.sha256,
                evidence_root=str(published),
                manifest_hash=evidence_hash,
            ),
        ),
    )
    # Existing original_probe tests rehash signal/PIT/native/split sources. Reuse
    # that boundary here; this test exercises prior authority and closure adoption.
    checked = []

    def originals(source, evidence, prior, base):
        checked.append(source.content_hash)
        assert source == p.source and prior == p.profile and base == p.base
        assert evidence.original_execution_outcome == "EXECUTION_FAILED"

    monkeypatch.setattr(adoption, "_retained_originals", originals)
    monkeypatch.setattr(adoption, "verify_snapshot", lambda _: p.snapshot)
    monkeypatch.setattr(adoption, "verify_qlib_view", lambda _: p.view)
    return p, record, published, checked, workspace


def test_completed_prior_report_adopts_exact_bytes_without_new_scientific_status(retained_probe):
    p, record, published, checked, _ = retained_probe
    before = {path: path.read_bytes() for path in published.iterdir()}
    result = adoption.adopt_prediction_evidence(record, p.profile, base_authoring=p.base)
    evidence, manifest_hash = result[p.source.request.sha256]
    assert manifest_hash == record.retained[0].manifest_hash
    assert evidence.original_execution_outcome == "EXECUTION_FAILED"
    assert (
        evidence.original_research_result_hash is None
        and evidence.original_validation_report_hash is None
    )
    assert checked == [p.source.content_hash]
    assert before == {path: path.read_bytes() for path in before}


@pytest.mark.parametrize(
    "damage,reason",
    [
        ("exit", "PRIOR_VERIFIED_REPORT_NOT_COMPLETED"),
        ("policy", "ADOPTION_PROFILE_OR_POLICY_CHANGED"),
        ("file", "ADOPTION_EVIDENCE_FILE_SET_CHANGED"),
        ("verifier", "ADOPTION_PRIOR_VERIFIER_BYTES_CHANGED"),
    ],
)
def test_adoption_rejects_incomplete_prior_report_or_changed_closure(
    retained_probe, damage, reason
):
    p, record, published, _, workspace = retained_probe
    if damage == "exit":
        ref = pin(Path(record.prior_report_exit.path), {"actual_exit": 1})
        record = record.model_copy(update={"prior_report_exit": ref})
    elif damage == "policy":
        p.profile = p.profile.model_copy(update={"min_defined_fraction": 1.0})
    elif damage == "file":
        (published / "unexpected.json").write_bytes(b"{}")
    else:
        # Keep Git clean while the actual declared dependency bytes change.
        path = workspace / "src/quantos/application/discovery_prediction.py"
        path.write_bytes(path.read_bytes() + b"\n# changed verifier\n")
        subprocess.run(["git", "-C", str(workspace), "add", "."], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(workspace),
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-qm",
                "changed",
            ],
            check=True,
        )
        capsule = json.loads(Path(record.prior_verifier_capsule.path).read_bytes())
        capsule["actual_commit"] = subprocess.check_output(
            ["git", "-C", str(workspace), "rev-parse", "HEAD"], text=True
        ).strip()
        new_ref = pin(Path(record.prior_verifier_capsule.path), capsule)
        config = json.loads(Path(record.prior_configuration.path).read_bytes())
        config["report_verifier_capsule"]["sha256"] = new_ref.sha256
        config_ref = pin(Path(record.prior_configuration.path), config)
        prelaunch = json.loads(Path(record.prior_report_prelaunch.path).read_bytes())
        args = prelaunch["argv"]
        args[args.index("--configuration-sha256") + 1] = config_ref.sha256
        launch_ref = pin(Path(record.prior_report_prelaunch.path), prelaunch)
        record = record.model_copy(
            update={
                "prior_verifier_capsule": new_ref,
                "prior_configuration": config_ref,
                "prior_report_prelaunch": launch_ref,
            }
        )
    with pytest.raises(ValueError, match=reason):
        adoption.adopt_prediction_evidence(record, p.profile, base_authoring=p.base)
