"""Actual native fsync exits are forensic facts, never canonical authority."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import pytest
from test_autonomous_campaign import _inputs
from test_hosted_campaign import _spec

from quantos.application.hosted_protocol import HostedProtocolService
from quantos.infrastructure import hosted_atomic_forensics as forensic
from quantos.infrastructure.hosted_store import HostedProtocolStore
from quantos.infrastructure.hosted_verification import (
    HostedQualificationError,
    raw_inventory,
    read_relative,
)


def _crash(root: Path, spec, domain: str, window: str) -> None:
    pid = os.fork()
    if pid == 0:

        def stop(point: str) -> None:
            if point == f"{domain}_{window}":
                os._exit(73)

        service = HostedProtocolService(
            HostedProtocolStore(root / "protocol", fault_hook=stop),
            verify_inputs=lambda _: None,
            clock=lambda: spec.started_at,
        )
        service.register(spec)
        service.start(spec.content_hash)
        os._exit(1)
    observed, status = os.waitpid(pid, 0)
    assert observed == pid and os.waitstatus_to_exitcode(status) == 73


@pytest.mark.parametrize("domain", ("spec", "journal", "object"))
@pytest.mark.parametrize("window", forensic.ATOMIC_WINDOWS)
def test_known_native_publication_aliases_are_observed_without_repair(
    tmp_path: Path, domain: str, window: str
) -> None:
    spec = _spec(_inputs(tmp_path / "inputs"))
    authority = tmp_path / "authority"
    _crash(authority, spec, domain, window)
    target, expected = forensic.native_registration_publication(spec, domain)
    facts = forensic.atomic_forensic_inventory(
        authority, target_path=target, expected_bytes=expected, window=window
    )
    assert facts.evidence_kind == "FORENSIC_ONLY_NOT_CANONICAL_AUTHORITY"
    assert facts.qualification_eligibility == "NOT_QUALIFIED"
    assert len(tuple(file for file in facts.files if file.link_count == 2)) == (
        2 if window == "file_linked" else 0
    )
    assert (
        forensic.atomic_forensic_inventory(
            authority, target_path=target, expected_bytes=expected, window=window
        )
        == facts
    )
    if window == "file_linked":
        # The canonical primitives have not acquired this finite forensic exception.
        with pytest.raises(HostedQualificationError):
            raw_inventory(authority)
        with pytest.raises(HostedQualificationError):
            read_relative(authority, target)
    with pytest.raises(HostedQualificationError, match="publication bytes differ"):
        forensic.atomic_forensic_inventory(
            authority, target_path=target, expected_bytes=expected + b"\n", window=window
        )
    assert (
        forensic.atomic_forensic_inventory(
            authority, target_path=target, expected_bytes=expected, window=window
        )
        == facts
    )


@pytest.mark.parametrize(
    "damage",
    (
        "third_inside_alias",
        "outside_alias",
        "symlink",
        "fifo",
        "extra_temporary",
        "wrong_temporary_name",
        "different_inode",
    ),
)
def test_forensic_pair_exception_cannot_authorize_unrelated_aliases_or_objects(
    tmp_path: Path, damage: str
) -> None:
    spec = _spec(_inputs(tmp_path / "inputs"))
    authority = tmp_path / "authority"
    window = "file_linked"
    _crash(authority, spec, "spec", window)
    target, expected = forensic.native_registration_publication(spec, "spec")
    source = authority / target
    temporary = next(source.parent.glob(".publish-*"))
    if damage == "third_inside_alias":
        os.link(source, authority / "third.json")
    elif damage == "outside_alias":
        os.link(source, tmp_path / "outside.json")
    elif damage == "symlink":
        (authority / "alias").symlink_to(source)
    elif damage == "fifo":
        os.mkfifo(authority / "fifo")
    elif damage == "extra_temporary":
        (source.parent / (".publish-" + "a" * 32)).write_bytes(expected)
    elif damage == "wrong_temporary_name":
        temporary.rename(source.parent / ".publish-invalid")
    else:
        temporary.unlink()
        temporary.write_bytes(expected)
    with pytest.raises(HostedQualificationError):
        forensic.atomic_forensic_inventory(
            authority, target_path=target, expected_bytes=expected, window=window
        )


def test_forensic_limits_reject_before_accepting_a_partial_tree(
    tmp_path: Path, monkeypatch
) -> None:
    spec = _spec(_inputs(tmp_path / "inputs"))
    authority = tmp_path / "authority"
    _crash(authority, spec, "spec", "file_published")
    target, expected = forensic.native_registration_publication(spec, "spec")
    for cap, value, message in (
        ("FORENSIC_ENTRY_CAP", 1, "entry cap"),
        ("FORENSIC_FILE_CAP", len(expected) - 1, "oversized"),
        ("FORENSIC_TOTAL_CAP", len(expected) - 1, "aggregate cap"),
    ):
        with monkeypatch.context() as limited:
            limited.setattr(forensic, cap, value)
            with pytest.raises((ValueError, HostedQualificationError), match=message):
                forensic.atomic_forensic_inventory(
                    authority, target_path=target, expected_bytes=expected, window="file_published"
                )


def test_entry_limit_stops_enumeration_before_materializing_a_large_directory(
    tmp_path: Path, monkeypatch
) -> None:
    for number in range(65):
        (tmp_path / f"{number:03d}.json").write_bytes(b"{}")
    consumed: list[str] = []
    original = os.scandir

    @contextmanager
    def bounded_observer(descriptor):
        with original(descriptor) as iterator:

            def observed():
                for item in iterator:
                    consumed.append(item.name)
                    yield item

            yield observed()

    monkeypatch.setattr(forensic, "FORENSIC_ENTRY_CAP", 4)
    monkeypatch.setattr(forensic.os, "scandir", bounded_observer)
    with pytest.raises(HostedQualificationError, match="entry cap"):
        forensic.atomic_forensic_inventory(
            tmp_path, target_path="000.json", expected_bytes=b"{}", window="file_published"
        )
    assert len(consumed) <= 5


def test_aggregate_limit_rejects_before_reading_the_excess_file(
    tmp_path: Path, monkeypatch
) -> None:
    directory = tmp_path / "publication"
    directory.mkdir()
    (directory / "known.json").write_bytes(b"frozen")
    reads: list[int] = []
    original = os.read

    def observed(descriptor: int, size: int) -> bytes:
        reads.append(size)
        return original(descriptor, size)

    monkeypatch.setattr(forensic, "FORENSIC_TOTAL_CAP", 5)
    monkeypatch.setattr(forensic.os, "read", observed)
    with pytest.raises(HostedQualificationError, match="aggregate cap"):
        forensic.atomic_forensic_inventory(
            tmp_path,
            target_path="publication/known.json",
            expected_bytes=b"frozen",
            window="file_published",
        )
    assert reads == []


@pytest.mark.parametrize("window", forensic.ATOMIC_WINDOWS)
def test_forensic_copy_keeps_original_links_and_retains_distinct_physical_facts(
    tmp_path: Path, window: str
) -> None:
    from quantos.artifacts.store import ArtifactIntegrityError
    from quantos.infrastructure.hosted_atomic_snapshot import (
        forensic_byte_view,
        snapshot_atomic_authority,
    )

    spec = _spec(_inputs(tmp_path / "inputs"))
    authority, channel = tmp_path / "authority", tmp_path / "channel"
    channel.mkdir()
    _crash(authority, spec, "spec", window)
    target, expected = forensic.native_registration_publication(spec, "spec")
    before = forensic.atomic_forensic_inventory(
        authority, target_path=target, expected_bytes=expected, window=window
    )
    facts = snapshot_atomic_authority(
        "crashed", authority, channel, target_path=target, expected_bytes=expected, window=window
    )
    copied = channel / "snapshots/crashed/authority"
    assert facts == before
    assert raw_inventory(copied) == forensic_byte_view(before)
    assert all(path.stat().st_nlink == 1 for path in copied.rglob("*") if path.is_file())
    assert before == forensic.atomic_forensic_inventory(
        authority, target_path=target, expected_bytes=expected, window=window
    )
    assert (channel / "phase-forensics/crashed.json").read_bytes() == before.canonical_bytes()
    with pytest.raises(ArtifactIntegrityError, match="fresh retained root"):
        snapshot_atomic_authority(
            "crashed",
            authority,
            channel,
            target_path=target,
            expected_bytes=expected,
            window=window,
        )


@pytest.mark.parametrize("overlap", ("same", "inside", "parent", "sidecar_symlink"))
def test_forensic_copy_rejects_overlapping_outputs_before_any_mutation(
    tmp_path: Path, overlap: str
) -> None:
    from quantos.artifacts.store import ArtifactIntegrityError
    from quantos.infrastructure.hosted_atomic_snapshot import snapshot_atomic_authority

    spec = _spec(_inputs(tmp_path / "inputs"))
    authority = tmp_path / "authority"
    _crash(authority, spec, "spec", "file_published")
    channel = (
        authority
        if overlap == "same"
        else authority / "inside"
        if overlap == "inside"
        else tmp_path
        if overlap == "parent"
        else tmp_path / "channel"
    )
    channel.mkdir(exist_ok=True)
    if overlap == "sidecar_symlink":
        (channel / "phase-forensics").symlink_to(authority, target_is_directory=True)
    target, expected = forensic.native_registration_publication(spec, "spec")
    before = forensic.atomic_forensic_inventory(
        authority, target_path=target, expected_bytes=expected, window="file_published"
    )
    with pytest.raises(ArtifactIntegrityError):
        snapshot_atomic_authority(
            "crashed",
            authority,
            channel,
            target_path=target,
            expected_bytes=expected,
            window="file_published",
        )
    assert before == forensic.atomic_forensic_inventory(
        authority, target_path=target, expected_bytes=expected, window="file_published"
    )
    assert not (channel / "snapshots").exists()
