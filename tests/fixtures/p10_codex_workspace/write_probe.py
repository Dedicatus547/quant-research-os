"""Attempt one deterministic write so P10 can observe read-only sandbox enforcement."""

from pathlib import Path

Path("should-not-exist").write_bytes(b"p10-sandbox-probe")
