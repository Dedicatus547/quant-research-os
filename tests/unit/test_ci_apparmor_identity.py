from pathlib import Path

from ci.apparmor.identity_v2 import collect as collector


def policy_tree(root: Path) -> Path:
    root.mkdir()
    (root / "revision").write_text("7\n")
    (root / "namespaces").mkdir()
    profile = root / "profiles" / "named.2"
    profile.mkdir(parents=True)
    (profile / "name").write_text("named\n")
    (profile / "mode").write_text("unconfined\n")
    (profile / "attach").write_text("<unknown>\n")
    return profile


def test_preserves_profile_field_association_and_missing_metadata(tmp_path):
    root = tmp_path / "policy"
    profile = policy_tree(root)
    child = profile / "profiles" / "child.3"
    child.mkdir(parents=True)
    for key, value in {
        "name": "named//child",
        "mode": "enforce",
        "attach": "/usr/bin/bwrap",
    }.items():
        (child / key).write_text(value + "\n")
    raw = root / "raw_data" / "6"
    raw.mkdir(parents=True)
    (raw / "abi").write_text("v9\n")
    (profile / "raw_abi").symlink_to("../../raw_data/6/abi")
    result = collector.collect(root)
    assert result["collection_complete"] is True
    assert result["profile_count"] == 2
    assert result["unknown_attachment_count"] == 1
    assert result["load_authorized"] is False
    assert result["attachment_review"] == "UNREVIEWED"
    first, second = result["profiles"]
    assert first["fields"]["name"]["value"] == "named\n"
    assert first["fields"]["attach"]["value"] == "<unknown>\n"
    assert first["loaded_metadata"]["sha256"]["status"] == "missing"
    assert first["loaded_metadata"]["raw_abi"]["value"] == "v9\n"
    assert first["links"]["raw_abi"]["target"] == "../../raw_data/6/abi"
    assert second["fields"]["name"]["value"] == "named//child\n"
    assert second["fields"]["attach"]["value"] == "/usr/bin/bwrap\n"


def test_missing_or_empty_required_field_remains_a_failed_collection(tmp_path):
    root = tmp_path / "policy"
    profile = policy_tree(root)
    (profile / "name").unlink()
    (profile / "attach").write_text("")
    result = collector.collect(root)
    assert result["collection_complete"] is False
    assert result["profiles"][0]["fields"]["name"]["status"] == "missing"
    assert result["profiles"][0]["fields"]["attach"]["status"] == "empty"
    assert result["load_authorized"] is False


def test_invalid_or_large_field_does_not_turn_into_no_attachment(tmp_path):
    root = tmp_path / "policy"
    profile = policy_tree(root)
    (profile / "attach").write_bytes(b"\xff")
    assert collector.collect(root)["profiles"][0]["fields"]["attach"]["status"] == "invalid_utf8"
    (profile / "attach").write_bytes(b"x" * (collector.MAX_FIELD_BYTES + 1))
    result = collector.collect(root)
    assert result["collection_complete"] is False
    assert result["profiles"][0]["fields"]["attach"]["status"] == "too_large"


def test_revision_change_keeps_records_but_refuses_complete_snapshot(tmp_path, monkeypatch):
    root = tmp_path / "policy"
    policy_tree(root)
    original = collector.field
    seen = 0

    def changing_field(path):
        nonlocal seen
        if path == root / "revision":
            seen += 1
            if seen == 2:
                path.write_text("8\n")
        return original(path)

    monkeypatch.setattr(collector, "field", changing_field)
    result = collector.collect(root)
    assert result["collection_complete"] is False
    assert result["profile_count"] == 1
    assert result["revision_before"] != result["revision_after"]
    assert result["load_authorized"] is False


def test_missing_tree_or_profile_symlink_is_not_silently_omitted(tmp_path):
    result = collector.collect(tmp_path / "absent")
    assert result["collection_complete"] is False
    assert result["profile_count"] == 0
    root = tmp_path / "policy"
    profile = policy_tree(root)
    (root / "profiles" / "unexpected").symlink_to(profile, target_is_directory=True)
    result = collector.collect(root)
    assert result["collection_complete"] is False
    assert any("unexpected profile entry" in error for error in result["errors"])


def test_profile_budget_failure_is_reported_without_approval(tmp_path, monkeypatch):
    root = tmp_path / "policy"
    policy_tree(root)
    monkeypatch.setattr(collector, "MAX_PROFILES", 0)
    result = collector.collect(root)
    assert result["collection_complete"] is False
    assert any("bounded collection limit" in error for error in result["errors"])
    assert result["load_authorized"] is False


def test_read_errors_and_additional_namespaces_remain_unresolved(tmp_path):
    root = tmp_path / "policy"
    profile = policy_tree(root)
    (root / "namespaces" / "other").mkdir()
    (profile / "mode").unlink()
    (profile / "mode").mkdir()
    result = collector.collect(root)
    assert result["collection_complete"] is False
    assert result["profiles"][0]["fields"]["mode"]["status"] == "error"
    assert result["other_namespaces"] == ["other"]
    assert result["load_authorized"] is False
