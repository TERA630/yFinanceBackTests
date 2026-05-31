"""yfinance data access for Backtest A."""

from __future__ import annotations

from typing import Dict, List, Tuple

import pandas as pd
import yfinance as yf

from app.data.fundamental_extractors import (
    extract_per_pbr,
    extract_quarterly_sales_growth_pct,
    extract_roa_pct,
)


def fetch_raw_price_map(watchlist: List[Tuple[str, str]], start_date: str, end_date: str) -> Dict[str, pd.DataFrame]:
    symbols = [f"{code}.T" for _, code in watchlist]
    start = (pd.Timestamp(start_date) - pd.Timedelta(days=340)).strftime("%Y-%m-%d")
    end = (pd.Timestamp(end_date) + pd.Timedelta(days=45)).strftime("%Y-%m-%d")

    data = yf.download(
        tickers=symbols,
        start=start,
        end=end,
        interval="1d",
        auto_adjust=True,
        progress=False,
        threads=True,
        group_by="ticker",
    )

    price_map: Dict[str, pd.DataFrame] = {}
    if data is None or data.empty:
        for _, code in watchlist:
            price_map[code] = pd.DataFrame()
        return price_map

    if isinstance(data.columns, pd.MultiIndex):
        lv0 = set(data.columns.get_level_values(0))
        for _, code in watchlist:
            symbol = f"{code}.T"
            if symbol not in lv0:
                price_map[code] = pd.DataFrame()
                continue
            df = data[symbol].copy()
            df.columns = [str(c).title() for c in df.columns]
            df.index = pd.to_datetime(df.index).tz_localize(None)
            price_map[code] = df.sort_index()
    else:
        _, code = watchlist[0]
        df = data.copy()
        df.columns = [str(c).title() for c in df.columns]
        df.index = pd.to_datetime(df.index).tz_localize(None)
        price_map[code] = df.sort_index()

    return price_map


def fetch_fundamentals_once(watchlist: List[Tuple[str, str]]) -> Dict[str, dict]:
    fundamentals: Dict[str, dict] = {}
    for name, code in watchlist:
        symbol = f"{code}.T"
        info: dict = {}
        income_stmt = pd.DataFrame()
        quarterly_income_stmt = pd.DataFrame()
        balance_sheet = pd.DataFrame()

        try:
            ticker = yf.Ticker(symbol)
            try:
                x = ticker.info
                if isinstance(x, dict):
                    info = x
            except Exception:
                info = {}
            try:
                x = ticker.income_stmt
                if isinstance(x, pd.DataFrame):
                    income_stmt = x
            except Exception:
                income_stmt = pd.DataFrame()
            try:
                x = ticker.quarterly_income_stmt
                if isinstance(x, pd.DataFrame):
                    quarterly_income_stmt = x
            except Exception:
                quarterly_income_stmt = pd.DataFrame()
            try:
                x = ticker.balance_sheet
                if isinstance(x, pd.DataFrame):
                    balance_sheet = x
            except Exception:
                balance_sheet = pd.DataFrame()
        except Exception:
            pass

        per, pbr = extract_per_pbr(info)
        sales_growth_pct = extract_quarterly_sales_growth_pct(info, quarterly_income_stmt, income_stmt)
        roa_pct = extract_roa_pct(info, income_stmt, balance_sheet)

        fundamentals[code] = {
            "name": name,
            "symbol": symbol,
            "per": per,
            "pbr": pbr,
            "sales_growth_pct": sales_growth_pct,
            "roa_pct": roa_pct,
        }
        print(f"[fundamentals] {name} ({code}) loaded")
    return fundamentals
