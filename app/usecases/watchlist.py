"""Watchlist parsing and loading."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple


SEMICONDUCTOR_RELATED_KEYWORDS = ("半導体", "AIインフラ")


@dataclass(frozen=True)
class WatchlistItem:
    name: str
    code: str
    is_semiconductor_related: bool = False


def parse_stock_md(md_text: str) -> List[Tuple[str, str]]:
    return [(item.name, item.code) for item in parse_watchlist_items(md_text)]


def parse_watchlist_items(md_text: str) -> List[WatchlistItem]:
    results: List[WatchlistItem] = []
    pattern = re.compile(r"[-*]?\s*([^\n()]+?)\s*[\(（]\s*(\d{4})\s*[\)）]")
    for line in md_text.splitlines():
        m = pattern.search(line)
        if m:
            results.append(
                WatchlistItem(
                    name=m.group(1).strip(),
                    code=m.group(2).strip(),
                    is_semiconductor_related=any(keyword in line for keyword in SEMICONDUCTOR_RELATED_KEYWORDS),
                )
            )

    seen = set()
    deduped: List[WatchlistItem] = []
    for item in results:
        if item.code not in seen:
            seen.add(item.code)
            deduped.append(item)
    return deduped


def load_watchlist(stock_md_path: Path) -> List[Tuple[str, str]]:
    return [(item.name, item.code) for item in load_watchlist_items(stock_md_path)]


def load_watchlist_items(stock_md_path: Path) -> List[WatchlistItem]:
    text = stock_md_path.read_text(encoding="utf-8")
    parsed = parse_watchlist_items(text)
    if not parsed:
        raise ValueError("stock.md から 4桁コード付き銘柄を抽出できませんでした。")
    return parsed
