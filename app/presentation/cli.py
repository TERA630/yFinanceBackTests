"""CLI argument parsing and input resolution."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional, Tuple

from app.presentation.gui import select_date_range, select_output_dir, select_stock_file


def build_parser():
    p = argparse.ArgumentParser(description="A7R 条件 Aバックテスト: V7厳選 + 最小限の現代化")
    p.add_argument("--stock-md", help="監視銘柄の markdown ファイルパス")
    p.add_argument("--start", help="開始日 YYYY-MM-DD")
    p.add_argument("--end", help="終了日 YYYY-MM-DD")
    p.add_argument("--out-dir", help="出力先フォルダ")
    p.add_argument(
        "--lower-low-exclude-count",
        type=int,
        choices=(0, 1, 2, 3),
        default=0,
        help="直近3日間の安値切り下げが指定回数以上なら除外（0は無効）",
    )
    p.add_argument("--gui", action="store_true", help="GUIでファイル・日付を選ぶ")
    return p


def resolve_inputs(args) -> Optional[Tuple[Path, str, str, Path, int]]:
    use_gui = args.gui or not (args.stock_md and args.start and args.end)

    if use_gui:
        stock_md_path = select_stock_file()
        if stock_md_path is None:
            return None
        date_range = select_date_range()
        if date_range is None:
            return None
        start_date, end_date, lower_low_exclude_count = date_range
        out_dir = select_output_dir(stock_md_path.parent)
        if out_dir is None:
            return None
        return stock_md_path, start_date, end_date, out_dir, lower_low_exclude_count

    stock_md_path = Path(args.stock_md)
    start_date = args.start
    end_date = args.end
    out_dir = Path(args.out_dir) if args.out_dir else stock_md_path.parent
    return stock_md_path, start_date, end_date, out_dir, args.lower_low_exclude_count
