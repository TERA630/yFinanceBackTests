"""Markdown reports for VWAP backtest results."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from app.domain.vwap_backtest import (
    ENTRY_OPEN,
    ENTRY_PREV_CLOSE,
    EXCURSION_WINDOWS,
    HORIZONS,
    MA25_NEGATIVE_SLOPE_REJECT,
    MA25_NEGATIVE_SLOPE_REJECT_NEGATIVE_OR_SLOWDOWN_5D,
    MA25_NEGATIVE_SLOPE_REJECT_SLOWDOWN_5D,
    MA25_NEGATIVE_SLOPE_SCORE,
    MA5_SLOWDOWN_ALLOW_ONE,
    MA5_SLOWDOWN_ALLOW_PREVIOUS_DAY,
    MA5_SLOWDOWN_ALLOW_THREE_DAYS_AGO,
    MA5_SLOWDOWN_IGNORE,
    MA5_SLOWDOWN_REJECT_ANY,
)


MA5_SLOWDOWN_LABELS = {
    MA5_SLOWDOWN_IGNORE: "考慮しない",
    MA5_SLOWDOWN_REJECT_ANY: "前日・3日前とも許容しない",
    MA5_SLOWDOWN_ALLOW_ONE: "前日・3日前のいずれかのみ許容",
    MA5_SLOWDOWN_ALLOW_THREE_DAYS_AGO: "3日前のみ許容",
    MA5_SLOWDOWN_ALLOW_PREVIOUS_DAY: "前日のみ許容",
}
MA25_NEGATIVE_SLOPE_LABELS = {
    MA25_NEGATIVE_SLOPE_REJECT: "傾き負を即除外",
    MA25_NEGATIVE_SLOPE_SCORE: "即除外しない",
    MA25_NEGATIVE_SLOPE_REJECT_SLOWDOWN_5D: "5日前より傾き鈍化除外",
    MA25_NEGATIVE_SLOPE_REJECT_NEGATIVE_OR_SLOWDOWN_5D: "傾き鈍化、傾き負いずれも除外",
}


def save_a11_reports(out_dir: Path, trades: pd.DataFrame, summary: dict) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    report_date = datetime.now().strftime("%m-%d")
    summary_path, result_path = _report_paths(out_dir, summary, report_date)
    summary_path.write_text(_summary_markdown(summary), encoding="utf-8")
    result_path.write_text(_result_markdown(trades, summary), encoding="utf-8")
    return summary_path, result_path


def save_a9r4_reports(out_dir: Path, trades: pd.DataFrame, summary: dict) -> tuple[Path, Path]:
    """Compatibility alias for callers using the old A9r4 report name."""
    return save_a11_reports(out_dir, trades, summary)


def save_a9r2_reports(out_dir: Path, trades: pd.DataFrame, summary: dict) -> tuple[Path, Path]:
    """Compatibility alias for callers using the old A9r2 report name."""
    return save_a11_reports(out_dir, trades, summary)


def save_a8_reports(out_dir: Path, trades: pd.DataFrame, summary: dict) -> tuple[Path, Path]:
    """Compatibility alias for callers using the former A8 report name."""
    return save_a11_reports(out_dir, trades, summary)


def save_vwap_reports(out_dir: Path, trades: pd.DataFrame, summary: dict) -> tuple[Path, Path]:
    """Compatibility alias for the former VWAP report writer."""
    return save_a11_reports(out_dir, trades, summary)


def _report_paths(out_dir: Path, summary: dict, report_date: str) -> tuple[Path, Path]:
    condition = _filename_condition(summary)
    index = 1
    while True:
        summary_path = out_dir / f"bt_a11_{condition}-{report_date}_summary-{index}.md"
        result_path = out_dir / f"bt_a11_{condition}-{report_date}_result-{index}.md"
        if not summary_path.exists() and not result_path.exists():
            return summary_path, result_path
        index += 1


def _summary_markdown(summary: dict) -> str:
    lines = [
        "# A11バックテスト サマリー",
        "",
        "## 実行条件",
        "",
        *_condition_lines(summary),
        "",
        "## 主項目",
        "",
        "| 評価期間 | +5%到達率 | -3%到達率 | MFE中央値 | MAE中央値 | +5%先着率 | -3%先着率 |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for window in EXCURSION_WINDOWS:
        lines.append(
            f"| {window}営業日 | {_percent(summary[f'reach_5pct_rate_{window}d_pct'])} | "
            f"{_percent(summary[f'adverse_3pct_rate_{window}d_pct'])} | "
            f"{_percent(summary[f'median_mfe_{window}d_pct'])} | "
            f"{_percent(summary[f'median_mae_{window}d_pct'])} | "
            f"{_percent(summary[f'first_reach_5pct_rate_{window}d_pct'])} | "
            f"{_percent(summary[f'first_adverse_3pct_rate_{window}d_pct'])} |"
        )
    lines.extend([
        "",
        "## 副項目",
        "",
        "| 売却時期 | 評価可能件数 | 勝率 |",
        "|---:|---:|---:|",
    ])
    for horizon in HORIZONS:
        lines.append(
            f"| {horizon}営業日後 | {summary[f'completed_{horizon}d']} | "
            f"{_percent(summary[f'win_rate_{horizon}d_pct'])} |"
        )
    lines.extend(["", "## スキップ内訳", ""])
    skipped = summary.get("skipped", {})
    if skipped:
        lines.extend(f"- {reason}: {count}" for reason, count in skipped.items())
    else:
        lines.append("- なし")
    lines.extend(["", "※ 手数料、税金、スリッページ、配当は考慮していません。", ""])
    return "\n".join(lines)


def _result_markdown(trades: pd.DataFrame, summary: dict) -> str:
    entry_only_count = _entry_only_count(trades)
    completed_trades = _completed_result_trades(trades)
    lines = [
        "# A11バックテスト 個別結果",
        "",
        "## 実行条件",
        "",
        *_condition_lines(summary),
        f"- エントリーのみ: {entry_only_count}件",
        "",
    ]
    if trades.empty:
        lines.extend(["エントリー対象銘柄はありませんでした。", ""])
        return "\n".join(lines)

    if completed_trades.empty:
        return "\n".join(lines)

    for _, row in completed_trades.iterrows():
        lines.extend([
            f"## {row['entry_date']} {row['name']} ({row['code']})",
            "",
            f"- 乖離判定日: {row['signal_date']}",
            f"- 前日終値: {_price(row['previous_close'])}",
            f"- 前日MA25: {_price(row['previous_ma25'])}",
            f"- 前日25日乖離率: {_percent(row['previous_dev25_pct'])}",
            f"- 直近3日の安値切り下げ回数: {int(row['lower_low_count_3d'])}回",
            f"- 直近3日の高値更新回数: {int(row.get('higher_high_count_3d', 0))}回",
            f"- 始値時点ATR14: {_price(row.get('atr14_open'))}",
            f"- エントリー条件: {_entry_label(row['entry_time'])}",
            f"- 買値: {_price(row['entry_price'])}",
            f"- {_range_position_label(row['entry_time'])}: {_percent(row.get('entry_range_position_pct'))}",
            f"- 崩れスコア: {_score(row.get('breakdown_score'))}",
            f"- 崩れ理由: {_text_or_na(row.get('breakdown_reasons'))}",
            f"- 出来高20日平均比: {_ratio(row.get('breakdown_volume_ratio_20d'))}",
            f"- 直下支持線距離: {_atr_distance(row.get('nearest_support_distance_atr'))}",
            f"- 当日暫定MA5: {_price(row.get('entry_ma5'))}",
            f"- 5日線傾き: {_percent(row.get('ma5_slope_pct'))}",
            f"- 前日5日線傾き: {_percent(row.get('previous_ma5_slope_pct'))}",
            f"- 3営業日前5日線傾き: {_percent(row.get('three_days_ago_ma5_slope_pct'))}",
            f"- 当日暫定MA25: {_price(row['entry_ma25'])}",
            f"- 当日25日乖離率: {_percent(row['entry_dev25_pct'])}",
            f"- 25日線傾き: {_percent(row['ma25_slope_pct'])}",
            f"- 5営業日前25日線傾き: {_percent(row.get('five_days_ago_ma25_slope_pct'))}",
            f"- 参考VWAP: {_price(row['vwap'])}",
            f"- VWAP上方率（参考）: {_percent(row['vwap_margin_pct'])}",
            "",
            "| 売却時期 | 売値 | 損益 | 損益率 |",
            "|---:|---:|---:|---:|",
        ])
        for horizon in HORIZONS:
            lines.append(
                f"| {horizon}営業日後 | {_price(row[f'sell_price_{horizon}d'])} | "
                f"{_price(row[f'profit_loss_{horizon}d'])} | {_percent(row[f'return_{horizon}d_pct'])} |"
            )
        lines.extend([
            "",
            "| 評価期間 | 最高値 | MFE | 最低値 | 最大含み損 | MAE | 先着 |",
            "|---:|---:|---:|---:|---:|---:|---:|",
        ])
        for window in EXCURSION_WINDOWS:
            lines.append(
                f"| {window}営業日 | {_price(row[f'maximum_price_{window}d'])} | "
                f"{_percent(row[f'max_favorable_excursion_{window}d_pct'])} | "
                f"{_price(row[f'minimum_price_{window}d'])} | "
                f"{_price(row[f'max_drawdown_{window}d'])} | {_percent(row[f'max_drawdown_{window}d_pct'])} | "
                f"{_first_touch(row.get(f'first_touch_{window}d'))} |"
            )
        lines.append("")
    return "\n".join(lines)


def _condition_lines(summary: dict) -> list[str]:
    return [
        f"- 乖離判定期間: {summary['start_date']} ～ {summary['end_date']}",
        f"- 前日・当日25日乖離率: {summary['dev25_min']}% < 乖離率 <= {summary['dev25_max']}%",
        f"- 25日線傾き: {_ma25_negative_slope_label(summary.get('ma25_negative_slope_policy'))}",
        f"- 崩れスコア除外: {_breakdown_score_condition(summary.get('breakdown_score_threshold'))}",
        f"- 5日線傾き: {'0%超を必須' if summary.get('require_ma5_slope_positive') else '条件なし'}",
        f"- 5日線傾き鈍化: {_ma5_slowdown_label(summary.get('ma5_slope_slowdown_policy'))}",
        _vwap_condition(summary),
        f"- エントリー条件: {_entry_label(summary['entry_time'])}",
        f"- 3日間の安値切り下げ: {_lower_low_condition(summary.get('lower_low_exclude_count'))}",
        f"- 3日間の高値更新条件: {summary.get('higher_high_exclude_count', 0)}回以上"
        if summary.get('higher_high_exclude_count', 0) > 0 else "- 3日間の高値更新条件: 考慮しない",
        f"- {_range_position_label(summary['entry_time'])}: {_range_condition(summary.get('range_position_min_pct'))}",
        f"- 直下支持線距離: {_support_distance_condition(summary.get('support_distance_max_atr'))}",
        f"- 監視銘柄数: {summary['stock_count']}",
        f"- 評価件数: {summary['evaluated_count']}",
        f"- エントリー件数: {summary['entry_count']}",
    ]


def _completed_result_trades(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty or "return_5d_pct" not in trades:
        return trades.iloc[0:0].copy()
    return trades.loc[pd.to_numeric(trades["return_5d_pct"], errors="coerce").notna()].copy()


def _entry_only_count(trades: pd.DataFrame) -> int:
    return int(len(trades) - len(_completed_result_trades(trades)))


def _filename_condition(summary: dict) -> str:
    return f"ME25({_number_label(summary['dev25_min'])},{_number_label(summary['dev25_max'])})"


def _number_label(value) -> str:
    return f"{float(value):g}"


def _entry_label(value: str) -> str:
    labels = {
        ENTRY_PREV_CLOSE: "日足:前日終値",
        ENTRY_OPEN: "日足:翌営業日始値",
    }
    return labels.get(value, f"日中足:{value}")


def _range_condition(value) -> str:
    return "考慮せず" if value is None or pd.isna(value) else f"{float(value):g}%以上"


def _range_position_label(entry_time: str) -> str:
    if entry_time in ("11:00", "14:00"):
        return "終端位置"
    return "終値位置"


def _support_distance_condition(value) -> str:
    return "考慮しない" if value is None or pd.isna(value) else f"{float(value):g}ATR超を除外"


def _lower_low_condition(value) -> str:
    labels = {
        0: "考慮しない",
        1: "3日のうち1回でも安値切下げ",
        2: "3日のうち2回安値切下げ",
        3: "3日連続安値切下げ",
    }
    if value is None or pd.isna(value):
        return labels[0]
    return labels.get(int(value), labels[0])


def _ma5_slowdown_label(value) -> str:
    return MA5_SLOWDOWN_LABELS.get(value, MA5_SLOWDOWN_LABELS[MA5_SLOWDOWN_IGNORE])


def _ma25_negative_slope_label(value) -> str:
    return MA25_NEGATIVE_SLOPE_LABELS.get(value, MA25_NEGATIVE_SLOPE_LABELS[MA25_NEGATIVE_SLOPE_REJECT])


def _breakdown_score_condition(value) -> str:
    return "考慮しない" if value is None or pd.isna(value) else f"{int(value)}点以上を除外"


def _vwap_condition(summary: dict) -> str:
    if summary.get("uses_intraday_prices", True):
        return "- VWAP: 単独除外なし（崩れスコアで判定）"
    return "- VWAP: 判定なし（日足条件のみ）"


def _first_touch(value) -> str:
    if value == "plus_5pct":
        return "+5%"
    if value == "minus_3pct":
        return "-3%"
    return "N/A"


def _price(value) -> str:
    return "N/A" if value is None or pd.isna(value) else f"{float(value):,.2f}円"


def _percent(value) -> str:
    return "N/A" if value is None or pd.isna(value) else f"{float(value):.2f}%"


def _ratio(value) -> str:
    return "N/A" if value is None or pd.isna(value) else f"{float(value) * 100.0:.2f}%"


def _atr_distance(value) -> str:
    return "N/A" if value is None or pd.isna(value) else f"{float(value):.2f}ATR"


def _score(value) -> str:
    return "N/A" if value is None or pd.isna(value) else f"{int(value)}点"


def _text_or_na(value) -> str:
    if value is None or pd.isna(value) or value == "":
        return "N/A"
    return str(value)
