import base64
import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from ci.apparmor.provenance_v3 import binding, capture


def field(value):
    raw = value.encode()
    return {
        "status": "ok",
        "value": value,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def inventory(offset=0):
    directories = [
        f"profiles/Qt.{1 + offset}",
        f"profiles/parent.{2 + offset}",
        f"profiles/parent.{2 + offset}/profiles/Qt.{3 + offset}",
    ]
    records = []
    for index, directory in enumerate(directories):
        group = (7 if index == 0 else 8) + offset
        prefix = "../" * len(directory.split("/")) + f"raw_data/{group}/"
        records.append(
            {
                "directory": directory,
                "fields": {
                    "name": field("QtWebEngineProcess\n" if index != 1 else "parent\n"),
                    "mode": field("enforce\n"),
                    "attach": field("<unknown>\n"),
                },
                "loaded_metadata": {
                    "sha256": field(str(index + 1) * 64 + "\n"),
                    "raw_sha256": field(("a" if index == 0 else "b") * 64 + "\n"),
                    "raw_abi": field("v5\n"),
                },
                "links": {
                    key: {"status": "ok", "target": prefix + name}
                    for key, name in [
                        ("raw_data", "raw_data"),
                        ("raw_sha256", "sha256"),
                        ("raw_abi", "abi"),
                    ]
                },
            }
        )
    return {
        "schema": "quantos-apparmor-identity-v2",
        "policy_root": "/sys/kernel/security/apparmor/policy",
        "revision_before": field(f"{110 + offset}\n"),
        "revision_after": field(f"{110 + offset}\n"),
        "profiles": records,
        "profile_count": 3,
        "unknown_attachment_count": 3,
        "other_namespaces": [],
        "errors": [],
        "collection_complete": True,
        "attachment_review": "UNREVIEWED",
        "load_authorized": False,
    }


def encoded(value):
    return json.dumps(value).encode()


def test_full_lineage_and_raw_group_relation_survive_id_changes():
    first = binding.inventory_binding(encoded(inventory()))
    second = binding.inventory_binding(encoded(inventory(30)))
    assert first == second
    names = [record["lineage"] for record in first["profiles"]]
    assert ["QtWebEngineProcess"] in names
    assert ["parent", "QtWebEngineProcess"] in names
    assert len(names) == 3
    assert first["unknown_attachment_count"] == 3


@pytest.mark.parametrize("key,value", [("mode", "complain\n"), ("attach", "/usr/bin/bwrap\n")])
def test_mode_or_attachment_is_preserved_as_drift(key, value):
    changed = inventory()
    changed["profiles"][0]["fields"][key] = field(value)
    if key == "attach":
        changed["unknown_attachment_count"] -= 1
    assert binding.inventory_binding(encoded(changed)) != binding.inventory_binding(
        encoded(inventory())
    )


@pytest.mark.parametrize(
    "key,value", [("sha256", "c" * 64 + "\n"), ("raw_sha256", "c" * 64 + "\n"), ("raw_abi", "v6\n")]
)
def test_loaded_hash_and_abi_are_preserved_as_drift(key, value):
    changed = inventory()
    changed["profiles"][0]["loaded_metadata"][key] = field(value)
    assert binding.inventory_binding(encoded(changed)) != binding.inventory_binding(
        encoded(inventory())
    )


@pytest.mark.parametrize(
    "change",
    [
        "parent_missing",
        "same_lineage",
        "broken_link",
        "wrong_link_field",
        "field_missing",
        "bad_hash",
        "extra_namespace",
        "unstable_revision",
        "inconsistent_raw_group",
    ],
)
def test_inventory_rejections(change):
    value = inventory()
    if change == "parent_missing":
        value["profiles"][2]["directory"] = "profiles/absent.99/profiles/Qt.3"
    if change == "same_lineage":
        value["profiles"][1]["fields"]["name"] = field("QtWebEngineProcess\n")
    if change == "broken_link":
        value["profiles"][0]["links"]["raw_data"]["target"] = "/etc/shadow"
    if change == "wrong_link_field":
        value["profiles"][0]["links"]["raw_abi"]["target"] = "../../raw_data/7/sha256"
    if change == "field_missing":
        del value["profiles"][0]["loaded_metadata"]["sha256"]
    if change == "bad_hash":
        value["profiles"][0]["fields"]["attach"]["sha256"] = "0" * 64
    if change == "extra_namespace":
        value["other_namespaces"] = ["other"]
    if change == "unstable_revision":
        value["revision_after"] = field("111\n")
    if change == "inconsistent_raw_group":
        value["profiles"][2]["loaded_metadata"]["raw_sha256"] = field("e" * 64 + "\n")
    with pytest.raises((ValueError, KeyError)):
        binding.inventory_binding(encoded(value))


def write(root, path, raw=b"fixture\n"):
    file = root / path.lstrip("/")
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(raw)
    return file


def source_packet(root, monkeypatch, offset=0):
    for path in [
        *capture.CONFIG,
        "/etc/apparmor.d/named",
        "/sys/kernel/security/apparmor/features/policy/versions",
        *("/sys/kernel/security/apparmor/" + name for name in capture.NAMESPACE),
        "/usr/sbin/apparmor_parser",
        "/usr/bin/bwrap",
    ]:
        write(root, path)
    monkeypatch.setattr(
        capture,
        "command",
        lambda argv: {
            "argv": list(argv),
            "status": "ok",
            "exit": 0,
            "stdout": "apparmor: /etc/apparmor.d/named\n",
            "stderr": "",
        },
    )
    plan = {
        "schema": "quantos-apparmor-source-plan-v3",
        "files": [{"path": "/etc/apparmor.d/named"}],
        "directories": [],
        "profiles": [],
    }
    for name, value in [
        (".ns_name", b"root\n"),
        (".ns_level", b"0\n"),
        (".ns_stacked", b"no\n"),
        (".stacked", b"no\n"),
    ]:
        write(root, "/sys/kernel/security/apparmor/" + name, value)
    original = inventory(offset)
    report = capture.capture(
        encoded(original), plan, capture.Reader(root), image_version="20261012.334.1"
    )
    report["revision_after_sources"] = copy.deepcopy(original["revision_after"])
    report["tool_sources"] = {"test-fixture": "explicitly synthetic"}
    return report


def test_source_capture_keeps_actual_bytes_and_original_inventory(tmp_path, monkeypatch):
    report = source_packet(tmp_path, monkeypatch)
    assert report["collection_complete"] is True
    assert base64.b64decode(report["inventory_raw_base64"]) == encoded(inventory())
    assert base64.b64decode(report["sources"][0]["base64"]) == b"fixture\n"
    assert report["source_to_loaded_correspondence"] == "UNRESOLVED"
    assert report["load_authorized"] is False
    result = binding.compare(encoded(report), encoded(report))
    assert result["content_equal"] is True
    assert result["load_authorized"] is False
    assert result["decision"] == "UNRESOLVED_SOURCE_REVIEW_REQUIRED"


def test_cross_job_candidate_with_sources_is_equal_but_never_approval(tmp_path, monkeypatch):
    first = source_packet(tmp_path, monkeypatch)
    second = source_packet(tmp_path, monkeypatch, 30)
    result = binding.compare(encoded(first), encoded(second))
    assert result["content_equal"] is True
    proposed = result["left"]["candidate_content_sha256"]
    assert (
        binding.compare(encoded(first), encoded(second), proposed)["matches_explicit_digest"]
        is True
    )
    assert binding.compare(encoded(first), encoded(second), proposed)["load_authorized"] is False


@pytest.mark.parametrize(
    "part", ["source", "parser", "namespace", "image", "config", "features", "package"]
)
def test_source_and_runtime_drift_prevents_candidate_match(tmp_path, monkeypatch, part):
    first = source_packet(tmp_path, monkeypatch)
    changed = copy.deepcopy(first)
    if part in ("source", "namespace", "config", "features"):
        group = {
            "source": "sources",
            "namespace": "namespace",
            "config": "settings",
            "features": "features",
        }[part]
        record = changed[group][1 if part == "namespace" else 0]
        record.update(
            base64=base64.b64encode(b"changed\n").decode(),
            bytes=8,
            sha256=hashlib.sha256(b"changed\n").hexdigest(),
        )
    if part == "parser":
        changed["binaries"][0]["sha256"] = "a" * 64
    if part == "image":
        changed["runtime"]["image"] = "other-image"
    if part == "package":
        changed["packages"]["versions"]["stdout"] = "different version"
    if part == "namespace":
        with pytest.raises(ValueError, match="namespace/stacking"):
            binding.compare(encoded(first), encoded(changed))
    else:
        assert binding.compare(encoded(first), encoded(changed))["content_equal"] is False


def test_missing_and_forged_sources_remain_rejected(tmp_path, monkeypatch):
    original = source_packet(tmp_path, monkeypatch)
    incomplete = copy.deepcopy(original)
    incomplete.update(collection_complete=False, errors=["source missing"])
    result = binding.compare(
        encoded(incomplete),
        encoded(incomplete),
        binding.candidate(encoded(incomplete))["candidate_content_sha256"],
    )
    assert result["decision"] == "REJECTED_INCOMPLETE_CAPTURE"
    assert result["matches_explicit_digest"] is False
    forged = copy.deepcopy(original)
    forged["sources"][0]["sha256"] = "f" * 64
    with pytest.raises(ValueError, match="source bytes/hash"):
        binding.candidate(encoded(forged))
    forged = copy.deepcopy(original)
    forged["source_to_loaded_correspondence"] = "VERIFIED"
    with pytest.raises(ValueError, match="cannot assert verified"):
        binding.candidate(encoded(forged))


def test_reader_refuses_file_parent_symlinks_and_nonregular_inputs(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    secret = write(tmp_path, "outside", b"do not read")
    (root / "file").symlink_to(secret)
    (root / "directory").symlink_to(tmp_path, target_is_directory=True)
    os.mkfifo(root / "pipe")
    reader = capture.Reader(root)
    assert reader.read("/file")["status"] == "error"
    assert reader.read("/directory/outside")["status"] == "error"
    assert reader.read("/pipe")["status"] == "error"
    assert reader.total == 0
    assert reader.read("/missing")["status"] == "missing"


def test_source_limits_and_permission_failures_are_retained(tmp_path, monkeypatch):
    write(tmp_path, "file", b"123456")
    monkeypatch.setattr(capture, "MAX_TOTAL_BYTES", 5)
    reader = capture.Reader(tmp_path)
    assert reader.read("/file")["status"] == "error"
    assert reader.read("/file")["status"] == "limit"
    assert reader.total == 6
    monkeypatch.setattr(
        capture.Reader,
        "open",
        lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("synthetic denied")),
    )
    assert capture.Reader(tmp_path).read("/file")["status"] == "error"


def test_unsafe_source_plan_is_rejected_before_any_read(tmp_path):
    with pytest.raises(ValueError, match="outside policy root"):
        capture.capture(
            encoded(inventory()),
            {
                "schema": "quantos-apparmor-source-plan-v3",
                "files": [{"path": "/etc/shadow"}],
                "directories": [],
            },
            capture.Reader(tmp_path),
        )


def test_binding_cli_refuses_even_an_identical_candidate(tmp_path, monkeypatch):
    report = source_packet(tmp_path, monkeypatch)
    file = tmp_path / "capture.json"
    file.write_bytes(encoded(report))
    script = Path(binding.__file__).resolve()
    proc = subprocess.run(
        [sys.executable, "-I", "-B", str(script), str(file), str(file)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    assert json.loads(proc.stdout)["load_authorized"] is False


def test_capture_cli_wrong_hash_stops_before_source_access(tmp_path):
    file = tmp_path / "inventory.json"
    file.write_bytes(encoded(inventory()))
    proc = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(Path(capture.__file__).resolve()),
            "--inventory",
            str(file),
            "--inventory-sha256",
            "0" * 64,
            "--image-version",
            "synthetic",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    assert "inventory size/hash mismatch" in proc.stderr
    assert proc.stdout == ""


def test_directory_budget_and_missing_namespace_refuse(tmp_path, monkeypatch):
    report = source_packet(tmp_path, monkeypatch)
    del report["namespace"][0]
    with pytest.raises(ValueError, match="incomplete namespace"):
        binding.candidate(encoded(report))
    directory = tmp_path / "bounded"
    directory.mkdir()
    for index in range(3):
        (directory / str(index)).write_text("x")
    monkeypatch.setattr(capture, "MAX_FILES", 2)
    paths, errors = capture.Reader(tmp_path).tree("/bounded")
    assert paths == []
    assert errors


def test_command_scratch_output_is_capped_without_success():
    result = capture.command(
        (
            sys.executable,
            "-I",
            "-B",
            "-c",
            'import os; os.write(1,b"x"*300000); os.write(1,b"x"*300000)',
        )
    )
    assert result["status"] != "ok"
    assert result["exit"] != 0
    assert len(result.get("stdout", "").encode()) <= 262144
    assert len(result.get("stderr", "").encode()) <= 8192
