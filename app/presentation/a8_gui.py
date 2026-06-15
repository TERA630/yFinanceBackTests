"""Single-window input form for the A8 backtest."""

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

from app.domain.vwap_backtest import A8BacktestConfig, ENTRY_1100, ENTRY_1400, ENTRY_PREV_CLOSE
from app.presentation.a8_settings import load_watchlist_path, save_watchlist_path


@dataclass(frozen=True)
class A8GuiInput:
    stock_file: Path
    output_dir: Path
    config: A8BacktestConfig


def default_date_range(now: Optional[pd.Timestamp] = None) -> tuple[pd.Timestamp, pd.Timestamp]:
    today = pd.Timestamp.now().normalize() if now is None else pd.Timestamp(now).normalize()
    end_date = pd.bdate_range(end=today, periods=1)[0]
    start_date = pd.bdate_range(end=end_date, periods=41)[0]
    return pd.Timestamp(start_date), pd.Timestamp(end_date)


def request_a8_backtest_input() -> Optional[A8GuiInput]:
    if tk is None or ttk is None or DateEntry is None:
        raise RuntimeError("tkinter と tkcalendar が必要です。")

    result: dict[str, Optional[A8GuiInput]] = {"value": None}
    win = tk.Tk()
    win.title("A8 バックテスト条件設定")
    win.geometry("650x550")
    win.resizable(False, False)

    frame = ttk.Frame(win, padding=18)
    frame.pack(fill=tk.BOTH, expand=True)
    remembered_watchlist = load_watchlist_path()
    stock_var = tk.StringVar(value=str(remembered_watchlist) if remembered_watchlist else "")
    output_var = tk.StringVar(value=str(remembered_watchlist.parent) if remembered_watchlist else "")
    min_var = tk.StringVar(value="-5.0")
    max_var = tk.StringVar(value="5.0")
    entry_var = tk.StringVar(value=ENTRY_1100)
    require_vwap_var = tk.BooleanVar(value=True)
    lower_low_var = tk.StringVar(value="0回")
    default_start, default_end = default_date_range()

    ttk.Label(frame, text="開始日").grid(row=0, column=0, sticky="w", pady=6)
    start_entry = DateEntry(frame, width=14, date_pattern="yyyy-mm-dd", locale="ja_JP")
    start_entry.set_date(default_start.date())
    start_entry.grid(row=0, column=1, sticky="w")

    ttk.Label(frame, text="終了日").grid(row=1, column=0, sticky="w", pady=6)
    end_entry = DateEntry(frame, width=14, date_pattern="yyyy-mm-dd", locale="ja_JP")
    end_entry.set_date(default_end.date())
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

    ttk.Checkbutton(
        frame,
        text="VWAP維持を確認してからエントリー",
        variable=require_vwap_var,
    ).grid(row=6, column=0, columnspan=2, sticky="w", pady=6)

    ttk.Label(frame, text="エントリー時刻").grid(row=7, column=0, sticky="w", pady=6)
    entry_box = ttk.Combobox(
        frame,
        textvariable=entry_var,
        values=("前日終値", ENTRY_1100, ENTRY_1400),
        state="readonly",
        width=14,
    )
    entry_box.grid(row=7, column=1, sticky="w")

    ttk.Label(frame, text="3日間の安値切り下げ除外").grid(row=8, column=0, sticky="w", pady=6)
    ttk.Combobox(
        frame,
        textvariable=lower_low_var,
        values=("0回", "1回", "2回", "3回"),
        state="readonly",
        width=14,
    ).grid(row=8, column=1, sticky="w")

    help_var = tk.StringVar()
    help_label = ttk.Label(
        frame,
        textvariable=help_var,
        foreground="#555555",
    )
    help_label.grid(row=9, column=0, columnspan=3, sticky="w", pady=(10, 16))

    def update_vwap_controls() -> None:
        if require_vwap_var.get():
            entry_box.configure(values=("前日終値", ENTRY_1100, ENTRY_1400))
            help_var.set(
                "指定時刻にVWAP維持を確認し、維持している場合だけエントリーします。\n"
                "安値切り下げは、指定回数以上の銘柄を除外します（0回は除外なし）。"
            )
        else:
            entry_box.configure(values=(ENTRY_1100, ENTRY_1400))
            if entry_var.get() in ("前日終値", ENTRY_PREV_CLOSE):
                entry_var.set(ENTRY_1100)
            help_var.set(
                "VWAPとの位置関係を判定せず、11時または14時の価格でエントリーします。\n"
                "安値切り下げは、指定回数以上の銘柄を除外します（0回は除外なし）。"
            )

    require_vwap_var.trace_add("write", lambda *_: update_vwap_controls())
    update_vwap_controls()

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
            config = A8BacktestConfig(
                start_date=start_entry.get_date().strftime("%Y-%m-%d"),
                end_date=end_entry.get_date().strftime("%Y-%m-%d"),
                dev25_min=float(min_var.get()),
                dev25_max=float(max_var.get()),
                entry_time=entry_time,
                lower_low_exclude_count=int(lower_low_var.get().removesuffix("回")),
                require_vwap_confirmation=require_vwap_var.get(),
            )
            config.validate()
            oldest = pd.Timestamp.now().normalize() - pd.Timedelta(days=59)
            if pd.Timestamp(config.start_date) < oldest:
                raise ValueError(f"開始日は {oldest.strftime('%Y-%m-%d')} 以降にしてください。")
            if pd.Timestamp(config.end_date) > pd.Timestamp.now().normalize():
                raise ValueError("終了日に未来の日付は指定できません。")
            save_watchlist_path(stock_file)
            result["value"] = A8GuiInput(stock_file, output_dir, config)
            win.destroy()
        except (OSError, ValueError) as exc:
            messagebox.showerror("入力エラー", str(exc))

    buttons = ttk.Frame(frame)
    buttons.grid(row=10, column=0, columnspan=3, pady=8)
    ttk.Button(buttons, text="実行", width=14, command=submit).pack(side=tk.LEFT, padx=8)
    ttk.Button(buttons, text="キャンセル", width=14, command=win.destroy).pack(side=tk.LEFT, padx=8)
    if remembered_watchlist is None:
        win.after(100, browse_stock)
    win.mainloop()
    return result["value"]


def show_a8_completion(summary_path: Path, result_path: Path) -> None:
    if tk is None or messagebox is None:
        return
    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo("完了", f"A8バックテストが完了しました。\n\n{summary_path}\n{result_path}")
    root.destroy()
