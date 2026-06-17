"""Markdown reports for VWAP backtest results."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from app.domain.vwap_backtest import EXCURSION_WINDOWS, HORIZONS


def save_a8_reports(out_dir: Path, trades: pd.DataFrame, summary: dict) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%m-%d-%H-%M-%S")
    summary_path, result_path = _report_paths(out_dir, timestamp)
    summary_path.write_text(_summary_markdown(summary), encoding="utf-8")
    result_path.write_text(_result_markdown(trades, summary), encoding="utf-8")
    return summary_path, result_path


def save_vwap_reports(out_dir: Path, trades: pd.DataFrame, summary: dict) -> tuple[Path, Path]:
    """Compatibility alias for the former VWAP report writer."""
    return save_a8_reports(out_dir, trades, summary)


def _report_paths(out_dir: Path, timestamp: str) -> tuple[Path, Path]:
    suffix = ""
    index = 1
    while True:
        summary_path = out_dir / f"backtest_a8_summary-{timestamp}{suffix}.md"
        result_path = out_dir / f"backtest_a8_result-{timestamp}{suffix}.md"
        if not summary_path.exists() and not result_path.exists():
            return summary_path, result_path
        index += 1
        suffix = f"_{index}"


def _summary_markdown(summary: dict) -> str:
    lines = [
        "# A8バックテスト サマリー",
        "",
        "## 実行条件",
        "",
        f"- 乖離判定期間: {summary['start_date']} ～ {summary['end_date']}",
        f"- 前日・当日25日乖離率: {summary['dev25_min']}% < 乖離率 <= {summary['dev25_max']}%",
        "- 25日線傾き: 横ばい以上（0%以上）",
        f"- 5日線傾き: {'0%超を必須' if summary.get('require_ma5_slope_positive') else '条件なし'}",
        f"- VWAP維持確認: {'あり' if summary['require_vwap_confirmation'] else 'なし'}",
        f"- エントリー時刻: {_entry_label(summary['entry_time'])}",
        f"- 3日間の安値切り下げ除外: {summary['lower_low_exclude_count']}回以上"
        if summary['lower_low_exclude_count'] > 0 else "- 3日間の安値切り下げ除外: なし",
        f"- 終端位置: {_range_condition(summary.get('range_position_min_pct'))}",
        f"- 監視銘柄数: {summary['stock_count']}",
        f"- 評価件数: {summary['evaluated_count']}",
        f"- エントリー件数: {summary['entry_count']}",
        "",
        "## 主要指標（5営業日）",
        "",
        f"- 5営業日後リターン: {_percent(summary['average_return_5d_pct'])}",
        f"- 最大含み損 平均: {_percent(summary['average_max_drawdown_5d_pct'])}",
        f"- 最大含み損 中央値: {_percent(summary['median_max_drawdown_5d_pct'])}",
        f"- 最大順行(MFE)中央値: {_percent(summary['median_mfe_5d_pct'])}",
        f"- 最大逆行(MAE)中央値: {_percent(summary['median_mae_5d_pct'])}",
        f"- -3%逆行率: {_percent(summary['adverse_3pct_rate_5d_pct'])}",
        f"- +5%到達率: {_percent(summary['reach_5pct_rate_5d_pct'])}",
        "",
        "## MFE・MAE解析",
        "",
        "| 評価期間 | MFE中央値 | MAE中央値 | -3%逆行率 | +5%到達率 |",
        "|---:|---:|---:|---:|---:|",
    ]
    for window in EXCURSION_WINDOWS:
        lines.append(
            f"| {window}営業日 | {_percent(summary[f'median_mfe_{window}d_pct'])} | "
            f"{_percent(summary[f'median_mae_{window}d_pct'])} | "
            f"{_percent(summary[f'adverse_3pct_rate_{window}d_pct'])} | "
            f"{_percent(summary[f'reach_5pct_rate_{window}d_pct'])} |"
        )
    lines.extend([
        "",
        "## 成績",
        "",
        "| 売却時期 | 評価可能件数 | 勝率 | 平均損益率 | 合計損益 |",
        "|---:|---:|---:|---:|---:|",
    ])
    for horizon in HORIZONS:
        lines.append(
            f"| {horizon}営業日後 | {summary[f'completed_{horizon}d']} | "
            f"{_percent(summary[f'win_rate_{horizon}d_pct'])} | "
            f"{_percent(summary[f'average_return_{horizon}d_pct'])} | "
            f"{_price(summary[f'total_profit_loss_{horizon}d'])} |"
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
    lines = [
        "# A8バックテスト 個別結果",
        "",
        f"対象期間: {summary['start_date']} ～ {summary['end_date']}",
        "",
    ]
    if trades.empty:
        lines.extend(["エントリー対象銘柄はありませんでした。", ""])
        return "\n".join(lines)

    for _, row in trades.iterrows():
        lines.extend([
            f"## {row['entry_date']} {row['name']} ({row['code']})",
            "",
            f"- 乖離判定日: {row['signal_date']}",
            f"- 前日終値: {_price(row['previous_close'])}",
            f"- 前日MA25: {_price(row['previous_ma25'])}",
            f"- 前日25日乖離率: {_percent(row['previous_dev25_pct'])}",
            f"- 直近3日の安値切り下げ回数: {int(row['lower_low_count_3d'])}回",
            f"- エントリー時刻: {_entry_label(row['entry_time'])}",
            f"- VWAP維持確認: {'あり' if row['vwap_confirmation_required'] else 'なし'}",
            f"- 買値: {_price(row['entry_price'])}",
            f"- 終端位置: {_percent(row.get('entry_range_position_pct'))}",
            f"- 当日暫定MA5: {_price(row.get('entry_ma5'))}",
            f"- 5日線傾き: {_percent(row.get('ma5_slope_pct'))}",
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
            "| 評価期間 | 最高値 | MFE | 最低値 | 最大含み損 | MAE |",
            "|---:|---:|---:|---:|---:|---:|",
        ])
        for window in EXCURSION_WINDOWS:
            lines.append(
                f"| {window}営業日 | {_price(row[f'maximum_price_{window}d'])} | "
                f"{_percent(row[f'max_favorable_excursion_{window}d_pct'])} | "
                f"{_price(row[f'minimum_price_{window}d'])} | "
                f"{_price(row[f'max_drawdown_{window}d'])} | {_percent(row[f'max_drawdown_{window}d_pct'])} |"
            )
        lines.append("")
    return "\n".join(lines)


def _entry_label(value: str) -> str:
    return "前日終値" if value == "prev_close" else value


def _range_condition(value) -> str:
    return "考慮せず" if value is None or pd.isna(value) else f"{float(value):g}%以上"


def _price(value) -> str:
    return "N/A" if value is None or pd.isna(value) else f"{float(value):,.2f}円"


def _percent(value) -> str:
    return "N/A" if value is None or pd.isna(value) else f"{float(value):.2f}%"
