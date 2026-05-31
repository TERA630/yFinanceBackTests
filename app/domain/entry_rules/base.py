"""Entry rule interface definitions."""

from __future__ import annotations

from typing import Protocol

import pandas as pd

from app.domain.models import ScreenResult


class EntryRule(Protocol):
    name: str

    def evaluate(
        self,
        name: str,
        code: str,
        trade_date: pd.Timestamp,
        row: pd.Series,
        prev3: pd.DataFrame,
        fundamentals: dict,
    ) -> ScreenResult:
        ...
