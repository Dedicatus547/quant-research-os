"""Trusted launcher composition with mount/process doubles, never model evidence."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from test_hosted_launcher import _configuration, _events, _profile
from test_hosted_protocol import _fixture

from quantos.application.hosted_protocol import HostedProtocolService
from quantos.artifacts.store import ArtifactIntegrityError
from quantos.contracts.autonomous import AutonomousCandidateProposal
from quantos.contracts.base import canonical_json_bytes, sha256_bytes
from quantos.contracts.hosted_deployment import HostedMountObservation, HostedProjectionFact
from quantos.infrastructure import hosted_launcher as launcher
from quantos.infrastructure.hosted_deployment import (
    HostedNamespacePaths,
    KnownValueGuard,
    export_projection,
    install_inventory,
    source_seccomp_filter,
)
from quantos.infrastructure.hosted_store import HostedProtocolStore


@pytest.fixture(autouse=True)
def synthetic_storage_checkpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    # Process/mount doubles cannot establish a mounted production storage quota.
    monkeypatch.setattr(launcher, "storage_checkpoint", lambda *_: None)


@pytest.mark.parametrize(
    "damage",
    (
        None,
        "exit",
        "timeout",
        "output_limit",
        "os_error",
        "secret",
        "model_conflict",
        "missing_terminal",
        "fact_host",
        "projection",
        "filter",
    ),
)
def test_capture_keeps_rejected_source_records_and_closes_filter_without_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str | None
) -> None:
    fixture = _fixture(tmp_path / "functional")
    configuration = _configuration()
    paths = HostedNamespacePaths(
        **{
            name: tmp_path / name
            for name in (
                "install",
                "projection",
                "channel",
                "authority",
                "configuration",
                "provenance",
                "offline_inputs",
            )
        }
    )
    for path in vars(paths).values():
        path.mkdir()
    (paths.install / "codex").write_bytes(b"synthetic binary identity, never executed")
    installed = install_inventory(paths.install)
    initial_root = tmp_path / "initial"
    initial_root.mkdir()
    (initial_root / "schema").write_bytes(b"synthetic initial projection")
    initial = install_inventory(initial_root)
    fd, bpf = source_seccomp_filter()
    os.close(fd)
    profile = _profile(configuration, initial_inventory_hash=initial.content_hash).model_copy(
        update={
            "install_inventory_hash": installed.content_hash,
            "cli_binary_hash": installed.files[0].bytes_hash,
            "seccomp_bpf_hash": sha256_bytes(bpf),
        }
    )
    spec = fixture.spec.model_copy(update={"deployment_profile_hash": profile.content_hash})
    protocol = HostedProtocolService(
        HostedProtocolStore(tmp_path / "bound-protocol"),
        clock=fixture.clock,
        verify_inputs=lambda _: None,
    )
    protocol.register(spec)
    request = protocol.issue(
        spec.content_hash,
        fixture.request.business_request,
        projection_object_hashes=tuple(
            sorted(
                (
                    fixture.request.context_pack_hash,
                    fixture.request.proposal_schema_hash,
                )
            )
        ),
    )
    projection = export_projection(
        paths.projection,
        request,
        {
            request.context_pack_hash: request.business_request.context_pack.canonical_bytes(),
            request.proposal_schema_hash: canonical_json_bytes(
                AutonomousCandidateProposal.model_json_schema()
            ),
        },
        guard=KnownValueGuard(()),
    )
    store = launcher.TrustedLauncherEvidenceStore(tmp_path / "evidence", KnownValueGuard(()))
    fact = HostedProjectionFact(
        campaign_hash=request.campaign_hash,
        hosted_spec_hash=spec.content_hash,
        deployment_profile_hash=profile.content_hash,
        request_hash=request.content_hash,
        host_instance="fixture-host",
        initial_projection_inventory_hash=initial.content_hash,
        projection_inventory_hash=projection.content_hash,
    )
    fact_hash = store.publish_bytes(fact.canonical_bytes())
    subject = launcher.TrustedCodexLauncher(paths, profile, installed, configuration, store)
    output = _events(fixture.response.proposal_json)
    if damage == "secret":
        output = b'{"api_key":"SYNTHETIC_SCANNER_CANARY_ONLY"}\n'
    elif damage == "model_conflict":
        output = _events(fixture.response.proposal_json, model="conflicting-fixture-model")
    elif damage == "missing_terminal":
        output = output.rsplit(b"\n", 2)[0] + b"\n"
    observed_fds, calls = [], []

    def mount(*args, **kwargs):
        observed_fds.append(kwargs["seccomp_fd"])
        return HostedMountObservation(
            request_hash=request.content_hash,
            deployment_profile_hash=profile.content_hash,
            projection_inventory_hash=projection.content_hash,
            observed_uid=1000,
            observed_gid=1000,
        )

    def process(argv, *, pass_fds, configuration, input_bytes):
        calls.append(argv)
        assert pass_fds == tuple(observed_fds)
        assert input_bytes == launcher.hosted_prompt(request)
        assert "/install/codex" in argv
        assert argv[argv.index("--model") + 1] == configuration.model
        assert argv[argv.index("--sandbox") + 1] == "read-only"
        assert "/authority" not in argv
        if damage == "os_error":
            raise OSError("synthetic CLI launch failure")
        return (
            int(damage == "exit"),
            output,
            b"",
            "TIMED_OUT"
            if damage == "timeout"
            else "OUTPUT_LIMIT"
            if damage == "output_limit"
            else "CAPTURED",
        )

    monkeypatch.setattr(launcher, "probe_projection_mount", mount)
    monkeypatch.setattr(launcher, "_capture_process", process)
    if damage == "projection":
        (paths.projection / "untrusted").write_bytes(b"out of allowlist")
    elif damage == "filter":
        subject.profile = profile.model_copy(update={"seccomp_bpf_hash": "0" * 64})
    if damage in {"fact_host", "projection", "filter"}:
        with pytest.raises(ArtifactIntegrityError):
            subject.capture(
                request,
                spec,
                projection,
                initial,
                projection_fact_hash=fact_hash,
                host_instance="borrowed-host" if damage == "fact_host" else "fixture-host",
            )
        assert calls == []
    else:
        record, proposal = subject.capture(
            request,
            spec,
            projection,
            initial,
            projection_fact_hash=fact_hash,
            host_instance="fixture-host",
        )
        assert record.request_hash == request.content_hash
        assert record.prompt_hash == sha256_bytes(launcher.hosted_prompt(request))
        assert store.publish_record(record) == record.content_hash
        assert calls
        if damage is None:
            assert proposal == fixture.response.proposal_json.encode()
            assert record.outcome == "CAPTURED"
        else:
            assert proposal is None
            assert record.reason != "CLI_EVENT_CAPTURED"
            if damage in {"timeout", "output_limit"}:
                assert not record.raw_output_complete
    for descriptor in observed_fds:
        with pytest.raises(OSError):
            os.fstat(descriptor)
