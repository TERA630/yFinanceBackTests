"""Tkinter GUI helpers for input selection and completion notice."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

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


def select_stock_file() -> Optional[Path]:
    if tk is None or filedialog is None:
        raise RuntimeError("tkinter が使えません。CLI引数で実行してください。")
    root = tk.Tk()
    root.withdraw()
    root.update()
    file_path = filedialog.askopenfilename(
        title="監視銘柄の stock.md を選択",
        filetypes=[("Markdown files", "*.md"), ("All files", "*.*")],
    )
    root.destroy()
    return Path(file_path) if file_path else None


def select_output_dir(initial_dir: Optional[Path] = None) -> Optional[Path]:
    if tk is None or filedialog is None:
        raise RuntimeError("tkinter が使えません。CLI引数で実行してください。")
    root = tk.Tk()
    root.withdraw()
    root.update()
    folder = filedialog.askdirectory(
        title="出力先フォルダを選択",
        initialdir=str(initial_dir) if initial_dir else None,
    )
    root.destroy()
    return Path(folder) if folder else None


def select_date_range() -> Optional[Tuple[str, str, int]]:
    if tk is None or ttk is None or DateEntry is None:
        raise RuntimeError("tkcalendar が使えません。pip install tkcalendar を実行するか、CLI引数で実行してください。")

    result = {"start": None, "end": None, "lower_low_exclude_count": None}
    win = tk.Tk()
    win.title("A7R バックテスト期間を選択")
    win.geometry("420x270")
    win.resizable(False, False)

    tk.Label(win, text="開始日").pack(pady=(15, 5))
    start_entry = DateEntry(win, width=14, background="darkblue", foreground="white", borderwidth=2, date_pattern="yyyy-mm-dd", locale="ja_JP")
    start_entry.pack()

    tk.Label(win, text="終了日").pack(pady=(15, 5))
    end_entry = DateEntry(win, width=14, background="darkblue", foreground="white", borderwidth=2, date_pattern="yyyy-mm-dd", locale="ja_JP")
    end_entry.pack()

    tk.Label(win, text="直近3日間の安値切り下げ銘柄を除外").pack(pady=(15, 5))
    lower_low_box = ttk.Combobox(win, width=12, state="readonly", values=("0回", "1回", "2回", "3回"))
    lower_low_box.current(0)
    lower_low_box.pack()

    def on_ok():
        start = start_entry.get_date().strftime("%Y-%m-%d")
        end = end_entry.get_date().strftime("%Y-%m-%d")
        if start > end:
            if messagebox is not None:
                messagebox.showerror("エラー", "開始日は終了日以前にしてください。")
            return
        result["start"] = start
        result["end"] = end
        result["lower_low_exclude_count"] = lower_low_box.current()
        win.destroy()

    def on_cancel():
        win.destroy()

    btn_frame = tk.Frame(win)
    btn_frame.pack(pady=20)
    tk.Button(btn_frame, text="実行", width=10, command=on_ok).pack(side=tk.LEFT, padx=8)
    tk.Button(btn_frame, text="キャンセル", width=10, command=on_cancel).pack(side=tk.LEFT, padx=8)
    win.mainloop()

    if result["start"] is None or result["end"] is None or result["lower_low_exclude_count"] is None:
        return None
    return result["start"], result["end"], result["lower_low_exclude_count"]


def show_completion_message(signals_path: Path, summary_path: Path) -> None:
    if messagebox is None or tk is None:
        return
    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo("完了", f"出力が完了しました。\n\n{signals_path}\n{summary_path}")
    root.destroy()
