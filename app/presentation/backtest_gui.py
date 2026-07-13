"""Single-window input form for the A11 backtest."""

from __future__ import annotations

from dataclasses import dataclass, replace
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

from app.domain.vwap_backtest import (
    VwapBacktestConfig,
    ENTRY_1100,
    ENTRY_1400,
    ENTRY_OPEN,
    ENTRY_PREV_CLOSE,
    MA25_NEGATIVE_SLOPE_REJECT,
    MA25_NEGATIVE_SLOPE_REJECT_NEGATIVE_OR_SLOWDOWN_5D,
    MA25_NEGATIVE_SLOPE_REJECT_SLOWDOWN_5D,
    MA25_NEGATIVE_SLOPE_SCORE,
    MA5_SLOWDOWN_ALLOW_ONE,
    MA5_SLOWDOWN_ALLOW_PREVIOUS_DAY,
    MA5_SLOWDOWN_ALLOW_THREE_DAYS_AGO,
    MA5_SLOWDOWN_IGNORE,
    MA5_SLOWDOWN_REJECT_ANY,
    requires_intraday_prices,
)
from app.data.settings_store import load_watchlist_path, save_watchlist_path


MA5_SLOWDOWN_LABELS = {
    MA5_SLOWDOWN_IGNORE: "考慮しない",
    MA5_SLOWDOWN_REJECT_ANY: "前日・3日前とも許容しない",
    MA5_SLOWDOWN_ALLOW_ONE: "前日・3日前のいずれかのみ許容",
    MA5_SLOWDOWN_ALLOW_THREE_DAYS_AGO: "3日前のみ許容",
    MA5_SLOWDOWN_ALLOW_PREVIOUS_DAY: "前日のみ許容",
}
MA5_SLOWDOWN_VALUES = {label: value for value, label in MA5_SLOWDOWN_LABELS.items()}
LOWER_LOW_LABELS = {
    0: "考慮しない",
    2: "3日のうち2回安値切下げ",
    3: "3日連続安値切下げ",
}
LOWER_LOW_VALUES = {label: value for value, label in LOWER_LOW_LABELS.items()}
MA25_NEGATIVE_SLOPE_LABELS = {
    MA25_NEGATIVE_SLOPE_REJECT: "傾き負を即除外",
    MA25_NEGATIVE_SLOPE_SCORE: "即除外しない",
    MA25_NEGATIVE_SLOPE_REJECT_SLOWDOWN_5D: "5日前より傾き鈍化除外",
    MA25_NEGATIVE_SLOPE_REJECT_NEGATIVE_OR_SLOWDOWN_5D: "傾き鈍化、傾き負いずれも除外",
}
MA25_NEGATIVE_SLOPE_VALUES = {label: value for value, label in MA25_NEGATIVE_SLOPE_LABELS.items()}
BREAKDOWN_SCORE_VALUES = {
    "考慮しない": None,
    "3点以上": 3,
    "4点以上": 4,
    "5点以上": 5,
}
MA25_DEVIATION_RANGES = ((-2.0, 0.0), (0.0, 2.0), (2.0, 4.0), (4.0, 6.0), (6.0, 8.0), (8.0, 10.0), (10.0, 12.0))


@dataclass(frozen=True)
class BacktestGuiInput:
    stock_file: Path
    output_dir: Path
    config: VwapBacktestConfig


def append_saved_condition(
    queue: list[BacktestGuiInput],
    gui_input: BacktestGuiInput,
    limit: int = 8,
) -> None:
    queue.append(gui_input)
    del queue[:-limit]


def append_ma25_conditions(
    queue: list[BacktestGuiInput],
    gui_input: BacktestGuiInput,
    limit: int = 8,
) -> None:
    for dev25_min, dev25_max in MA25_DEVIATION_RANGES:
        append_saved_condition(
            queue,
            replace(
                gui_input,
                config=replace(gui_input.config, dev25_min=dev25_min, dev25_max=dev25_max),
            ),
            limit,
        )


