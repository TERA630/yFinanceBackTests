"""Persistence for local GUI preferences."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


SETTINGS_PATH = Path(__file__).resolve().parents[2] / ".backtest_settings.json"


def load_watchlist_path(settings_path: Path = SETTINGS_PATH) -> Optional[Path]:
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        path = Path(data["watchlist_path"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return path if path.is_file() else None


def save_watchlist_path(watchlist_path: Path, settings_path: Path = SETTINGS_PATH) -> None:
    settings_path.write_text(
        json.dumps({"watchlist_path": str(watchlist_path.resolve())}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
