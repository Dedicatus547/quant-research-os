"""Retained package pinning and operator command construction with synthetic launches."""

import json
import os
import socket
import sys
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace

import pytest

from quantos.application import adaptive_package as package
from quantos.artifacts.store import ArtifactIntegrityError, sha256_file
from quantos.contracts.base import canonical_json_bytes


@pytest.fixture
def retained(tmp_path, monkeypatch):
    repo = Path(__file__).resolve().parents[2]
    proposal = {"resources": {"growth_bytes": 1024}, "wall_seconds": 120}
    (tmp_path / "proposed-combination.json").write_bytes(canonical_json_bytes(proposal))
    pin = tmp_path / "input.json"
    pin.write_text('{"fixture":true}')
    policy = tmp_path / "policy.json"
    policy.write_bytes(
        canonical_json_bytes(
            {
                key: str(tmp_path)
                for key in ("evidence_root", "scratch_root", "host_volume", "vhd_file")
            }
        )
    )
    live = tmp_path / "task"
    live.mkdir()
    manifest = {
        "proposal_sha256": sha256_file(tmp_path / "proposed-combination.json"),
        "host": socket.gethostname(),
        "uid": os.getuid(),
        "workspace": str(repo),
        "commit": "a" * 40,
        "lockfile_sha256": "b" * 64,
        "pins": [{"path": str(pin), "sha256": sha256_file(pin)}],
        "distribution_versions": {"pydantic": version("pydantic")},
        "task_hash": "c" * 64,
        "output_root": str(live),
        "python": sys.executable,
        "pythonpath": str(repo / "src"),
        "spec_path": str(tmp_path / "spec.json"),
        "readonly_inputs": [str(pin)],
        "storage_policy": {"path": str(policy), "sha256": sha256_file(policy)},
    }
    state = SimpleNamespace(provenance=[], launches=[], code=0, issues=[], checks=[])
    monkeypatch.setattr(
        package, "verify_code_provenance", lambda root, **kw: state.provenance.append((root, kw))
    )
    monkeypatch.setattr(package, "StoragePolicy", lambda **kw: SimpleNamespace(**kw))
    monkeypatch.setattr(
        package,
        "StorageGuard",
        lambda _: SimpleNamespace(
            check=lambda n: state.checks.append(n) or {"synthetic_capacity": True}
        ),
    )
    monkeypatch.setattr(package, "require_bounded_bwrap", lambda: None)
    monkeypatch.setattr(
        package.subprocess,
        "run",
        lambda argv, **kw: (
            state.launches.append((argv, kw)) or SimpleNamespace(returncode=state.code)
        ),
    )
    monkeypatch.setattr(
        package,
        "closeout_package",
        lambda *args: {"audit_output": str(tmp_path / "audit"), "issues": state.issues},
    )

    def write():
        (tmp_path / "release-manifest.json").write_bytes(canonical_json_bytes(manifest))

    write()
    return tmp_path, manifest, state, write