def summarize_condition(gui_input: BacktestGuiInput) -> str:
    config = gui_input.config
    entry_label = _entry_label(config.entry_time)
    lower_low_label = f"安値切下げ:{LOWER_LOW_LABELS.get(config.lower_low_exclude_count, '考慮しない')}"
    higher_high_label = (
        "高値更新考慮なし"
        if config.higher_high_exclude_count == 0
        else f"高値更新{config.higher_high_exclude_count}回以上"
    )
    range_label = (
        f"{_range_position_label(config.entry_time)}考慮せず"
        if config.range_position_min_pct is None
        else f"{_range_position_label(config.entry_time)}{config.range_position_min_pct:g}%以上"
    )
    ma5_label = "5日線上向き" if config.require_ma5_slope_positive else "5日線条件なし"
    ma5_slowdown_label = MA5_SLOWDOWN_LABELS.get(config.ma5_slope_slowdown_policy, "考慮しない")
    ma25_slope_label = MA25_NEGATIVE_SLOPE_LABELS.get(config.ma25_negative_slope_policy, "傾き負を即除外")
    breakdown_label = (
        "崩れスコア考慮なし"
        if config.breakdown_score_threshold is None
        else f"崩れスコア{config.breakdown_score_threshold}点以上除外"
    )
    support_label = (
        "支持線距離考慮なし"
        if config.support_distance_max_atr is None
        else f"支持線距離{config.support_distance_max_atr:g}ATR以内"
    )
    return (
        f"25日乖離 {config.dev25_min:g}%超-{config.dev25_max:g}%以下 / "
        f"{entry_label} / {lower_low_label} / {higher_high_label} / {range_label} / "
        f"{support_label} / {ma5_label} / 5日線鈍化:{ma5_slowdown_label} / "
        f"25日線傾き:{ma25_slope_label} / "
        f"{breakdown_label}"
    )


def default_date_range(now: Optional[pd.Timestamp] = None) -> tuple[pd.Timestamp, pd.Timestamp]:
    today = pd.Timestamp.now().normalize() if now is None else pd.Timestamp(now).normalize()
    end_date = pd.offsets.BDay().rollback(today)
    start_date = pd.offsets.BDay().rollforward(today - pd.Timedelta(days=59))
    return pd.Timestamp(start_date), pd.Timestamp(end_date)


def _entry_label(value: str) -> str:
    labels = {
        ENTRY_PREV_CLOSE: "日足:前日終値",
        ENTRY_OPEN: "日足:翌営業日始値",
        ENTRY_1100: "日中足:11:00",
        ENTRY_1400: "日中足:14:00",
    }
    return labels.get(value, value)


def _range_position_label(entry_time: str) -> str:
    if entry_time in (ENTRY_1100, ENTRY_1400):
        return "終端位置"
    return "終値位置"


