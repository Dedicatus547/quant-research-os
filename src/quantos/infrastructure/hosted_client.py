"""Thin restricted Unix client; no admission, filesystem fallback or authority access."""

from __future__ import annotations

import os
import socket
import struct
from pathlib import Path
from typing import Literal, cast

from quantos.contracts.base import canonical_json_bytes
from quantos.contracts.hosted import strict_json_object
from quantos.contracts.hosted_deployment import (
    HostedChannelPolicy,
    HostedChannelRequest,
    HostedClientConfiguration,
)

CHANNEL_MAGIC = b"QHM1"


class HostedChannelError(RuntimeError):
    """Safe fixed error; contains no server exception or submitted material."""


def receive_exact(connection: socket.socket, length: int) -> bytes:
    result = bytearray()
    while len(result) < length:
        data = connection.recv(length - len(result))
        if not data:
            raise HostedChannelError("CHANNEL_INCOMPLETE_FRAME")
        result.extend(data)
    return bytes(result)


def consume_capability_fd(fd: int) -> bytes:
    """One private inherited descriptor; never accepts a capability value in argv/env."""
    if fd < 3:
        raise HostedChannelError("CAPABILITY_DESCRIPTOR_INVALID")
    try:
        os.set_blocking(fd, False)
        value = os.read(fd, 33)
    except OSError as error:
        raise HostedChannelError("CAPABILITY_DESCRIPTOR_INVALID") from error
    finally:
        os.close(fd)
    if len(value) != 32:
        raise HostedChannelError("CAPABILITY_DESCRIPTOR_INVALID")
    return value


class HostedUnixClient:
    def __init__(self, socket_path: Path, capability: bytes, policy: HostedChannelPolicy) -> None:
        if len(capability) != 32:
            raise HostedChannelError("CAPABILITY_LENGTH_INVALID")
        self._socket_path = socket_path
        self._capability = capability
        self.policy = policy

    def __repr__(self) -> str:
        return "HostedUnixClient(REDACTED)"

    @classmethod
    def from_configuration(
        cls,
        configuration: HostedClientConfiguration,
        capability_fd: int,
    ) -> HostedUnixClient:
        return cls(
            Path(configuration.socket_path),
            consume_capability_fd(capability_fd),
            configuration.policy,
        )

    def _call(
        self,
        operation: Literal["start", "pending", "status", "submit", "resume", "cancel"],
        target_hash: str,
        campaign_hash: str,
        body: bytes = b"",
    ) -> dict[str, object] | None:
        header = HostedChannelRequest(
            operation=operation, campaign_hash=campaign_hash, target_hash=target_hash
        ).canonical_bytes()
        if len(header) > self.policy.header_byte_cap:
            raise HostedChannelError("CHANNEL_HEADER_LIMIT")
        # An oversized local input is transmitted only as cap+1, letting the common
        # protocol publish an incomplete-prefix rejection and charge its allowance.
        body = body[: self.policy.response_byte_cap + 1]
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(self.policy.io_timeout_ms / 1000)
                connection.connect(str(self._socket_path))
                connection.sendall(CHANNEL_MAGIC + self._capability)
                connection.sendall(struct.pack("!I", len(header)) + header)
                connection.sendall(struct.pack("!I", len(body)) + body)
                connection.settimeout(self.policy.operation_reply_timeout_ms / 1000)
                size = struct.unpack("!I", receive_exact(connection, 4))[0]
                if size > self.policy.reply_byte_cap:
                    raise HostedChannelError("CHANNEL_REPLY_LIMIT")
                reply = strict_json_object(
                    receive_exact(connection, size), max_bytes=self.policy.reply_byte_cap
                )
        except (OSError, ValueError) as error:
            raise HostedChannelError("CHANNEL_UNAVAILABLE_OR_INVALID") from error
        if (
            set(reply) != {"schema_version", "ok", "error", "value"}
            or reply["schema_version"] != "hosted-channel-result/v1"
        ):
            raise HostedChannelError("CHANNEL_RESULT_INVALID")
        if reply["ok"] is not True:
            raise HostedChannelError("CHANNEL_REJECTED")
        value = reply["value"]
        if value is None:
            return None
        if not isinstance(value, dict):
            raise HostedChannelError("CHANNEL_RESULT_INVALID")
        return strict_json_object(
            canonical_json_bytes(cast(dict[str, object], value)),
            max_bytes=self.policy.reply_byte_cap,
        )

    def start(self, spec_hash: str, campaign_hash: str) -> dict[str, object] | None:
        return self._call("start", spec_hash, campaign_hash)

    def pending(self, campaign_hash: str) -> dict[str, object] | None:
        return self._call("pending", campaign_hash, campaign_hash)

    def status(self, campaign_hash: str) -> dict[str, object] | None:
        return self._call("status", campaign_hash, campaign_hash)

    def submit(
        self, request_hash: str, response_bytes: bytes, campaign_hash: str
    ) -> dict[str, object] | None:
        return self._call("submit", request_hash, campaign_hash, response_bytes)

    def resume(self, campaign_hash: str) -> dict[str, object] | None:
        return self._call("resume", campaign_hash, campaign_hash)

    def cancel(self, request_hash: str, campaign_hash: str) -> dict[str, object] | None:
        return self._call("cancel", request_hash, campaign_hash)
