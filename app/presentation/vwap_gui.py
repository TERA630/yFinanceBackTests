"""Single-window GUI for the VWAP backtest."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from tkcalendar import DateEntry
except Exception:
    tk = None
    filedialog = None
    messagebox = None
    ttk = None
    DateEntry = None

from app.domain.vwap_backtest import ENTRY_1100, ENTRY_1400, ENTRY_PREV_CLOSE, VwapBacktestConfig


@dataclass(frozen=True)
class VwapGuiInput:
    stock_file: Path
    output_dir: Path
    config: VwapBacktestConfig


def request_vwap_backtest_input() -> Optional[VwapGuiInput]:
    if tk is None or DateEntry is None or ttk is None:
        raise RuntimeError("tkinter と tkcalendar が必要です。")

    result: dict[str, Optional[VwapGuiInput]] = {"value": None}
    win = tk.Tk()
    win.title("VWAP維持・25日線基準バックテスト")
    win.geometry("610x430")
    win.resizable(False, False)

    frame = ttk.Frame(win, padding=18)
    frame.pack(fill=tk.BOTH, expand=True)
    stock_var = tk.StringVar()
    output_var = tk.StringVar()
    min_var = tk.StringVar(value="-5.0")
    max_var = tk.StringVar(value="5.0")
    entry_var = tk.StringVar(value="11:00")

    ttk.Label(frame, text="開始日").grid(row=0, column=0, sticky="w", pady=6)
    start_entry = DateEntry(frame, width=14, date_pattern="yyyy-mm-dd", locale="ja_JP")
    start_entry.set_date((pd.Timestamp.now() - pd.Timedelta(days=30)).date())
    start_entry.grid(row=0, column=1, sticky="w")

    ttk.Label(frame, text="終了日").grid(row=1, column=0, sticky="w", pady=6)
    end_entry = DateEntry(frame, width=14, date_pattern="yyyy-mm-dd", locale="ja_JP")
    end_entry.set_date(pd.Timestamp.now().date())
    end_entry.grid(row=1, column=1, sticky="w")

    ttk.Label(frame, text="監視銘柄ファイル").grid(row=2, column=0, sticky="w", pady=6)
    ttk.Entry(frame, textvariable=stock_var, width=48).grid(row=2, column=1, sticky="w")

    def browse_stock() -> None:
        path = filedialog.askopenfilename(
            title="監視銘柄ファイルを選択",
            filetypes=[("Markdown files", "*.md"), ("All files", "*.*")],
        )
        if path:
            stock_var.set(path)
            if not output_var.get():
                output_var.set(str(Path(path).parent))

    ttk.Button(frame, text="参照", command=browse_stock).grid(row=2, column=2, padx=(8, 0))

    ttk.Label(frame, text="出力先フォルダ").grid(row=3, column=0, sticky="w", pady=6)
    ttk.Entry(frame, textvariable=output_var, width=48).grid(row=3, column=1, sticky="w")

    def browse_output() -> None:
        path = filedialog.askdirectory(title="出力先フォルダを選択")
        if path:
            output_var.set(path)

    ttk.Button(frame, text="参照", command=browse_output).grid(row=3, column=2, padx=(8, 0))

    ttk.Label(frame, text="25日乖離率 最低値 (%)").grid(row=4, column=0, sticky="w", pady=6)
    ttk.Entry(frame, textvariable=min_var, width=16).grid(row=4, column=1, sticky="w")
    ttk.Label(frame, text="最低値 < 乖離率 <= 最高値").grid(row=4, column=1, sticky="w", padx=(140, 0))

    ttk.Label(frame, text="25日乖離率 最高値 (%)").grid(row=5, column=0, sticky="w", pady=6)
    ttk.Entry(frame, textvariable=max_var, width=16).grid(row=5, column=1, sticky="w")

    ttk.Label(frame, text="VWAP維持判定").grid(row=6, column=0, sticky="w", pady=6)
    entry_box = ttk.Combobox(
        frame,
        textvariable=entry_var,
        values=("前日終値", ENTRY_1100, ENTRY_1400),
        state="readonly",
        width=14,
    )
    entry_box.grid(row=6, column=1, sticky="w")

    ttk.Label(
        frame,
        text="前日・当日の25日乖離率が基準範囲内、かつ25日線が横ばい以上。\n"
             "さらに指定時刻価格が累積VWAP以上なら買付。",
        foreground="#555555",
    ).grid(row=7, column=0, columnspan=3, sticky="w", pady=(10, 16))

    def submit() -> None:
        try:
            stock_file = Path(stock_var.get().strip())
            output_dir = Path(output_var.get().strip())
            if not stock_file.is_file():
                raise ValueError("監視銘柄ファイルを選択してください。")
            if not output_var.get().strip():
                raise ValueError("出力先フォルダを選択してください。")
            selected = entry_var.get()
            entry_time = ENTRY_PREV_CLOSE if selected == "前日終値" else selected
            config = VwapBacktestConfig(
                start_date=start_entry.get_date().strftime("%Y-%m-%d"),
                end_date=end_entry.get_date().strftime("%Y-%m-%d"),
                dev25_min=float(min_var.get()),
                dev25_max=float(max_var.get()),
                entry_time=entry_time,
            )
            config.validate()
            oldest = pd.Timestamp.now().normalize() - pd.Timedelta(days=59)
            if pd.Timestamp(config.start_date) < oldest:
                raise ValueError(f"開始日は {oldest.strftime('%Y-%m-%d')} 以降にしてください。")
            if pd.Timestamp(config.end_date) > pd.Timestamp.now().normalize():
                raise ValueError("終了日に未来の日付は指定できません。")
            result["value"] = VwapGuiInput(stock_file, output_dir, config)
            win.destroy()
        except ValueError as exc:
            messagebox.showerror("入力エラー", str(exc))

    buttons = ttk.Frame(frame)
    buttons.grid(row=8, column=0, columnspan=3, pady=8)
    ttk.Button(buttons, text="実行", width=14, command=submit).pack(side=tk.LEFT, padx=8)
    ttk.Button(buttons, text="キャンセル", width=14, command=win.destroy).pack(side=tk.LEFT, padx=8)
    win.mainloop()
    return result["value"]


def show_vwap_completion(summary_path: Path, result_path: Path) -> None:
    if tk is None or messagebox is None:
        return
    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo("完了", f"バックテストが完了しました。\n\n{summary_path}\n{result_path}")
    root.destroy()
