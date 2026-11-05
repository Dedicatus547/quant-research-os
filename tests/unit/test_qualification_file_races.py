"""Read-only inventory refuses aliases, bounded overflow and changing originals."""

import os

import pytest

from quantos.infrastructure import hosted_verification as module


@pytest.mark.parametrize("reader", ["bytes", "digest"])
@pytest.mark.parametrize("attack", ["grow", "replace_size", "hardlink", "fifo", "cap"])
def test_original_file_must_remain_regular_unique_bounded_and_unchanged(
    tmp_path, monkeypatch, reader, attack
):
    path = tmp_path / "original"
    if attack == "fifo":
        os.mkfifo(path)
    else:
        path.write_bytes(b"original bytes")
    if attack == "hardlink":
        os.link(path, tmp_path / "alias")
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    read = os.read
    changed = False

    def read_once(fd, size):
        nonlocal changed
        result = read(fd, size)
        if fd == descriptor and not changed and attack in {"grow", "replace_size"}:
            changed = True
            with path.open("ab" if attack == "grow" else "wb") as stream:
                stream.write(b"new")
        return result

    monkeypatch.setattr(module.os, "read", read_once)
    monkeypatch.setattr(
        module, "MAX_SINGLE_FILE_BYTES", 1 if attack == "cap" else 20 if attack == "grow" else 100
    )
    try:
        with pytest.raises(module.HostedQualificationError):
            if reader == "bytes":
                module._regular_bytes(
                    descriptor, max_bytes=1 if attack == "cap" else 20 if attack == "grow" else 100
                )
            else:
                module._regular_digest(descriptor)
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("attack", ["files", "bytes", "unsafe", "directories"])
def test_inventory_limits_include_all_files_and_empty_directories(tmp_path, monkeypatch, attack):
    (tmp_path / "empty").mkdir()
    (tmp_path / "one").write_bytes(b"abc")
    (tmp_path / "two").write_bytes(b"def")
    if attack == "files":
        monkeypatch.setattr(module, "MAX_BUNDLE_FILES", 1)
    elif attack == "bytes":
        monkeypatch.setattr(module, "MAX_INVENTORY_BYTES", 5)
    elif attack == "unsafe":
        os.mkfifo(tmp_path / "pipe")
    else:
        monkeypatch.setattr(module, "MAX_BUNDLE_FILES", 1)
    with pytest.raises(module.HostedQualificationError):
        if attack == "directories":
            module.directory_inventory(tmp_path)
        else:
            module.raw_inventory(tmp_path)