def test_describe_and_verify_never_launch_or_create_authority(retained, capsys):
    root, manifest, state, _ = retained
    assert package.package_main(root, []) == 0
    assert json.loads(capsys.readouterr().out)["wall_seconds"] == 120
    assert not state.provenance
    assert package.package_main(root, ["--verify"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "OFFLINE_PINS_VERIFIED"
    assert state.provenance[0][1]["expected_commit_hash"] == manifest["commit"]
    assert not state.launches and not (root / "authorization.json").exists()
    with pytest.raises(ValueError, match="unsupported"):
        package.package_main(root, ["--unknown"])


@pytest.mark.parametrize(
    "attack,match",
    [
        ("proposal", "proposal differs"),
        ("host", "host differs"),
        ("uid", "host differs"),
        ("pin", "pinned original"),
        ("import", "source import"),
        ("version", "environment differs"),
    ],
)
def test_package_identity_tampering_is_rejected_before_launch(retained, attack, match):
    root, manifest, state, write = retained
    if attack == "proposal":
        (root / "proposed-combination.json").write_text("{}")
    elif attack in {"host", "uid"}:
        manifest[attack] = "different" if attack == "host" else -1
    elif attack == "pin":
        (root / "input.json").write_text("changed")
    elif attack == "import":
        manifest["workspace"] = str(root)
    else:
        manifest["distribution_versions"]["pydantic"] = "0.0.0"
    write()
    with pytest.raises(ArtifactIntegrityError, match=match):
        package.package_main(root, ["--run-approved"])
    assert not state.launches and not state.checks


@pytest.mark.parametrize(
    "attack",
    [
        "status",
        "task_hash",
        "manifest_sha256",
        "proposal_sha256",
        "egress_authorized",
        "live_run_authorized",
        "user_approval",
        "naive",
        "expired",
        "future",
        "overlong",
    ],
)
def test_authority_is_exact_bounded_and_not_inferred_from_package(retained, attack):
    root, _, state, _ = retained
    assert package.package_main(root, ["--authorize", "synthetic approval for unit fixture"]) == 0
    path = root / "authorization.json"
    authority = json.loads(path.read_bytes())
    now = datetime.now(UTC)
    if attack in {"egress_authorized", "live_run_authorized"}:
        authority[attack] = False
    elif attack == "user_approval":
        authority[attack] = ""
    elif attack == "naive":
        authority["approved_at"] = now.replace(tzinfo=None).isoformat()
    elif attack == "expired":
        authority["launch_not_after"] = (now - timedelta(seconds=1)).isoformat()
    elif attack == "future":
        authority["approved_at"] = (now + timedelta(hours=1)).isoformat()
    elif attack == "overlong":
        authority["launch_not_after"] = (now + timedelta(days=2)).isoformat()
    else:
        authority[attack] = "d" * 64
    path.write_bytes(canonical_json_bytes(authority))
    with pytest.raises(ArtifactIntegrityError, match="authority missing or expired"):
        package.package_main(root, ["--run-approved"])
    assert not state.launches and not state.checks


@pytest.mark.parametrize("code,issues,expected", [(0, [], 0), (7, [], 7), (0, ["incomplete"], 1)])
def test_bounded_launch_preserves_actual_exit_and_separate_audit(retained, code, issues, expected):
    root, manifest, state, _ = retained
    state.code, state.issues = code, issues
    package.package_main(root, ["--authorize", "synthetic approval for unit fixture"])
    assert package.package_main(root, ["--run-approved"]) == expected
    operation = Path(manifest["output_root"]) / "operator/operation-0001"
    prelaunch = json.loads((operation / "prelaunch.json").read_bytes())
    actual = json.loads((operation / "process-exit.json").read_bytes())
    assert actual["actual_exit"] == code
    assert actual["observed_by"] == "PARENT_SUBPROCESS_WAIT"
    assert prelaunch["wall_seconds"] == 120
    argv = state.launches[0][0]
    assert "--clearenv" in argv and "--ro-bind" in argv and "120s" in argv
    assert argv[-3:] == ["--operator-operation", str(operation), "--approved"]
    with pytest.raises(FileExistsError):
        package.package_main(root, ["--run-approved"])
    assert len(state.launches) == 1


@pytest.mark.parametrize("mode", ["--resume-approved", "--reconcile-approved"])
def test_recovery_uses_original_deadline_and_finite_operation_count(retained, mode):
    root, manifest, state, _ = retained
    package.package_main(root, ["--authorize", "synthetic approval for unit fixture"])
    live = Path(manifest["output_root"])
    activation = {
        "task_hash": manifest["task_hash"],
        "deadline": datetime.now(UTC) + timedelta(seconds=60),
    }
    (live / "activation.json").write_bytes(canonical_json_bytes(activation))
    assert package.package_main(root, [mode]) == 0
    saved = json.loads((live / "operator/operation-0001/prelaunch.json").read_bytes())
    assert 1 <= saved["wall_seconds"] <= (60 if mode == "--resume-approved" else 900)
    if mode == "--reconcile-approved":
        assert "reconcile" in state.launches[0][0] and "--approved" not in state.launches[0][0]
    for number in (2, 3):
        (live / "operator" / f"operation-{number:04d}").mkdir()
    with pytest.raises(ArtifactIntegrityError, match="operations exhausted"):
        package.package_main(root, [mode])
    assert len(state.launches) == 1
