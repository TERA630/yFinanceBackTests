"""Markdown reports for VWAP backtest results."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from app.domain.vwap_backtest import (
    EXCURSION_WINDOWS,
    HORIZONS,
    MA5_SLOWDOWN_ALLOW_ONE,
    MA5_SLOWDOWN_ALLOW_PREVIOUS_DAY,
    MA5_SLOWDOWN_ALLOW_THREE_DAYS_AGO,
    MA5_SLOWDOWN_IGNORE,
    MA5_SLOWDOWN_REJECT_ANY,
    RESISTANCE_FAILURE_IGNORE,
    RESISTANCE_FAILURE_REJECT_ALL,
    RESISTANCE_FAILURE_REJECT_APPROACH,
)


MA5_SLOWDOWN_LABELS = {
    MA5_SLOWDOWN_IGNORE: "考慮しない",
    MA5_SLOWDOWN_REJECT_ANY: "前日・3日前とも許容しない",
    MA5_SLOWDOWN_ALLOW_ONE: "前日・3日前のいずれかのみ許容",
    MA5_SLOWDOWN_ALLOW_THREE_DAYS_AGO: "3日前のみ許容",
    MA5_SLOWDOWN_ALLOW_PREVIOUS_DAY: "前日のみ許容",
}
RESISTANCE_FAILURE_LABELS = {
    RESISTANCE_FAILURE_IGNORE: "考慮しない",
    RESISTANCE_FAILURE_REJECT_APPROACH: "接近して失速した場合は除外",
    RESISTANCE_FAILURE_REJECT_ALL: "接近失速・だまし突破の両方を除外",
}


def save_a9r2_reports(out_dir: Path, trades: pd.DataFrame, summary: dict) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    report_date = datetime.now().strftime("%m-%d")
    summary_path, result_path = _report_paths(out_dir, summary, report_date)
    summary_path.write_text(_summary_markdown(summary), encoding="utf-8")
    result_path.write_text(_result_markdown(trades, summary), encoding="utf-8")
    return summary_path, result_path


def save_a8_reports(out_dir: Path, trades: pd.DataFrame, summary: dict) -> tuple[Path, Path]:
    """Compatibility alias for callers using the former A8 report name."""
    return save_a9r2_reports(out_dir, trades, summary)


def save_vwap_reports(out_dir: Path, trades: pd.DataFrame, summary: dict) -> tuple[Path, Path]:
    """Compatibility alias for the former VWAP report writer."""
    return save_a9r2_reports(out_dir, trades, summary)


def _report_paths(out_dir: Path, summary: dict, report_date: str) -> tuple[Path, Path]:
    condition = _filename_condition(summary)
    index = 1
    while True:
        summary_path = out_dir / f"bt_v9r2_{condition}-{report_date}_summary-{index}.md"
        result_path = out_dir / f"bt_v9r2_{condition}-{report_date}_result-{index}.md"
        if not summary_path.exists() and not result_path.exists():
            return summary_path, result_path
        index += 1


def _summary_markdown(summary: dict) -> str:
    lines = [
        "# A9r2バックテスト サマリー",
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
        "# A9r2バックテスト 個別結果",
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
            f"- 支持線反発: {_support_rebound(row)}",
            f"- エントリー時刻: {_entry_label(row['entry_time'])}",
            f"- VWAP維持確認: {'あり' if row['vwap_confirmation_required'] else 'なし'}",
            f"- 買値: {_price(row['entry_price'])}",
            f"- 終端位置: {_percent(row.get('entry_range_position_pct'))}",
            f"- 当日暫定MA5: {_price(row.get('entry_ma5'))}",
            f"- 5日線傾き: {_percent(row.get('ma5_slope_pct'))}",
            f"- 前日5日線傾き: {_percent(row.get('previous_ma5_slope_pct'))}",
            f"- 3営業日前5日線傾き: {_percent(row.get('three_days_ago_ma5_slope_pct'))}",
            f"- 当日暫定MA25: {_price(row['entry_ma25'])}",
            f"- 当日25日乖離率: {_percent(row['entry_dev25_pct'])}",
            f"- 25日線傾き: {_percent(row['ma25_slope_pct'])}",
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
        "- 25日線傾き: 横ばい以上（0%以上）",
        f"- 5日線傾き: {'0%超を必須' if summary.get('require_ma5_slope_positive') else '条件なし'}",
        f"- 5日線傾き鈍化: {_ma5_slowdown_label(summary.get('ma5_slope_slowdown_policy'))}",
        f"- VWAP維持確認: {'あり' if summary['require_vwap_confirmation'] else 'なし'}",
        f"- エントリー時刻: {_entry_label(summary['entry_time'])}",
        f"- 3日間の安値切り下げ除外: {summary['lower_low_exclude_count']}回以上"
        if summary['lower_low_exclude_count'] > 0 else "- 3日間の安値切り下げ除外: なし",
        f"- 3日間の高値更新条件: {summary.get('higher_high_exclude_count', 0)}回以上"
        if summary.get('higher_high_exclude_count', 0) > 0 else "- 3日間の高値更新条件: 考慮しない",
        f"- 支持線反発: {'確認する' if summary.get('require_support_rebound') else '確認しない'}",
        f"- 抵抗線トライ失敗: {_resistance_failure_label(summary.get('resistance_failure_policy'))}",
        f"- 終端位置: {_range_condition(summary.get('range_position_min_pct'))}",
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
    return "前日終値" if value == "prev_close" else value


def _range_condition(value) -> str:
    return "考慮せず" if value is None or pd.isna(value) else f"{float(value):g}%以上"


def _ma5_slowdown_label(value) -> str:
    return MA5_SLOWDOWN_LABELS.get(value, MA5_SLOWDOWN_LABELS[MA5_SLOWDOWN_IGNORE])


def _resistance_failure_label(value) -> str:
    return RESISTANCE_FAILURE_LABELS.get(value, RESISTANCE_FAILURE_LABELS[RESISTANCE_FAILURE_IGNORE])


def _support_rebound(row: pd.Series) -> str:
    if not row.get("support_rebound", False):
        return "なし"
    level_type = row.get("support_level_type")
    level = row.get("support_level")
    if level_type is None or level is None or pd.isna(level):
        return "あり"
    return f"{level_type} ({_price(level)})"


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
