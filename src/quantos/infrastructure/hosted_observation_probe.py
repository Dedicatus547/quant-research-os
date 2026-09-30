"""Fixed offline management fixtures for bounded observation; never live source."""

from __future__ import annotations

import argparse

from quantos.contracts.base import canonical_json_bytes
from quantos.infrastructure.hosted_fixture_frames import HOST_OBSERVATION_CASES
from quantos.infrastructure.hosted_negative_probe import (
    run_transport_fixture,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-hash", required=True)
    parser.add_argument("--case", choices=HOST_OBSERVATION_CASES, required=True)
    args = parser.parse_args()
    try:
        run_transport_fixture(args.profile_hash, args.case, "Q08")
    except Exception as error:
        print(
            canonical_json_bytes(
                {"observation": "FAILED", "error_type": type(error).__name__}
            ).decode()
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
