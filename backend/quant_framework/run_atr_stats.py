"""ATR 顶/底信号样本外统计（全自选股 × 多周期）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import astock  # noqa: E402
from quant_framework.atr import atr_signal_stats  # noqa: E402

CODES = ["000636", "300223", "600487", "000063", "516080"]
CATS = [("日K", 4), ("周K", 5), ("月K", 6), ("60分", 11), ("30分", 2), ("15分", 1)]


def main() -> None:
    for cat_name, cat in CATS:
        rows_all = []
        for code in CODES:
            try:
                rdata = astock.kline(code, category=cat, offset=800)
                if not rdata:
                    continue
                df = pd.DataFrame(rdata)
                df["datetime"] = pd.to_datetime(df["datetime"])
                stats = atr_signal_stats(df, horizon=5)
                top_n = stats["top"]["n"]
                bot_n = stats["bottom"]["n"]
                top_hit = stats["top"]["hit_rate"]
                bot_hit = stats["bottom"]["hit_rate"]
                top_avg = stats["top"]["avg_fwd"]
                bot_avg = stats["bottom"]["avg_fwd"]
                rows_all.append(f"{code}: 顶 n={top_n} 命中={top_hit}% 后5均={top_avg}% | 底 n={bot_n} 命中={bot_hit}% 后5均={bot_avg}%")
            except Exception as e:  # noqa: BLE001
                rows_all.append(f"{code}: ERR {e}")
        print(f"=== {cat_name} ===")
        for r in rows_all:
            print(" ", r)


if __name__ == "__main__":
    main()
