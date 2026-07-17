"""Pure position-state simulation for the A11 backtest."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Optional

import pandas as pd


DUPLICATE_HOLDING = "holding_signal"
DUPLICATE_NOT_RESET = "signal_not_reset"
DUPLICATE_MIN_INTERVAL = "minimum_reentry_interval"

EXIT_TAKE_PROFIT = "take_profit_5pct"
EXIT_STOP_LOSS = "stop_loss_3pct"
EXIT_HORIZON = "holding_period_end"
EXIT_INCOMPLETE = "insufficient_future_data"

TAKE_PROFIT_PCT = 5.0
STOP_LOSS_PCT = -3.0
MINIMUM_FULL_BUSINESS_DAYS_BETWEEN_ENTRIES = 3


class PositionState(str, Enum):
    FLAT = "flat"
    OPEN = "open"
    COOLDOWN = "cooldown"


@dataclass(frozen=True)
class PositionExit:
    date: Optional[pd.Timestamp]
    price: Optional[float]
    reason: str


@dataclass(frozen=True)
class PositionSimulation:
    trades: pd.DataFrame
    signal_count: int
    duplicate_counts: Counter


def simulate_positions(
    candidates: pd.DataFrame,
    daily_by_code: Mapping[str, pd.DataFrame],
    holding_period_days: int,
) -> PositionSimulation:
    """Apply per-symbol OPEN/COOLDOWN behavior to chronological signals."""
    if holding_period_days <= 0:
        raise ValueError("保有期間は1営業日以上で指定してください。")
    if candidates.empty:
        return PositionSimulation(pd.DataFrame(), 0, Counter())

    required = {"code", "signal_date", "entry_date", "entry_price"}
    missing = required.difference(candidates.columns)
    if missing:
        raise ValueError(f"ポジション候補の必須列がありません: {', '.join(sorted(missing))}")

    ordered = candidates.copy()
    ordered["code"] = ordered["code"].astype(str)
    ordered["signal_date"] = pd.to_datetime(ordered["signal_date"]).dt.normalize()
    ordered["entry_date"] = pd.to_datetime(ordered["entry_date"]).dt.normalize()
    ordered = ordered.sort_values(["signal_date", "code", "entry_date"], kind="stable")
    ordered = ordered.drop_duplicates(["code", "signal_date"], keep="first").reset_index(drop=True)

    calendars = {
        str(code): _trading_calendar(daily)
        for code, daily in daily_by_code.items()
    }
    signal_dates_by_code = {
        code: set(group["signal_date"])
        for code, group in ordered.groupby("code", sort=False)
    }

    duplicate_counts: Counter = Counter()
    accepted_records: list[dict] = []
    latest_position: dict[str, dict] = {}

    for _, candidate in ordered.iterrows():
        code = str(candidate["code"])
        signal_date = pd.Timestamp(candidate["signal_date"]).normalize()
        previous = latest_position.get(code)
        state = _position_state(previous, signal_date)

        if state == PositionState.OPEN:
            duplicate_counts[DUPLICATE_HOLDING] += 1
            continue

        if state == PositionState.COOLDOWN and previous is not None:
            exit_date = previous["exit_date"]
            calendar = calendars.get(code, pd.DatetimeIndex([]))
            reset_observed = _has_failed_signal_day(
                calendar,
                signal_dates_by_code.get(code, set()),
                exit_date,
                signal_date,
            )
            if not reset_observed:
                duplicate_counts[DUPLICATE_NOT_RESET] += 1
                continue

            full_days = _full_business_days_between(
                calendar,
                previous["entry_date"],
                signal_date,
            )
            if full_days < MINIMUM_FULL_BUSINESS_DAYS_BETWEEN_ENTRIES:
                duplicate_counts[DUPLICATE_MIN_INTERVAL] += 1
                continue

        daily = daily_by_code.get(code, pd.DataFrame())
        entry_date = pd.Timestamp(candidate["entry_date"]).normalize()
        entry_price = _number(candidate["entry_price"])
        if entry_price is None or entry_price <= 0:
            continue
        exit_result = determine_position_exit(daily, entry_date, entry_price, holding_period_days)
        return_pct = (
            None
            if exit_result.price is None
            else (exit_result.price / entry_price - 1.0) * 100.0
        )
        record = candidate.to_dict()
        record.update(
            {
                "holding_period_days": holding_period_days,
                "exit_date": exit_result.date,
                "exit_price": exit_result.price,
                "exit_reason": exit_result.reason,
                "position_return_pct": return_pct,
            }
        )
        accepted_records.append(record)
        latest_position[code] = {
            "entry_date": entry_date,
            "exit_date": exit_result.date,
        }

    return PositionSimulation(
        trades=pd.DataFrame(accepted_records),
        signal_count=int(len(ordered)),
        duplicate_counts=duplicate_counts,
    )


def determine_position_exit(
    daily: pd.DataFrame,
    entry_date: pd.Timestamp,
    entry_price: float,
    holding_period_days: int,
) -> PositionExit:
    """Resolve the first threshold touch, conservatively preferring -3%."""
    if daily is None or daily.empty or entry_price <= 0:
        return PositionExit(None, None, EXIT_INCOMPLETE)
    normalized = daily.copy()
    normalized.index = pd.DatetimeIndex(normalized.index).normalize()
    normalized = normalized.sort_index()
    positions = normalized.index.get_indexer([pd.Timestamp(entry_date).normalize()])
    entry_position = int(positions[0])
    final_position = entry_position + holding_period_days
    if entry_position < 0 or final_position >= len(normalized):
        return PositionExit(None, None, EXIT_INCOMPLETE)

    take_profit_price = entry_price * 1.05
    stop_loss_price = entry_price * 0.97
    high_source = normalized["High"] if "High" in normalized.columns else normalized["Close"]
    for position in range(entry_position + 1, final_position + 1):
        high = _number(high_source.iloc[position])
        low = _number(normalized["Low"].iloc[position])
        reached_take_profit = high is not None and high >= take_profit_price
        reached_stop_loss = low is not None and low <= stop_loss_price
        if reached_stop_loss:
            return PositionExit(pd.Timestamp(normalized.index[position]), stop_loss_price, EXIT_STOP_LOSS)
        if reached_take_profit:
            return PositionExit(pd.Timestamp(normalized.index[position]), take_profit_price, EXIT_TAKE_PROFIT)

    final_close = _number(normalized["Close"].iloc[final_position])
    if final_close is None:
        return PositionExit(None, None, EXIT_INCOMPLETE)
    return PositionExit(pd.Timestamp(normalized.index[final_position]), final_close, EXIT_HORIZON)


def _has_failed_signal_day(
    calendar: pd.DatetimeIndex,
    signal_dates: set[pd.Timestamp],
    exit_date: pd.Timestamp,
    current_signal_date: pd.Timestamp,
) -> bool:
    eligible = calendar[(calendar > exit_date) & (calendar < current_signal_date)]
    return any(pd.Timestamp(date).normalize() not in signal_dates for date in eligible)


def _position_state(previous: Optional[dict], signal_date: pd.Timestamp) -> PositionState:
    if previous is None:
        return PositionState.FLAT
    exit_date = previous["exit_date"]
    if exit_date is None or signal_date <= exit_date:
        return PositionState.OPEN
    return PositionState.COOLDOWN


def _full_business_days_between(
    calendar: pd.DatetimeIndex,
    entry_date: pd.Timestamp,
    signal_date: pd.Timestamp,
) -> int:
    return int(((calendar > entry_date) & (calendar < signal_date)).sum())


def _trading_calendar(daily: pd.DataFrame) -> pd.DatetimeIndex:
    if daily is None or daily.empty:
        return pd.DatetimeIndex([])
    return pd.DatetimeIndex(daily.index).normalize().unique().sort_values()


def _number(value) -> Optional[float]:
    try:
        return None if pd.isna(value) else float(value)
    except (TypeError, ValueError):
        return None
