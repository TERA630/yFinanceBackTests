"""A7R2 entry rule implementation."""

from __future__ import annotations

from typing import List, Optional, Tuple

import pandas as pd

from app.domain.config import (
    CATEGORY_PRIORITY,
    DEV25_HARD_MAX,
    DEV25_SOFT_1,
    DEV25_SOFT_2,
    DEV5_HARD_LOW,
    DEV5_HARD_MAX,
    DEV5_SOFT_MAX,
    DEV5_SOFT_MIN,
    ENTRY_LIMIT_DEV_FROM_25,
    GENERAL_SALES_GROWTH_FLOOR,
    LEADER_CODES,
    LEADER_SALES_GROWTH_FLOOR,
    MA25_SLOPE_MIN,
    MA75_SLOPE_MIN,
    MAX_DAY_GAIN,
    MAX_RSI,
    MIN_RSI,
    MIN_TURNOVER_20D,
    NEAR_HIGH_MIN,
    PERCENT_B_HARD_MAX,
    PERCENT_B_SOFT_MAX,
    PER_HARD_EXCLUDE,
    PER_HARD_EXCLUDE_DEV25,
    PER_HARD_EXCLUDE_RSI,
    REBOUND_DEV25_MAX,
    ROA_HARD_MIN,
    ROA_PASS_MIN,
    ROA_STRONG_MIN,
    SOFT_FAIL_NEAR_PASS_MAX,
    TWO_DAY_GAIN_HARD_MAX,
)
from app.domain.indicators import safe_float
from app.domain.models import ReasonItem, ScreenResult


def add_reason(items: List[ReasonItem], category: str, message: str, *, is_hard: bool, priority: int) -> None:
    items.append(ReasonItem(category=category, message=message, is_hard=is_hard, priority=priority))


def summarize_reasons(reason_items: List[ReasonItem]) -> Tuple[Optional[str], Optional[str], List[str]]:
    if not reason_items:
        return None, None, []

    ordered = sorted(
        reason_items,
        key=lambda x: (CATEGORY_PRIORITY.get(x.category, 99), x.priority, 0 if x.is_hard else 1, x.message),
    )
    primary = ordered[0]
    secondary: List[str] = []
    seen = {primary.message}
    for item in ordered[1:]:
        if item.message not in seen:
            secondary.append(item.message)
            seen.add(item.message)
    return primary.category, primary.message, secondary



def is_recoverable_soft_reason(item: ReasonItem) -> bool:
    if item.is_hard:
        return False
    msg = item.message or ""
    if item.category == "過熱":
        if "25日線からやや過熱" in msg or "25日線から強い過熱" in msg:
            return True
        if "%B=" in msg or "+2σ超え" in msg:
            return True
    if item.category == "押し目未完成":
        if "直近3日で安値切り下げが続く" in msg:
            return True
    return False


def can_promote_soft_fails(reason_items: List[ReasonItem]) -> bool:
    softs = [x for x in reason_items if not x.is_hard]
    if not softs:
        return True
    return all(is_recoverable_soft_reason(x) for x in softs)

def estimate_entry_limits(ma25: Optional[float], close: Optional[float]) -> Tuple[Optional[float], Optional[float]]:
    if ma25 is None:
        return None, None
    low = ma25
    high = ma25 * (1 + ENTRY_LIMIT_DEV_FROM_25 / 100)
    if close is not None and close < high:
        high = max(close, low)
    return low, high