def request_backtest_inputs() -> Optional[list[BacktestGuiInput]]:
    if tk is None or ttk is None or DateEntry is None:
        raise RuntimeError("tkinter と tkcalendar が必要です。")

    result: dict[str, Optional[list[BacktestGuiInput]]] = {"value": None}
    win = tk.Tk()
    win.title("A11 バックテスト条件設定")
    win.geometry("760x850")
    win.resizable(False, False)

    frame = ttk.Frame(win, padding=18)
    frame.pack(fill=tk.BOTH, expand=True)
    remembered_watchlist = load_watchlist_path()
    stock_var = tk.StringVar(value=str(remembered_watchlist) if remembered_watchlist else "")
    min_var = tk.StringVar(value="-5.0")
    max_var = tk.StringVar(value="5.0")
    entry_mode_var = tk.StringVar(value="daily")
    daily_entry_var = tk.StringVar(value="翌営業日始値")
    intraday_entry_var = tk.StringVar(value=ENTRY_1100)
    lower_low_var = tk.StringVar(value=LOWER_LOW_LABELS[0])
    higher_high_var = tk.StringVar(value="考慮しない")
    range_position_var = tk.StringVar(value="考慮せず")
    require_ma5_slope_var = tk.BooleanVar(value=False)
    ma5_slowdown_var = tk.StringVar(value=MA5_SLOWDOWN_LABELS[MA5_SLOWDOWN_IGNORE])
    ma25_negative_slope_var = tk.StringVar(value=MA25_NEGATIVE_SLOPE_LABELS[MA25_NEGATIVE_SLOPE_REJECT])
    breakdown_score_var = tk.StringVar(value="5点以上")
    default_start, default_end = default_date_range()

    date_frame = ttk.Frame(frame)
    date_frame.grid(row=0, column=0, columnspan=3, sticky="w", pady=6)

    ttk.Label(date_frame, text="開始日").grid(row=0, column=0, sticky="w")
    start_entry = DateEntry(date_frame, width=14, date_pattern="yyyy-mm-dd", locale="ja_JP")
    start_entry.set_date(default_start.date())
    start_entry.grid(row=0, column=1, sticky="w")

    ttk.Label(date_frame, text="終了日").grid(row=0, column=2, sticky="w", padx=(16, 0))
    end_entry = DateEntry(date_frame, width=14, date_pattern="yyyy-mm-dd", locale="ja_JP")
    end_entry.set_date(default_end.date())
    end_entry.grid(row=0, column=3, sticky="w")

    ttk.Label(frame, text="監視銘柄ファイル").grid(row=2, column=0, sticky="w", pady=6)
    ttk.Entry(frame, textvariable=stock_var, width=48).grid(row=2, column=1, sticky="w")

    def browse_stock() -> None:
        path = filedialog.askopenfilename(
            title="監視銘柄ファイルを選択",
            filetypes=[("Markdown files", "*.md"), ("All files", "*.*")],
        )
        if path:
            stock_var.set(path)

    ttk.Button(frame, text="参照", command=browse_stock).grid(row=2, column=2, padx=(8, 0))

    ttk.Label(frame, text="25日乖離率 最低値 (%)").grid(row=4, column=0, sticky="w", pady=6)
    ttk.Entry(frame, textvariable=min_var, width=16).grid(row=4, column=1, sticky="w")
    ttk.Label(frame, text="最低値 < 乖離率 <= 最高値").grid(row=4, column=1, sticky="w", padx=(140, 0))

    ttk.Label(frame, text="25日乖離率 最高値 (%)").grid(row=5, column=0, sticky="w", pady=6)
    ttk.Entry(frame, textvariable=max_var, width=16).grid(row=5, column=1, sticky="w")

    entry_frame = ttk.LabelFrame(frame, text="エントリー条件")
    entry_frame.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(8, 6))
    entry_frame.columnconfigure(1, weight=1)

    ttk.Radiobutton(
        entry_frame,
        text="日足",
        variable=entry_mode_var,
        value="daily",
    ).grid(row=0, column=0, sticky="w", padx=10, pady=6)
    ttk.Combobox(
        entry_frame,
        textvariable=daily_entry_var,
        values=("翌営業日始値", "前日終値"),
        state="readonly",
        width=16,
    ).grid(row=0, column=1, sticky="w", padx=10, pady=6)

    ttk.Radiobutton(
        entry_frame,
        text="日中足（5分足）",
        variable=entry_mode_var,
        value="intraday",
    ).grid(row=1, column=0, sticky="w", padx=10, pady=6)
    ttk.Combobox(
        entry_frame,
        textvariable=intraday_entry_var,
        values=(ENTRY_1100, ENTRY_1400),
        state="readonly",
        width=16,
    ).grid(row=1, column=1, sticky="w", padx=10, pady=6)

    exclusion_frame = ttk.LabelFrame(frame, text="日足条件")
    exclusion_frame.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(10, 6))
    exclusion_frame.columnconfigure(1, weight=1)

    ttk.Label(exclusion_frame, text="3日間の安値切り下げ").grid(row=0, column=0, sticky="w", padx=10, pady=6)
    ttk.Combobox(
        exclusion_frame,
        textvariable=lower_low_var,
        values=tuple(LOWER_LOW_VALUES.keys()),
        state="readonly",
        width=26,
    ).grid(row=0, column=1, sticky="w", padx=10, pady=6)

    range_position_label_var = tk.StringVar(value="終端位置")
    ttk.Label(exclusion_frame, textvariable=range_position_label_var).grid(
        row=1, column=0, sticky="w", padx=10, pady=6
    )
    range_position_box = ttk.Combobox(
        exclusion_frame,
        textvariable=range_position_var,
        values=("考慮せず", "30%以上", "40%以上", "50%以上", "60%以上"),
        state="readonly",
        width=14,
    )
    range_position_box.grid(row=1, column=1, sticky="w", padx=10, pady=6)

    ttk.Label(exclusion_frame, text="3日間の高値更新条件").grid(row=2, column=0, sticky="w", padx=10, pady=6)
    ttk.Combobox(
        exclusion_frame,
        textvariable=higher_high_var,
        values=("考慮しない", "1回以上", "2回以上", "3回"),
        state="readonly",
        width=14,
    ).grid(row=2, column=1, sticky="w", padx=10, pady=6)

    ttk.Checkbutton(
        exclusion_frame,
        text="5日線傾き > 0 を条件にする",
        variable=require_ma5_slope_var,
    ).grid(row=4, column=0, columnspan=2, sticky="w", padx=10, pady=6)

    ttk.Label(exclusion_frame, text="5日線傾き鈍化").grid(row=5, column=0, sticky="w", padx=10, pady=6)
    ttk.Combobox(
        exclusion_frame,
        textvariable=ma5_slowdown_var,
        values=tuple(MA5_SLOWDOWN_VALUES.keys()),
        state="readonly",
        width=30,
    ).grid(row=5, column=1, sticky="w", padx=10, pady=6)

    ttk.Label(exclusion_frame, text="25日線傾き").grid(row=6, column=0, sticky="w", padx=10, pady=6)
    ttk.Combobox(
        exclusion_frame,
        textvariable=ma25_negative_slope_var,
        values=tuple(MA25_NEGATIVE_SLOPE_VALUES.keys()),
        state="readonly",
        width=32,
    ).grid(row=6, column=1, sticky="w", padx=10, pady=6)

    score_frame = ttk.LabelFrame(frame, text="日中足条件（5分足）")
    score_frame.grid(row=8, column=0, columnspan=3, sticky="ew", pady=6)
    score_frame.columnconfigure(1, weight=1)

    ttk.Label(score_frame, text="崩れスコア除外").grid(row=0, column=0, sticky="w", padx=10, pady=6)
    breakdown_score_box = ttk.Combobox(
        score_frame,
        textvariable=breakdown_score_var,
        values=tuple(BREAKDOWN_SCORE_VALUES.keys()),
        state="readonly",
        width=18,
    )
    breakdown_score_box.grid(row=0, column=1, sticky="w", padx=10, pady=6)

    def refresh_entry_dependent_controls(*_args) -> None:
        if entry_mode_var.get() == "intraday":
            range_position_label_var.set("終端位置")
            range_position_box.configure(state="readonly")
            breakdown_score_box.configure(state="readonly")
            return
        range_position_label_var.set("終値")
        if daily_entry_var.get() == "翌営業日始値":
            if breakdown_score_var.get() != "考慮しない":
                breakdown_score_var.set("考慮しない")
            range_position_box.configure(state="readonly")
            breakdown_score_box.configure(state="disabled")
        else:
            range_position_box.configure(state="readonly")
            breakdown_score_box.configure(state="readonly")
        if breakdown_score_var.get() == "考慮しない":
            start_entry.set_date(pd.Timestamp(year=pd.Timestamp.now().year, month=1, day=4).date())

    entry_mode_var.trace_add("write", refresh_entry_dependent_controls)
    daily_entry_var.trace_add("write", refresh_entry_dependent_controls)
    breakdown_score_var.trace_add("write", refresh_entry_dependent_controls)
    refresh_entry_dependent_controls()

    saved_queue: list[BacktestGuiInput] = []
    saved_count_var = tk.StringVar(value="保存済み条件: 0件")

    ttk.Label(frame, text="保存済み条件").grid(row=10, column=0, sticky="nw", pady=(8, 4))
    queue_frame = ttk.Frame(frame)
    queue_frame.grid(row=10, column=1, columnspan=2, sticky="w", pady=(8, 4))
    queue_list = tk.Listbox(queue_frame, width=78, height=8)
    queue_xscroll = ttk.Scrollbar(queue_frame, orient=tk.HORIZONTAL, command=queue_list.xview)
    queue_list.configure(xscrollcommand=queue_xscroll.set)
    queue_list.grid(row=0, column=0, sticky="w")
    queue_xscroll.grid(row=1, column=0, sticky="ew")
    ttk.Label(frame, textvariable=saved_count_var, foreground="#555555").grid(
        row=11, column=1, columnspan=2, sticky="w", pady=(0, 8)
    )

    def refresh_queue_list() -> None:
        queue_list.delete(0, tk.END)
        for index, gui_input in enumerate(saved_queue, start=1):
            queue_list.insert(tk.END, f"{index}. {summarize_condition(gui_input)}")
        saved_count_var.set(f"保存済み条件: {len(saved_queue)}件")

    def build_input_from_form() -> BacktestGuiInput:
        stock_file = Path(stock_var.get().strip())
        if not stock_file.is_file():
            raise ValueError("監視銘柄ファイルを選択してください。")
        output_dir = stock_file.parent
        if entry_mode_var.get() == "daily":
            entry_time = ENTRY_OPEN if daily_entry_var.get() == "翌営業日始値" else ENTRY_PREV_CLOSE
        else:
            entry_time = intraday_entry_var.get()
        selected_range_position = range_position_var.get()
        range_position_min_pct = (
            None if selected_range_position == "考慮せず" else float(selected_range_position.removesuffix("%以上"))
        )
        higher_high_exclude_count = (
            0 if higher_high_var.get() == "考慮しない" else int(higher_high_var.get().removesuffix("以上").removesuffix("回"))
        )
        config = VwapBacktestConfig(
            start_date=start_entry.get_date().strftime("%Y-%m-%d"),
            end_date=end_entry.get_date().strftime("%Y-%m-%d"),
            dev25_min=float(min_var.get()),
            dev25_max=float(max_var.get()),
            entry_time=entry_time,
            lower_low_exclude_count=LOWER_LOW_VALUES[lower_low_var.get()],
            higher_high_exclude_count=higher_high_exclude_count,
            range_position_min_pct=range_position_min_pct,
            support_distance_max_atr=None,
            require_ma5_slope_positive=require_ma5_slope_var.get(),
            ma5_slope_slowdown_policy=MA5_SLOWDOWN_VALUES[ma5_slowdown_var.get()],
            ma25_negative_slope_policy=MA25_NEGATIVE_SLOPE_VALUES[ma25_negative_slope_var.get()],
            breakdown_score_threshold=BREAKDOWN_SCORE_VALUES[breakdown_score_var.get()],
        )
        config.validate()
        if requires_intraday_prices(config):
            oldest = pd.offsets.BDay().rollforward(pd.Timestamp.now().normalize() - pd.Timedelta(days=59))
            if pd.Timestamp(config.start_date) < oldest:
                raise ValueError(f"5分足を使うため、開始日は {oldest.strftime('%Y-%m-%d')} 以降にしてください。")
        if pd.Timestamp(config.end_date) > pd.Timestamp.now().normalize():
            raise ValueError("終了日に未来の日付は指定できません。")
        save_watchlist_path(stock_file)
        return BacktestGuiInput(stock_file, output_dir, config)

    def save_condition() -> None:
        try:
            append_saved_condition(saved_queue, build_input_from_form())
            refresh_queue_list()
        except (OSError, ValueError) as exc:
            messagebox.showerror("入力エラー", str(exc))

    def clear_conditions() -> None:
        saved_queue.clear()
        refresh_queue_list()

    def assign_ma25_conditions() -> None:
        try:
            append_ma25_conditions(saved_queue, build_input_from_form())
            refresh_queue_list()
        except (OSError, ValueError) as exc:
            messagebox.showerror("入力エラー", str(exc))

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

    queue_buttons = ttk.Frame(frame)
    queue_buttons.grid(row=9, column=1, columnspan=2, sticky="w", pady=(8, 0))
    ttk.Button(queue_buttons, text="条件保存", width=14, command=save_condition).pack(side=tk.LEFT, padx=(0, 6))
    ttk.Button(queue_buttons, text="連続実行", width=14, command=submit_queue).pack(side=tk.LEFT, padx=6)
    ttk.Button(queue_buttons, text="MA25条件割当", width=14, command=assign_ma25_conditions).pack(
        side=tk.LEFT, padx=(6, 10)
    )
    ttk.Button(queue_buttons, text="キュークリア", width=14, command=clear_conditions).pack(side=tk.LEFT, padx=6)

    buttons = ttk.Frame(frame)
    buttons.grid(row=12, column=0, columnspan=3, pady=8)
    ttk.Button(buttons, text="実行", width=14, command=submit).pack(side=tk.LEFT, padx=8)
    ttk.Button(buttons, text="キャンセル", width=14, command=win.destroy).pack(side=tk.LEFT, padx=8)
    if remembered_watchlist is None:
        win.after(100, browse_stock)
    win.mainloop()
    return result["value"]


def show_batch_completion(
    outputs: Sequence[tuple[Path, Path]],
    errors: Sequence[tuple[BacktestGuiInput, Exception]],
) -> None:
    if tk is None or messagebox is None:
        return
    root = tk.Tk()
    root.withdraw()
    lines = [
        f"A11バックテストが完了しました。成功: {len(outputs)}件 / エラー: {len(errors)}件"
    ]
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
