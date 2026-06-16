"""Single-window input form for the A8 backtest."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

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


def append_saved_condition(queue: list[A8GuiInput], gui_input: A8GuiInput, limit: int = 3) -> None:
    queue.append(gui_input)
    del queue[:-limit]


def summarize_condition(gui_input: A8GuiInput) -> str:
    config = gui_input.config
    vwap_label = "VWAPあり" if config.require_vwap_confirmation else "VWAPなし"
    entry_label = "前日終値" if config.entry_time == ENTRY_PREV_CLOSE else config.entry_time
    lower_low_label = (
        "安値除外なし"
        if config.lower_low_exclude_count == 0
        else f"安値{config.lower_low_exclude_count}回以上除外"
    )
    return (
        f"25日乖離 {config.dev25_min:g}%超-{config.dev25_max:g}%以下 / "
        f"{vwap_label} / {entry_label} / {lower_low_label}"
    )


def default_date_range(now: Optional[pd.Timestamp] = None) -> tuple[pd.Timestamp, pd.Timestamp]:
    today = pd.Timestamp.now().normalize() if now is None else pd.Timestamp(now).normalize()
    end_date = pd.bdate_range(end=today, periods=1)[0]
    start_date = pd.bdate_range(end=end_date, periods=41)[0]
    return pd.Timestamp(start_date), pd.Timestamp(end_date)


def request_a8_backtest_input() -> Optional[list[A8GuiInput]]:
    if tk is None or ttk is None or DateEntry is None:
        raise RuntimeError("tkinter と tkcalendar が必要です。")

    result: dict[str, Optional[list[A8GuiInput]]] = {"value": None}
    win = tk.Tk()
    win.title("A8 バックテスト条件設定")
    win.geometry("720x650")
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

    saved_queue: list[A8GuiInput] = []
    saved_count_var = tk.StringVar(value="保存済み条件: 0件")

    ttk.Label(frame, text="保存済み条件").grid(row=10, column=0, sticky="nw", pady=(8, 4))
    queue_list = tk.Listbox(frame, width=78, height=3)
    queue_list.grid(row=10, column=1, columnspan=2, sticky="w", pady=(8, 4))
    ttk.Label(frame, textvariable=saved_count_var, foreground="#555555").grid(
        row=11, column=1, columnspan=2, sticky="w", pady=(0, 8)
    )

    def refresh_queue_list() -> None:
        queue_list.delete(0, tk.END)
        for index, gui_input in enumerate(saved_queue, start=1):
            queue_list.insert(tk.END, f"{index}. {summarize_condition(gui_input)}")
        saved_count_var.set(f"保存済み条件: {len(saved_queue)}件")

    def build_input_from_form() -> A8GuiInput:
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
        return A8GuiInput(stock_file, output_dir, config)

    def save_condition() -> None:
        try:
            append_saved_condition(saved_queue, build_input_from_form())
            refresh_queue_list()
        except (OSError, ValueError) as exc:
            messagebox.showerror("入力エラー", str(exc))

    def clear_conditions() -> None:
        saved_queue.clear()
        refresh_queue_list()

    def submit() -> None:
        try:
            result["value"] = [build_input_from_form()]
            win.destroy()
        except (OSError, ValueError) as exc:
            messagebox.showerror("入力エラー", str(exc))

    def submit_queue() -> None:
        if not saved_queue:
            messagebox.showinfo("連続実行", "保存済み条件がありません。")
            return
        result["value"] = list(saved_queue)
        win.destroy()

    buttons = ttk.Frame(frame)
    buttons.grid(row=12, column=0, columnspan=3, pady=8)
    ttk.Button(buttons, text="条件保存", width=14, command=save_condition).pack(side=tk.LEFT, padx=6)
    ttk.Button(buttons, text="実行", width=14, command=submit).pack(side=tk.LEFT, padx=8)
    ttk.Button(buttons, text="連続実行", width=14, command=submit_queue).pack(side=tk.LEFT, padx=6)
    ttk.Button(buttons, text="キュークリア", width=14, command=clear_conditions).pack(side=tk.LEFT, padx=6)
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


def show_a8_batch_completion(
    outputs: Sequence[tuple[Path, Path]],
    errors: Sequence[tuple[A8GuiInput, Exception]],
) -> None:
    if tk is None or messagebox is None:
        return
    root = tk.Tk()
    root.withdraw()
    lines = [f"A8バックテストが完了しました。成功: {len(outputs)}件 / エラー: {len(errors)}件"]
    for index, (summary_path, result_path) in enumerate(outputs, start=1):
        lines.append("")
        lines.append(f"[成功 {index}]")
        lines.append(str(summary_path))
        lines.append(str(result_path))
    for index, (gui_input, exc) in enumerate(errors, start=1):
        lines.append("")
        lines.append(f"[エラー {index}] {summarize_condition(gui_input)}")
        lines.append(str(exc))
    messagebox.showinfo("完了", "\n".join(lines))
    root.destroy()
