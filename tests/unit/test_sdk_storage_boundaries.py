"""SDK host quota and diagnostic checks using synthetic observations only."""

import base64
import json
from types import SimpleNamespace

import pytest

from quantos.application import sdk_producer as module
from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.base import sha256_bytes
from quantos.infrastructure import hosted_storage


@pytest.mark.parametrize(
    "attack",
    [
        "valid",
        "zero",
        "bool",
        "negative",
        "missing_env",
        "absent",
        "invalid",
        "array",
        "too_small",
        "boolean_reservation",
        "outside",
        "lease",
        "capacity",
    ],
)
def test_sdk_reservation_requires_actual_bound_lease_and_capacity(tmp_path, monkeypatch, attack):
    calls = []

    class Guard:
        def require_root(self, root):
            calls.append(("root", root))
            if attack == "outside":
                raise hosted_storage.StorageRejected("OUTSIDE")

        def require_lease(self):
            calls.append(("lease",))
            if attack == "lease":
                raise hosted_storage.StorageRejected("NO_LEASE")

        def check(self, value):
            calls.append(("capacity", value))
            if attack == "capacity":
                raise hosted_storage.StorageRejected("NO_CAPACITY")

    monkeypatch.setattr(hosted_storage, "configured_guard", Guard)
    monkeypatch.setenv(hosted_storage.LEASE_ENV, str(tmp_path))
    value = {"expected_new_bytes": 100}
    if attack == "array":
        value = []
    elif attack == "too_small":
        value["expected_new_bytes"] = 9
    elif attack == "boolean_reservation":
        value["expected_new_bytes"] = True
    if attack != "absent":
        (tmp_path / "prelaunch.json").write_text(
            "invalid" if attack == "invalid" else json.dumps(value)
        )
    if attack == "missing_env":
        monkeypatch.delenv(hosted_storage.LEASE_ENV)
    amount = {"zero": 0, "negative": -1, "bool": True}.get(attack, 10)
    if attack == "valid":
        module.require_sdk_storage_reservation((tmp_path,), amount)
        assert calls == [("root", tmp_path), ("lease",), ("capacity", 10)]
    else:
        with pytest.raises((hosted_storage.StorageRejected, ArtifactIntegrityError)):
            module.require_sdk_storage_reservation((tmp_path,), amount)
        if attack in {"zero", "negative", "bool"}:
            assert not calls


@pytest.mark.parametrize(
    "attack",
    [
        "absent",
        "schema",
        "streams",
        "entry",
        "name",
        "encoding_type",
        "encoding_cap",
        "encoding_invalid",
        "size",
        "hash",
        "unicode",
        "valid",
    ],
)
def test_host_diagnostics_cannot_substitute_or_escape_original_bytes(tmp_path, attack):
    payload = b"ordinary bounded diagnostic" if attack != "unicode" else b"\xff"
    item = {
        "file": "host-stdout.txt",
        "complete": True,
        "bytes": len(payload),
        "sha256": sha256_bytes(payload),
        "retention": "RETAINED",
        "base64": base64.b64encode(payload).decode(),
    }
    diagnostic = {
        "schema_version": "sdk-host-transport/v1",
        "phase": "SYNTHETIC",
        "exception_class": "OSError",
        "streams": [item, {"file": "host-stderr.txt", "retention": "UNAVAILABLE"}],
    }
    if attack == "schema":
        diagnostic["schema_version"] = "unknown"
    elif attack == "streams":
        diagnostic["streams"] = []
    elif attack == "entry":
        diagnostic["streams"][0] = []
    elif attack == "name":
        item["file"] = "../outside"
    elif attack == "encoding_type":
        item["base64"] = None
    elif attack == "encoding_cap":
        item["base64"] = "a" * 87385
    elif attack == "encoding_invalid":
        item["base64"] = "!"
    elif attack == "size":
        item["bytes"] = 999
    elif attack == "hash":
        item["sha256"] = "0" * 64
    execution = SimpleNamespace(
        attempts=[
            SimpleNamespace(
                qualification_observations={}
                if attack == "absent"
                else {"host_transport": diagnostic}
            )
        ]
    )
    if attack in {"absent", "valid", "unicode"}:
        result = module._persist_host_transport(tmp_path, execution)
        if attack == "absent":
            assert result is None
        else:
            assert result is not None
            if attack == "valid":
                assert (tmp_path / "host-stdout.txt").read_bytes() == payload
            else:
                assert not (tmp_path / "host-stdout.txt").exists()
    else:
        with pytest.raises(ArtifactIntegrityError):
            module._persist_host_transport(tmp_path, execution)
        assert not list(tmp_path.iterdir())
