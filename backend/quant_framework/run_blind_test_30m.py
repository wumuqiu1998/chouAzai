"""30分钟K长窗口跨行业盲测（腾讯可取约100个交易日）。

mootdx/东财分钟K当前不可用，腾讯 30 分钟K offset=800 ≈ 100 天，
作为“分钟级长窗口”的可行替代。随机 20 只，信号按确认延迟成交
（ATR+1根/缠论+2根/SMC+3根），持有 2/4 根（1/2小时）。
"""

from __future__ import annotations

import random
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import astock  # noqa: E402
from run_blind_test import collect_signals, eval_signal, fetch_universe  # noqa: E402

SEED = 20260812
N = 20
CAT = 2  # 30分钟
OFFSET = 800
OUT = Path(__file__).resolve().parent / "data" / "blind_test_30m.md"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    universe = fetch_universe()
    rng = random.Random(SEED)
    sample = rng.sample(universe, min(N, len(universe)))
    stats: dict[str, dict] = defaultdict(lambda: {"n": 0, "rets2": [], "rets4": []})
    used = 0
    for s in sample:
        code = s["code"]
        try:
            rows = astock.kline(code, category=CAT, offset=OFFSET)
        except Exception:  # noqa: BLE001
            continue
        if len(rows) < 300:
            continue
        df = pd.DataFrame(rows)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        opens = df["open"].astype(float).values
        closes = df["close"].astype(float).values
        used += 1
        for sig in collect_signals(df):
            off = sig.get("exec_offset", 1)
            e2 = eval_signal(opens, closes, sig["i"], 2, off)
            e4 = eval_signal(opens, closes, sig["i"], 4, off)
            key = f"{sig['strategy']}|{sig['side']}"
            if e2:
                stats[key]["n"] += 1
                stats[key]["rets2"].append(e2["ret"])
                stats[key]["rets4"].append(e4["ret"] if e4 else e2["ret"])
        print(f"{code} {s['name']} done", flush=True)

    lines = [
        "# 30分钟K长窗口跨行业盲测（20 只随机 × 约100个交易日）",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　有效股票：{used}",
        "> 口径：信号后按确认延迟成交（ATR+1根/缠论+2根/SMC+3根），持有 2/4 根（1/2小时）。",
        "> 数据源说明：mootdx/东财分钟K当前不可用，腾讯30分钟K为可行上限（800根≈100天）。",
        "",
        "| 策略 | 方向 | 样本 | 1小时平均收益 | 1小时准确率 | 2小时平均收益 | 2小时准确率 |",
        "|---|---|---|---|---|---|---|",
    ]
    for strategy in ("ATR", "缠论", "SMC"):
        for side in ("buy", "sell"):
            key = f"{strategy}|{side}"
            v = stats.get(key)
            if not v or v["n"] == 0:
                lines.append(f"| {strategy} | {'买' if side == 'buy' else '卖'} | 0 | - | - | - | - |")
                continue
            r2, r4 = np.mean(v["rets2"]), np.mean(v["rets4"])
            a2 = np.mean([1 if x < 0 else 0 for x in v["rets2"]]) if side == "sell" else np.mean([1 if x > 0 else 0 for x in v["rets2"]])
            a4 = np.mean([1 if x < 0 else 0 for x in v["rets4"]]) if side == "sell" else np.mean([1 if x > 0 else 0 for x in v["rets4"]])
            lines.append(f"| {strategy} | {'买' if side == 'buy' else '卖'} | {v['n']} | {r2 * 100:+.2f}% | {a2 * 100:.0f}% | {r4 * 100:+.2f}% | {a4 * 100:.0f}% |")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已生成：{OUT}")


if __name__ == "__main__":
    main()
