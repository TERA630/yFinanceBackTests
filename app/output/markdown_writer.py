"""Markdown reports for VWAP backtest results."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from app.domain.vwap_backtest import HORIZONS


def save_vwap_reports(out_dir: Path, trades: pd.DataFrame, summary: dict) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%m-%d-%H-%M")
    summary_path = out_dir / f"backtest_Summary-{timestamp}.md"
    result_path = out_dir / f"backtest_result--{timestamp}.md"
    summary_path.write_text(_summary_markdown(summary), encoding="utf-8")
    result_path.write_text(_result_markdown(trades, summary), encoding="utf-8")
    return summary_path, result_path


def _summary_markdown(summary: dict) -> str:
    lines = [
        "# VWAP維持・25日線基準バックテスト サマリー",
        "",
        "## 実行条件",
        "",
        f"- 乖離判定期間: {summary['start_date']} ～ {summary['end_date']}",
        f"- 前日・当日25日乖離率: {summary['dev25_min']}% < 乖離率 <= {summary['dev25_max']}%",
        "- 25日線傾き: 横ばい以上（0%以上）",
        f"- VWAP維持判定・エントリー時刻: {_entry_label(summary['entry_time'])}",
        f"- 監視銘柄数: {summary['stock_count']}",
        f"- 評価件数: {summary['evaluated_count']}",
        f"- エントリー件数: {summary['entry_count']}",
        "",
        "## 主要指標（5営業日）",
        "",
        f"- 5営業日後リターン: {_percent(summary['average_return_5d_pct'])}",
        f"- 最大含み損 平均: {_percent(summary['average_max_drawdown_5d_pct'])}",
        f"- 最大含み損 中央値: {_percent(summary['median_max_drawdown_5d_pct'])}",
        f"- -3%逆行率: {_percent(summary['adverse_3pct_rate_5d_pct'])}",
        "",
        "## 成績",
        "",
        "| 売却時期 | 評価可能件数 | 勝率 | 平均損益率 | 合計損益 |",
        "|---:|---:|---:|---:|---:|",
    ]
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
        "# VWAP維持・25日線基準バックテスト 個別結果",
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
            f"- 判定時刻: {_entry_label(row['entry_time'])}",
            f"- 買値: {_price(row['entry_price'])}",
            f"- 当日暫定MA25: {_price(row['entry_ma25'])}",
            f"- 当日25日乖離率: {_percent(row['entry_dev25_pct'])}",
            f"- 25日線傾き: {_percent(row['ma25_slope_pct'])}",
            f"- 累積VWAP: {_price(row['vwap'])}",
            f"- VWAP上方率: {_percent(row['vwap_margin_pct'])}",
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
            "| 評価期間 | 最低値 | 最大含み損 | 最大含み損率 |",
            "|---:|---:|---:|---:|",
        ])
        for window in (5, 20):
            lines.append(
                f"| {window}営業日 | {_price(row[f'minimum_price_{window}d'])} | "
                f"{_price(row[f'max_drawdown_{window}d'])} | {_percent(row[f'max_drawdown_{window}d_pct'])} |"
            )
        lines.append("")
    return "\n".join(lines)


def _entry_label(value: str) -> str:
    return "前日終値" if value == "prev_close" else value


def _price(value) -> str:
    return "N/A" if value is None or pd.isna(value) else f"{float(value):,.2f}円"


def _percent(value) -> str:
    return "N/A" if value is None or pd.isna(value) else f"{float(value):.2f}%"
