"""Bounded canary capture checks; random values remain in process memory only."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import tempfile
from pathlib import Path
from urllib.parse import quote


def _string_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for child in value for item in _string_values(child)]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _string_values(child)]
    return []


def known_value_detected(data: bytes, known_value: bytes) -> bool:
    """Canary design check, not a qualified production credential scanner."""
    if len(data) > 65_536 or len(known_value) > 256:
        return True
    text = known_value.decode("ascii")
    encoded = (
        known_value,
        known_value.hex().encode(),
        known_value.hex().upper().encode(),
        base64.b64encode(known_value),
        base64.b64encode(known_value).rstrip(b"="),
        base64.urlsafe_b64encode(known_value),
        base64.urlsafe_b64encode(known_value).rstrip(b"="),
        quote(text, safe="").encode(),
        "".join(f"%{value:02X}" for value in known_value).encode(),
        "".join(f"%{value:02x}" for value in known_value).encode(),
    )
    if any(value in data for value in encoded):
        return True
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError):
        return False
    return any(known_value in item.encode("utf-8") for item in _string_values(parsed))


def main() -> None:
    canary = secrets.token_urlsafe(32).encode()
    cases = {
        "literal": canary,
        "base64": base64.b64encode(canary),
        "urlsafe_base64": base64.urlsafe_b64encode(canary),
        "base64_without_padding": base64.b64encode(canary).rstrip(b"="),
        "hex": canary.hex().encode(),
        "uppercase_hex": canary.hex().upper().encode(),
        "percent_encoded": quote(canary.decode(), safe="").encode(),
        "fully_percent_encoded": "".join(f"%{value:02X}" for value in canary).encode(),
        "lowercase_percent_encoded": "".join(f"%{value:02x}" for value in canary).encode(),
        "json_decoded_value": (
            '{"text":"' + "".join("\\u" + f"{value:04x}" for value in canary) + '"}'
        ).encode(),
    }
    facts = []
    with tempfile.TemporaryDirectory(prefix="hm06-value-canary-") as temporary:
        root = Path(temporary)
        for name, data in cases.items():
            rejected = known_value_detected(data, canary)
            # Publication has one entrance; nothing is written until checking succeeds.
            if not rejected:
                (root / name).write_bytes(data)
            facts.append({"case": name, "rejected_before_publish": rejected})
        count = len(list(root.iterdir()))
    safe_control = b'{"text":"NON_SENSITIVE_CONTROL"}'
    facts.append(
        {"case": "safe_control", "allowed": not known_value_detected(safe_control, canary)}
    )
    print(
        json.dumps(
            {
                "schema_version": "hm06-known-value-preflight/v1",
                "scope": "IN_MEMORY_CANARY_NOT_PRODUCTION_SCANNER_QUALIFICATION",
                "model": "gpt-6-sol",
                "reasoning_effort": "high",
                "attempt_count": 1,
                "usage": "unavailable",
                "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "canary_generation": "RANDOM_IN_MEMORY_NO_VALUE_OR_DIGEST_RETAINED",
                "rejected_case_files_written": count,
                "facts": facts,
                "qualification_granted": False,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