# =========================
# scoring / evaluation
# =========================
def score_result_a7r2(
    *,
    close: Optional[float],
    ma25: Optional[float],
    ma75: Optional[float],
    dev5: Optional[float],
    dev25: Optional[float],
    rsi: Optional[float],
    momentum_pct: Optional[float],
    avg_turnover_20d: Optional[float],
    near_high_ratio: Optional[float],
    ma25_slope_pct: Optional[float],
    ma75_slope_pct: Optional[float],
    roa_pct: Optional[float],
    sales_growth_pct: Optional[float],
    bb_percent_b: Optional[float],
    code: str,
) -> int:
    score = 0

    if ma25 is not None and ma75 is not None and ma25 > ma75:
        score += 15
    if close is not None and ma25 is not None and close > ma25:
        score += 15
    if ma25_slope_pct is not None and ma25_slope_pct > MA25_SLOPE_MIN:
        score += 8
    if ma75_slope_pct is not None and ma75_slope_pct >= MA75_SLOPE_MIN:
        score += 5

    if dev25 is not None:
        if 0.5 <= dev25 <= 4.0:
            score += 14
        elif 0 <= dev25 <= DEV25_SOFT_1:
            score += 10
        elif -1.0 <= dev25 < 0:
            score += 3

    if dev5 is not None:
        if 0.5 <= dev5 <= 2.5:
            score += 10
        elif DEV5_SOFT_MIN <= dev5 <= DEV5_SOFT_MAX:
            score += 5

    if rsi is not None:
        if 47.0 <= rsi <= 60.0:
            score += 10
        elif MIN_RSI <= rsi <= MAX_RSI:
            score += 5

    if near_high_ratio is not None:
        if near_high_ratio >= 0.90:
            score += 8
        elif near_high_ratio >= NEAR_HIGH_MIN:
            score += 4

    if avg_turnover_20d is not None:
        if avg_turnover_20d >= 5_000_000_000:
            score += 5
        elif avg_turnover_20d >= MIN_TURNOVER_20D:
            score += 3

    if momentum_pct is not None and momentum_pct > 0:
        score += 5

    if roa_pct is not None:
        if roa_pct >= ROA_STRONG_MIN:
            score += 6
        elif roa_pct >= ROA_PASS_MIN:
            score += 3
        elif roa_pct >= ROA_HARD_MIN:
            score += 1

    leader_floor = 5.0 if code not in LEADER_CODES else 0.0
    if sales_growth_pct is not None and sales_growth_pct >= leader_floor:
        score += 6
    elif sales_growth_pct is not None and sales_growth_pct > LEADER_SALES_GROWTH_FLOOR:
        score += 2

    if bb_percent_b is not None:
        if 0.25 <= bb_percent_b <= 0.90:
            score += 4
        elif bb_percent_b > 0.98:
            score -= 2

    return max(0, min(score, 100))


