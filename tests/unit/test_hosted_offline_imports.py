"""Clean-process offline imports must not load vendor or LLM transports."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "scenario", ["offline_modules", "injected_client", "invalid_token", "acquisition_stub"]
)
def test_offline_imports_and_injected_clients_do_not_load_sdk(scenario: str) -> None:
    source = Path(__file__).resolve().parents[2] / "src"
    program = r"""
import importlib.abc
import sys
from types import ModuleType

class BlockTransport(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "tushare" or fullname.startswith(
            ("tushare.", "openai", "quantos.agents.openai")
        ):
            raise RuntimeError("FORBIDDEN_TRANSPORT_IMPORT")

sys.meta_path.insert(0, BlockTransport())
scenario = sys.argv[1]
if scenario == "offline_modules":
    import quantos.infrastructure.hosted_negative_probe
    import quantos.infrastructure.hosted_offline
    import quantos.application.hosted_campaign
    assert not any(
        name == "tushare" or name.startswith(("tushare.", "openai"))
        for name in sys.modules
    )
else:
    from quantos.data.tushare.capabilities import TushareSnapshotSource
    class Client:
        def __bool__(self):
            return False
        def query(self, *args, **kwargs):
            raise AssertionError("UNEXPECTED_QUERY")
    client = Client()
    if scenario == "injected_client":
        source = TushareSnapshotSource("NON_SECRET_ACQUISITION_FIXTURE", client=client)
        assert source.client is client and not source._probe_limiters
        assert "tushare" not in sys.modules
    elif scenario == "invalid_token":
        try:
            TushareSnapshotSource("", client=client)
        except ValueError:
            pass
        else:
            raise AssertionError("EMPTY_TOKEN_ACCEPTED")
        assert "tushare" not in sys.modules
    else:
        # Stub only the acquisition SDK factory, never call a real vendor endpoint.
        module = ModuleType("tushare")
        seen = []
        def pro_api(token):
            assert token == "NON_SECRET_ACQUISITION_FIXTURE"
            seen.append("INITIALIZED")
            return client
        module.pro_api = pro_api
        sys.modules["tushare"] = module
        source = TushareSnapshotSource("NON_SECRET_ACQUISITION_FIXTURE")
        assert source.client is client and seen == ["INITIALIZED"]
        assert set(source._probe_limiters) == {"trade_cal", "stock_basic"}
print("OFFLINE_IMPORT_BOUNDARY_VERIFIED")
"""
    result = subprocess.run(
        (sys.executable, "-c", program, scenario),
        env={"PATH": "/usr/bin:/bin", "HOME": "/tmp", "PYTHONPATH": str(source)},
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert b"OFFLINE_IMPORT_BOUNDARY_VERIFIED" in result.stdout
