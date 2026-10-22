"""Exact whole-group matching; this does not judge semantic equivalence."""

from collections.abc import Mapping, Sequence

from quantos.contracts.base import canonical_json_bytes


def group_match(
    actual: Sequence[Mapping[str, object]],
    approved: Sequence[Sequence[Mapping[str, object]]],
) -> bool:
    """Match one complete preapproved group, ignoring order but rejecting duplicates."""
    keys = [canonical_json_bytes(citation) for citation in actual]
    return len(keys) == len(set(keys)) and any(
        set(keys) == {canonical_json_bytes(citation) for citation in group} for group in approved
    )
