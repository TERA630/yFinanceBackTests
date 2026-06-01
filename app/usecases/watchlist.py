"""Watchlist parsing and loading."""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple


def parse_stock_md(md_text: str) -> List[Tuple[str, str]]:
    results: List[Tuple[str, str]] = []
    pattern = re.compile(r"[-*]?\s*([^\n()]+?)\s*[\(（]\s*(\d{4})\s*[\)）]")
    for line in md_text.splitlines():
        m = pattern.search(line)
        if m:
            results.append((m.group(1).strip(), m.group(2).strip()))

    seen = set()
    deduped: List[Tuple[str, str]] = []
    for name, code in results:
        if code not in seen:
            seen.add(code)
            deduped.append((name, code))
    return deduped


def load_watchlist(stock_md_path: Path) -> List[Tuple[str, str]]:
    text = stock_md_path.read_text(encoding="utf-8")
    parsed = parse_stock_md(text)
    if not parsed:
        raise ValueError("stock.md から 4桁コード付き銘柄を抽出できませんでした。")
    return parsed