def evaluate_row_a7r2(
    name: str,
    code: str,
    trade_date: pd.Timestamp,
    row: pd.Series,
    prev3: pd.DataFrame,
    fundamentals: dict,
) -> ScreenResult:
    close = safe_float(row["Close"])
    ma5 = safe_float(row["MA5"])
    ma25 = safe_float(row["MA25"])
    ma75 = safe_float(row["MA75"])
    dev5 = safe_float(row["Dev5"])
    dev25 = safe_float(row["Dev25"])
    rsi = safe_float(row["RSI14"])
    momentum_raw = safe_float(row["Momentum20"])
    momentum_pct = momentum_raw * 100 if momentum_raw is not None else None
    avg_turnover_20d = safe_float(row["AvgTurnover20"])
    near_high_ratio = safe_float(row["NearHighRatio"])
    ma25_slope_pct = safe_float(row["MA25_SlopePct"])
    ma75_slope_pct = safe_float(row["MA75_SlopePct"])
    day_change_pct = safe_float(row["DayChangePct"])
    volume_ratio_20d = safe_float(row["VolumeRatio20"])
    close_position_pct = safe_float(row["ClosePositionPct"])
    prev_close = safe_float(row["PrevClose"])
    bb_upper = safe_float(row.get("BB_Upper20"))
    bb_lower = safe_float(row.get("BB_Lower20"))
    bb_percent_b = safe_float(row.get("BB_PercentB"))
    prev2_base = safe_float(row.get("Close2Ago"))
    two_day_gain_pct = None if prev2_base in (None, 0) or close is None else (close / prev2_base - 1.0) * 100.0

    per = fundamentals.get("per")
    pbr = fundamentals.get("pbr")
    sales_growth_pct = fundamentals.get("sales_growth_pct")
    roa_pct = fundamentals.get("roa_pct")

    reason_items: List[ReasonItem] = []
    hard_fail = False
    soft_fail_count = 0
    is_leader = code in LEADER_CODES

    # ===== trend =====
    if ma25 is None or ma75 is None:
        hard_fail = True
        add_reason(reason_items, "判定保留", "移動平均線データ不足", is_hard=True, priority=1)
    elif ma25 <= ma75:
        hard_fail = True
        add_reason(reason_items, "下降トレンド", "25日線が75日線の上にない", is_hard=True, priority=1)

    if close is None or ma25 is None:
        hard_fail = True
        add_reason(reason_items, "判定保留", "終値または25日線データ不足", is_hard=True, priority=2)
    elif close <= ma25:
        hard_fail = True
        add_reason(reason_items, "下降トレンド", "終値が25日線の上にない", is_hard=True, priority=2)

    if ma25_slope_pct is None:
        hard_fail = True
        add_reason(reason_items, "判定保留", "25日線傾きデータ不足", is_hard=True, priority=3)
    elif ma25_slope_pct <= MA25_SLOPE_MIN:
        hard_fail = True
        add_reason(reason_items, "下降トレンド", f"25日線の傾きが弱い({ma25_slope_pct:.2f}%)", is_hard=True, priority=3)

    if ma75_slope_pct is None:
        hard_fail = True
        add_reason(reason_items, "判定保留", "75日線傾きデータ不足", is_hard=True, priority=4)
    elif ma75_slope_pct < MA75_SLOPE_MIN:
        hard_fail = True
        add_reason(reason_items, "下降トレンド", f"75日線が上向きでない({ma75_slope_pct:.2f}%)", is_hard=True, priority=4)

    if near_high_ratio is None:
        hard_fail = True
        add_reason(reason_items, "判定保留", "60日高値圏データ不足", is_hard=True, priority=5)
    elif near_high_ratio < NEAR_HIGH_MIN:
        hard_fail = True
        add_reason(reason_items, "下降トレンド", "60日高値圏から離れすぎ", is_hard=True, priority=5)

    # ===== pullback / overheat =====
    if dev25 is None or dev5 is None:
        hard_fail = True
        add_reason(reason_items, "判定保留", "乖離率データ不足", is_hard=True, priority=10)
    else:
        if dev25 < REBOUND_DEV25_MAX:
            hard_fail = True
            add_reason(reason_items, "リバ候補", f"25日線から離れすぎ({dev25:.2f}%)", is_hard=True, priority=1)
        elif dev25 < 0:
            soft_fail_count += 1
            add_reason(reason_items, "押し目未完成", f"25日線を少し割り込み({dev25:.2f}%)", is_hard=False, priority=1)
        elif dev25 > DEV25_HARD_MAX:
            hard_fail = True
            add_reason(reason_items, "過熱", f"25日線乖離が大きすぎる({dev25:.2f}%)", is_hard=True, priority=1)
        elif dev25 > DEV25_SOFT_2:
            soft_fail_count += 1
            add_reason(reason_items, "過熱", f"25日線から強い過熱({dev25:.2f}%)", is_hard=False, priority=2)
        elif dev25 > DEV25_SOFT_1:
            soft_fail_count += 1
            add_reason(reason_items, "過熱", f"25日線からやや過熱({dev25:.2f}%)", is_hard=False, priority=3)

        if dev5 < DEV5_HARD_LOW:
            hard_fail = True
            add_reason(reason_items, "押し目未完成", f"5日線を大きく割り込み({dev5:.2f}%)", is_hard=True, priority=2)
        elif dev5 < DEV5_SOFT_MIN:
            soft_fail_count += 1
            add_reason(reason_items, "押し目未完成", f"5日線を少し割り込み({dev5:.2f}%)", is_hard=False, priority=2)
        elif dev5 > DEV5_HARD_MAX:
            hard_fail = True
            add_reason(reason_items, "過熱", f"5日線から離れすぎ({dev5:.2f}%)", is_hard=True, priority=4)
        elif dev5 > DEV5_SOFT_MAX:
            soft_fail_count += 1
            add_reason(reason_items, "過熱", f"5日線からやや離れすぎ({dev5:.2f}%)", is_hard=False, priority=4)

    # ===== bollinger =====
    if bb_percent_b is not None and bb_percent_b > PERCENT_B_HARD_MAX:
        hard_fail = True
        add_reason(reason_items, "過熱", f"%Bが過熱水準({bb_percent_b:.2f})", is_hard=True, priority=5)
    elif bb_percent_b is not None and bb_percent_b > PERCENT_B_SOFT_MAX:
        soft_fail_count += 1
        add_reason(reason_items, "過熱", f"%Bがやや高い({bb_percent_b:.2f})", is_hard=False, priority=6)
    elif bb_upper is not None and close is not None and close > bb_upper:
        soft_fail_count += 1
        add_reason(reason_items, "過熱", f"+2σ超えで過熱警戒(%B={bb_percent_b:.2f})" if bb_percent_b is not None else "+2σ超えで過熱警戒", is_hard=False, priority=7)

    # ===== RSI / extension =====
    if rsi is None:
        hard_fail = True
        add_reason(reason_items, "判定保留", "RSIデータ不足", is_hard=True, priority=11)
    else:
        if rsi < MIN_RSI:
            hard_fail = True
            add_reason(reason_items, "押し目未完成", f"RSIが弱い({rsi:.2f})", is_hard=True, priority=3)
        elif rsi > MAX_RSI:
            hard_fail = True
            add_reason(reason_items, "過熱", f"RSIが高すぎる({rsi:.2f})", is_hard=True, priority=7)

    if day_change_pct is not None and day_change_pct > MAX_DAY_GAIN:
        hard_fail = True
        add_reason(reason_items, "過熱", f"当日上昇率が大きすぎる({day_change_pct:.2f}%)", is_hard=True, priority=8)

    if two_day_gain_pct is not None and two_day_gain_pct > TWO_DAY_GAIN_HARD_MAX:
        hard_fail = True
        add_reason(reason_items, "過熱", f"直近2日で上がりすぎ({two_day_gain_pct:.2f}%)", is_hard=True, priority=9)

    # ===== pullback completion =====
    if len(prev3) >= 3:
        lower_low_count = int(prev3["LowerLow"].fillna(False).sum())
        bear_count = int(prev3["IsBear"].fillna(False).sum())
        if lower_low_count >= 3:
            hard_fail = True
            add_reason(reason_items, "押し目未完成", "直近3日で安値切り下げが続きすぎ", is_hard=True, priority=4)
        elif lower_low_count == 2:
            soft_fail_count += 1
            add_reason(reason_items, "押し目未完成", "直近3日で安値切り下げが続く", is_hard=False, priority=4)
        if bear_count >= 3:
            hard_fail = True
            add_reason(reason_items, "押し目未完成", "陰線が連続しすぎ", is_hard=True, priority=5)

    if bool(row.get("DownVolExpand2", False)):
        hard_fail = True
        add_reason(reason_items, "押し目未完成", "出来高増で2日連続下落", is_hard=True, priority=6)

    # ===== liquidity =====
    if avg_turnover_20d is None:
        hard_fail = True
        add_reason(reason_items, "判定保留", "20日平均売買代金データ不足", is_hard=True, priority=20)
    elif avg_turnover_20d < MIN_TURNOVER_20D:
        hard_fail = True
        add_reason(reason_items, "流動性不足", "20日平均売買代金が15億円未満", is_hard=True, priority=1)

    # ===== fundamentals =====
    if roa_pct is None:
        soft_fail_count += 1
        add_reason(reason_items, "判定保留", "ROAデータ不足", is_hard=False, priority=30)
    elif roa_pct < ROA_HARD_MIN:
        hard_fail = True
        add_reason(reason_items, "ファンダ注意", f"ROAが低すぎる({roa_pct:.2f}%)", is_hard=True, priority=1)
    elif roa_pct < ROA_PASS_MIN:
        soft_fail_count += 1
        add_reason(reason_items, "ファンダ注意", f"ROAがやや低い({roa_pct:.2f}%)", is_hard=False, priority=2)

    if sales_growth_pct is None:
        soft_fail_count += 1
        add_reason(reason_items, "判定保留", "売上成長率データ不足", is_hard=False, priority=31)
    else:
        floor = LEADER_SALES_GROWTH_FLOOR if is_leader else GENERAL_SALES_GROWTH_FLOOR
        if sales_growth_pct < floor:
            hard_fail = True
            if is_leader:
                add_reason(reason_items, "ファンダ注意", f"売上成長が許容下限以下({sales_growth_pct:.2f}%)", is_hard=True, priority=3)
            else:
                add_reason(reason_items, "ファンダ注意", f"売上成長率が0%未満({sales_growth_pct:.2f}%)", is_hard=True, priority=3)
        elif sales_growth_pct < (0.0 if is_leader else 3.0):
            soft_fail_count += 1
            add_reason(reason_items, "ファンダ注意", f"売上成長が弱い({sales_growth_pct:.2f}%)", is_hard=False, priority=4)

    if per is not None and (dev25 is not None and dev25 >= PER_HARD_EXCLUDE_DEV25) and (rsi is not None and rsi >= PER_HARD_EXCLUDE_RSI) and per > PER_HARD_EXCLUDE:
        hard_fail = True
        add_reason(reason_items, "過熱", f"高PERかつ過熱({per:.2f}倍)", is_hard=True, priority=10)

    promotable_soft_only = can_promote_soft_fails(reason_items)
    passed = (not hard_fail) and (
        soft_fail_count == 0
        or (promotable_soft_only and soft_fail_count <= 2)
    )
    near_pass = (not hard_fail) and (not passed) and (0 < soft_fail_count <= SOFT_FAIL_NEAR_PASS_MAX)

    score = score_result_a7r2(
        close=close,
        ma25=ma25,
        ma75=ma75,
        dev5=dev5,
        dev25=dev25,
        rsi=rsi,
        momentum_pct=momentum_pct,
        avg_turnover_20d=avg_turnover_20d,
        near_high_ratio=near_high_ratio,
        ma25_slope_pct=ma25_slope_pct,
        ma75_slope_pct=ma75_slope_pct,
        roa_pct=roa_pct,
        sales_growth_pct=sales_growth_pct,
        bb_percent_b=bb_percent_b,
        code=code,
    )

    primary_category, primary_reason, secondary_reasons = summarize_reasons(reason_items)

    if passed:
        watch_status = "本命候補"
    elif near_pass:
        watch_status = "監視候補"
    else:
        mapping = {
            "下降トレンド": "見送り:トレンド",
            "押し目未完成": "見送り:押し未完成",
            "過熱": "見送り:過熱",
            "ファンダ注意": "見送り:ファンダ",
            "流動性不足": "見送り:流動性",
            "リバ候補": "別戦略:リバ候補",
            "判定保留": "判定保留",
        }
        watch_status = mapping.get(primary_category or "", "見送り")

    entry_limit_low, entry_limit_high = estimate_entry_limits(ma25, close)

    return ScreenResult(
        code=code,
        name=name,
        symbol=f"{code}.T",
        trade_date=trade_date.strftime("%Y-%m-%d"),
        day_open=safe_float(row["Open"]),
        day_high=safe_float(row["High"]),
        day_low=safe_float(row["Low"]),
        day_close=close,
        ma5=ma5,
        ma25=ma25,
        ma75=ma75,
        dev5=dev5,
        dev25=dev25,
        roa_pct=roa_pct,
        rsi=rsi,
        momentum_pct=momentum_pct,
        per=per,
        pbr=pbr,
        sales_growth_pct=sales_growth_pct,
        avg_turnover_20d=avg_turnover_20d,
        near_high_ratio=near_high_ratio,
        ma25_slope_pct=ma25_slope_pct,
        ma75_slope_pct=ma75_slope_pct,
        day_change_pct=day_change_pct,
        volume_ratio_20d=volume_ratio_20d,
        close_position_pct=close_position_pct,
        prev_close=prev_close,
        passed=passed,
        near_pass=near_pass,
        score=score,
        reason_items=reason_items,
        primary_category=primary_category,
        primary_reason=primary_reason,
        secondary_reasons=secondary_reasons,
        watch_status=watch_status,
        entry_limit_low=entry_limit_low,
        entry_limit_high=entry_limit_high,
        bb_upper=bb_upper,
        bb_lower=bb_lower,
        bb_percent_b=bb_percent_b,
        two_day_gain_pct=two_day_gain_pct,
    )



class A7R2EntryRule:
    name = "a7r2"

    def evaluate(
        self,
        name: str,
        code: str,
        trade_date: pd.Timestamp,
        row: pd.Series,
        prev3: pd.DataFrame,
        fundamentals: dict,
    ) -> ScreenResult:
        return evaluate_row_a7r2(name, code, trade_date, row, prev3, fundamentals)
