"""Signal summary aggregation."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.domain.config import HORIZONS, WINDOWS


def summarize_signals(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    summaries = []
    for category, g in df.groupby("category", dropna=False):
        record = {"category": category, "count": int(len(g))}
        for h in HORIZONS:
            col = f"ret_{h}d_pct"
            s = pd.to_numeric(g[col], errors="coerce")
            record[f"avg_{h}d_pct"] = float(s.mean()) if not s.dropna().empty else np.nan
            record[f"median_{h}d_pct"] = float(s.median()) if not s.dropna().empty else np.nan
            record[f"winrate_{h}d_pct"] = float((s > 0).mean() * 100.0) if not s.dropna().empty else np.nan

        for w in WINDOWS:
            up = pd.to_numeric(g[f"max_up_{w}d_pct"], errors="coerce")
            dd = pd.to_numeric(g[f"max_dd_{w}d_pct"], errors="coerce")
            record[f"avg_max_up_{w}d_pct"] = float(up.mean()) if not up.dropna().empty else np.nan
            record[f"avg_max_dd_{w}d_pct"] = float(dd.mean()) if not dd.dropna().empty else np.nan

        summaries.append(record)

    out = pd.DataFrame(summaries)
    preferred_order = {
        "本命候補": 0,
        "監視候補": 1,
        "別戦略:リバ候補": 2,
        "見送り:押し未完成": 3,
        "見送り:過熱": 4,
        "見送り:トレンド": 5,
        "見送り:ファンダ": 6,
        "見送り:流動性": 7,
        "判定保留": 8,
    }
    out["_order"] = out["category"].map(lambda x: preferred_order.get(x, 99))
    out = out.sort_values(["_order", "avg_5d_pct", "count"], ascending=[True, False, False]).drop(columns=["_order"]).reset_index(drop=True)
    return out
