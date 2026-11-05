"""Malformed source capture and memory-only auth tests; no model launch."""

import json
import os

import pytest
from test_hosted_launcher import _configuration, _events

from quantos.artifacts.store import ArtifactIntegrityError
from quantos.infrastructure.hosted_deployment import KnownValueGuard, private_memory_fd
from quantos.infrastructure.hosted_launcher import (
    extract_proposal,
    register_model_auth_memory,
    scan_cli_capture,
)


@pytest.mark.parametrize(
    "attack",
    [
        "thread_twice",
        "turn_twice",
        "completion_first",
        "item_before",
        "item_after",
        "item_scalar",
        "no_text",
        "bad_usage",
        "extra_usage",
        "negative_usage",
        "bool_usage",
        "scalar",
        "blank",
        "nonfinite",
        "model_type",
        "model_length",
        "model_conflict",
        "empty",
        "proposal_cap",
        "output_cap",
        "startup_id",
        "startup_extra",
    ],
)
def test_malformed_capture_cannot_become_a_proposal(attack):
    events = [json.loads(line) for line in _events("unmodified proposal").splitlines()]
    config = _configuration()
    if attack == "thread_twice":
        events.insert(1, events[0])
    elif attack == "turn_twice":
        events.insert(2, events[1])
    elif attack == "completion_first":
        events.insert(1, events[-1])
    elif attack == "item_before":
        events[1], events[2] = events[2], events[1]
    elif attack == "item_after":
        events[-1], events[-2] = events[-2], events[-1]
    elif attack == "item_scalar":
        events[2]["item"] = []
    elif attack == "no_text":
        events[2]["item"]["text"] = None
    elif attack == "bad_usage":
        events[-1]["usage"] = []
    elif attack == "extra_usage":
        events[-1]["usage"]["unexpected"] = 0
    elif attack == "negative_usage":
        events[-1]["usage"]["input_tokens"] = -1
    elif attack == "bool_usage":
        events[-1]["usage"]["input_tokens"] = True
    elif attack == "scalar":
        events[0] = []
    elif attack == "model_type":
        events[1]["model"] = 1
    elif attack == "model_length":
        events[1]["model"] = "x" * 201
    elif attack == "model_conflict":
        events[0]["model"] = "one"
        events[1]["model"] = "two"
    elif attack == "empty":
        events[2]["item"]["text"] = ""
    elif attack == "proposal_cap":
        config = config.model_copy(update={"proposal_byte_cap": 1})
    elif attack == "output_cap":
        config = config.model_copy(update={"output_byte_cap": 1})
    elif attack.startswith("startup"):
        item = {"id": "", "type": "error", "message": "notification"}
        if attack == "startup_extra":
            item.update(id="valid", extra="forbidden")
        events.insert(1, {"type": "item.completed", "item": item})
    output = b"\n".join(json.dumps(event).encode() for event in events)
    if attack == "blank":
        output = b"\n" + output
    elif attack == "nonfinite":
        output = output.replace(b'"thread.started"', b"NaN")
    with pytest.raises(ValueError):
        extract_proposal(output, config, guard=KnownValueGuard(()))


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"[",
        b'{"a":1,"a":2}',
        b'"short"',
        b"x" * 65537,
        b"[" * 18 + b'"NON_SECRET_INERT_CANARY_12345"' + b"]" * 18,
    ],
)
def test_auth_memory_must_have_bounded_unique_valid_values(raw):
    fd = private_memory_fd("synthetic-invalid-auth")
    try:
        os.write(fd, raw)
        with pytest.raises(ArtifactIntegrityError):
            register_model_auth_memory(fd, KnownValueGuard(()))
    finally:
        os.close(fd)


def test_plain_text_and_json_scalar_capture_are_scanned():
    scan_cli_capture(b'plain diagnostic\n[1,2]\n"ordinary text"\n', guard=KnownValueGuard(()))
    with pytest.raises(UnicodeError):
        scan_cli_capture(b"\xff", guard=KnownValueGuard(()))
