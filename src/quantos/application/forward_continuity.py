"""Conservative source-bound exceptions for structural gaps and new nonmembers."""

from typing import Any

import numpy as np


def align_historical_prefix(old: Any, new: Any) -> Any:
    if old.empty or not old.index.isin(new.index).all():
        raise ValueError("historical rows removed")
    added = new.loc[~new.index.isin(old.index)]
    if not added.empty and (added.is_member.isna().any() or added.is_member.any()):
        raise ValueError("new history contains a previously unobserved member")
    return new.reindex(old.index)


def source_observable_factors(frame: Any) -> bool:
    if "adjustment_factor" not in frame:
        return False
    factors = np.asarray(frame.adjustment_factor, dtype=float)
    valid = np.isfinite(factors) & (factors > 0)
    if valid.all():
        return True
    if "is_listed" not in frame or "is_suspended" not in frame:
        return False
    if frame.is_listed.isna().any() or frame.is_suspended.isna().any():
        return False
    structural = np.asarray(~frame.is_listed | frame.is_suspended, dtype=bool)
    return bool((valid | (np.isnan(factors) & structural)).all())
