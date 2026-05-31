"""Normalize yfinance fundamental fields for Backtest A."""

from __future__ import annotations

from typing import Optional, Tuple

import pandas as pd

from app.domain.indicators import safe_float


def extract_per_pbr(info: dict) -> Tuple[Optional[float], Optional[float]]:
    return safe_float(info.get("trailingPE")), safe_float(info.get("priceToBook"))


def extract_quarterly_sales_growth_pct(
    info: dict,
    quarterly_income_stmt: pd.DataFrame,
    income_stmt: pd.DataFrame,
) -> Optional[float]:
    for key in ["quarterlyRevenueGrowth", "revenueGrowth"]:
        raw = safe_float(info.get(key))
        if raw is not None:
            return raw * 100

    if isinstance(quarterly_income_stmt, pd.DataFrame) and not quarterly_income_stmt.empty:
        row_name = next((r for r in ["Total Revenue", "Revenue"] if r in quarterly_income_stmt.index), None)
        if row_name is not None:
            vals = quarterly_income_stmt.loc[row_name].dropna()
            if len(vals) >= 5:
                latest = safe_float(vals.iloc[0])
                prev_yoy = safe_float(vals.iloc[4])
                if latest is not None and prev_yoy not in (None, 0):
                    return (latest / prev_yoy - 1.0) * 100
            elif len(vals) >= 2:
                latest = safe_float(vals.iloc[0])
                prev = safe_float(vals.iloc[1])
                if latest is not None and prev not in (None, 0):
                    return (latest / prev - 1.0) * 100

    if isinstance(income_stmt, pd.DataFrame) and not income_stmt.empty:
        row_name = next((r for r in ["Total Revenue", "Revenue"] if r in income_stmt.index), None)
        if row_name is not None:
            vals = income_stmt.loc[row_name].dropna()
            if len(vals) >= 2:
                latest = safe_float(vals.iloc[0])
                prev = safe_float(vals.iloc[1])
                if latest is not None and prev not in (None, 0):
                    return (latest / prev - 1.0) * 100
    return None


def extract_roa_pct(info: dict, income_stmt: pd.DataFrame, balance_sheet: pd.DataFrame) -> Optional[float]:
    roa = safe_float(info.get("returnOnAssets"))
    if roa is not None:
        return roa * 100

    if income_stmt.empty or balance_sheet.empty:
        return None

    ni_row = next((r for r in ["Net Income", "Net Income Common Stockholders"] if r in income_stmt.index), None)
    ta_row = next((r for r in ["Total Assets"] if r in balance_sheet.index), None)
    if ni_row is None or ta_row is None:
        return None

    ni_vals = income_stmt.loc[ni_row].dropna()
    ta_vals = balance_sheet.loc[ta_row].dropna()
    if len(ni_vals) < 1 or len(ta_vals) < 1:
        return None

    net_income = safe_float(ni_vals.iloc[0])
    total_assets = safe_float(ta_vals.iloc[0])
    if net_income is None or total_assets in (None, 0):
        return None

    return (net_income / total_assets) * 100
