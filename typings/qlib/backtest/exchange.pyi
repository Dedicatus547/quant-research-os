"""Qlib 0.9.7 Exchange surface consumed by the frozen open-limit adapter.

Typing only; the installed Qlib implementation still owns execution and accounting.
Other Qlib modules continue to resolve from the installed distribution.
"""

from typing import Any

import pandas as pd

class Exchange:
    quote_df: pd.DataFrame
    trade_w_adj_price: bool
    def __init__(self, **kwargs: Any) -> None: ...
    def _update_limit(self, limit_threshold: tuple[str, str] | float | None) -> None: ...
