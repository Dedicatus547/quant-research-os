"""Pure command fixtures: arguments do not establish namespace or quota execution."""

import json
from pathlib import Path

import pytest

from quantos.contracts.base import sha256_bytes
from quantos.infrastructure.hosted_deployment import (
    LEGACY_MOUNT_POLICY_BYTES,
    NAMESPACE_TMPFS_BYTES,
    PRE_STORAGE_MOUNT_POLICY_BYTES,
    STORAGE_MOUNT_POLICY_BYTES,
    HostedNamespacePaths,
    namespace_command,
)
from quantos.infrastructure.hosted_regression_runtime import ci_namespace_command


@pytest.fixture
def paths() -> HostedNamespacePaths:
    return HostedNamespacePaths(
        *(
            Path("/fixture") / name
            for name in (
                "install",
                "projection",
                "channel",
                "authority",
                "config",
                "provenance",
                "inputs",
            )
        )
    )


@pytest.mark.parametrize("role", ["service", "host"])
def test_v3_namespace_places_fixed_hard_cap_immediately_before_private_tmp(paths, role):
    argv = namespace_command(
        role,
        paths,
        ("/install/fixed-worker",),
        seccomp_fd=7 if role == "host" else None,
        mount_policy_hash=sha256_bytes(STORAGE_MOUNT_POLICY_BYTES),
    )
    index = argv.index("--size")
    assert argv[index : index + 4] == ("--size", "536870912", "--tmpfs", "/tmp")
    assert argv.count("--size") == 1 and argv[-1] == "/install/fixed-worker"
    policy = json.loads(STORAGE_MOUNT_POLICY_BYTES)
    assert policy["schema_version"] == "hosted-mount-policy/v3"
    assert policy["private_tmp_size_bytes"] == NAMESPACE_TMPFS_BYTES == 512 << 20
    assert policy["private_tmp_enforcement"] == "BWRAP_SIZE_BEFORE_TMPFS"


@pytest.mark.parametrize("role", ["service", "host"])
@pytest.mark.parametrize(
    "version,policy", [(1, LEGACY_MOUNT_POLICY_BYTES), (2, PRE_STORAGE_MOUNT_POLICY_BYTES)]
)
def test_retained_legacy_mount_policies_do_not_acquire_new_quota_claims(
    paths, role, version, policy
):
    argv = namespace_command(
        role,
        paths,
        ("/install/fixed-worker",),
        seccomp_fd=7 if role == "host" else None,
        mount_policy_hash=sha256_bytes(policy),
    )
    assert "--size" not in argv
    assert any(argv[index : index + 2] == ("--tmpfs", "/tmp") for index in range(len(argv) - 1))
    value = json.loads(policy)
    assert value["schema_version"] == f"hosted-mount-policy/v{version}"
    assert "private_tmp_size_bytes" not in value
    if role == "service":
        assert ("--symlink" in argv) is (version == 2)


def test_ci_namespace_uses_the_same_fixed_private_tmp_cap():
    python = Path("/fixture/ci/.venv/bin/python3.11")
    command = (str(python), "-B", "-m", "pytest", "frozen-tests")
    argv = ci_namespace_command(
        python, Path("/fixture/source"), Path("/fixture/ci"), {"PATH": "/usr/bin:/bin"}, command
    )
    index = argv.index("--size")
    assert argv[index : index + 4] == ("--size", "536870912", "--tmpfs", "/run")
    assert argv.count("--size") == 1
    assert "--unshare-pid" in argv and "--unshare-net" in argv
    assert json.loads(argv[-1]) == list(command)
