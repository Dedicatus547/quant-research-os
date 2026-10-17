"""Package closeout is an offline control path with no subprocess launch."""

import json

from quantos.application import adaptive_package


def test_package_closeout_does_not_launch(tmp_path, monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(
        adaptive_package, "verified_package", lambda p: ({"task_hash": "a" * 64}, {})
    )
    monkeypatch.setattr(
        adaptive_package,
        "closeout_package",
        lambda p, m: seen.append((p, m)) or {"audit_output": "/retained/audit", "issues": []},
    )
    monkeypatch.setattr(
        adaptive_package.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no process allowed")),
    )
    assert adaptive_package.package_main(tmp_path, ["--closeout"]) == 0
    assert seen[0][0] == tmp_path
    assert json.loads(capsys.readouterr().out)["audit_output"] == "/retained/audit"


def test_package_selects_guard_for_exact_operator_operation(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from quantos.application import adaptive_closeout, adaptive_store
    from quantos.contracts.base import canonical_json_bytes, sha256_bytes

    task = tmp_path / "task"
    package = tmp_path / "package"
    operation = task / "operator" / "operation-0002"
    operation.mkdir(parents=True)
    operation.joinpath("process-exit.json").write_text("{}")
    command = ["python", "run", "--operator-operation", str(operation)]
    operation.joinpath("prelaunch.json").write_text(json.dumps({"argv": ["guard", "--", *command]}))
    evidence = tmp_path / "evidence"
    for name, op in [("old", task / "operator/operation-0001"), ("new", operation)]:
        guard = evidence / "storage-control" / name
        guard.mkdir(parents=True)
        args = ["python", "run", "--operator-operation", str(op)]
        guard.joinpath("prelaunch.json").write_bytes(
            canonical_json_bytes({"argv_hash": sha256_bytes(canonical_json_bytes(args))})
        )
        guard.joinpath("exit.json").write_text("{}")
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"evidence_root": str(evidence)}))
    monkeypatch.setattr(
        adaptive_store, "contract", lambda *a: SimpleNamespace(output_root=str(task))
    )
    seen = []
    monkeypatch.setattr(
        adaptive_closeout, "closeout_adaptive", lambda *a, **k: seen.append(k) or {"issues": []}
    )
    manifest = {"spec_path": str(package / "spec.json"), "storage_policy": {"path": str(policy)}}
    adaptive_package.closeout_package(package, manifest)
    assert seen[0]["exit_paths"]["guard"] == evidence / "storage-control/new/exit.json"
