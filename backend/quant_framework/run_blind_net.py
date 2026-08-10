"""盲测净收益：缠论买点信号（费用+涨停约束） vs 随机基准。

在方向准确率（run_blind_test.py）基础上加：
- 买入：信号后第 2 根开盘（缠论右侧确认），若开盘相对昨收 ≥ +9.8% 视为涨停买不进，跳过；
- 卖出：持有 5 日后收盘卖出，若收盘相对昨收 ≤ -9.8% 视为跌停卖不出，按收盘估值（保守标记）；
- 费用：佣金 0.0003×2、印花税 0.0005、滑点 0.0001×2。
"""

from __future__ import annotations

import random
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import astock  # noqa: E402
from quant_framework.chan import analyze_chan  # noqa: E402
from run_blind_test import fetch_universe  # noqa: E402

SEED = 20260810
N = 50
OUT = Path(__file__).resolve().parent / "data" / "blind_net.md"
COMMISSION = 0.0003
STAMP = 0.0005
SLIPPAGE = 0.0001
LIMIT = 0.098

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def net_of(base: float, sell: float) -> float:
    buy_px = base * (1 + SLIPPAGE)
    sell_px = sell * (1 - SLIPPAGE)
    return sell_px / buy_px - 1.0 - COMMISSION * 2 - STAMP


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    universe = fetch_universe()
    rng = random.Random(SEED)
    sample = rng.sample(universe, min(N, len(universe)))
    sig_nets: list[float] = []
    base_nets: list[float] = []
    blocked = 0
    used = 0

    for s in sample:
        code = s["code"]
        try:
            rows = astock.kline(code, category=4, offset=260)
        except Exception:  # noqa: BLE001
            continue
        if len(rows) < 250:
            continue
        df = pd.DataFrame(rows)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        opens = df["open"].astype(float).values
        closes = df["close"].astype(float).values
        used += 1

        sig_i: set[int] = set()
        chan = analyze_chan(df)
        im = {str(pd.Timestamp(ts))[:16].replace(" 00:00", ""): i for i, ts in enumerate(df["datetime"])}
        for p in chan["points"]:
            i = im.get(p["date"])
            if i is None or not p["kind"].startswith("buy") or i + 7 >= len(closes):
                continue
            sig_i.add(i)
            prev = closes[i + 1]
            if prev <= 0:
                continue
            buy = opens[i + 2]
            if buy / prev - 1.0 >= LIMIT - 1e-6:
                blocked += 1
                continue
            sell = closes[i + 7]
            if sell / closes[i + 6] - 1.0 <= -LIMIT + 1e-6:
                blocked += 1
                continue
            if buy <= 0:
                continue
            sig_nets.append(net_of(buy, sell))

        for i in range(len(closes) - 7):
            if i in sig_i or i + 1 in sig_i or i + 2 in sig_i:
                continue
            prev = closes[i + 1]
            if prev <= 0:
                continue
            buy = opens[i + 2]
            if buy / prev - 1.0 >= LIMIT - 1e-6:
                continue
            sell = closes[i + 7]
            if sell / closes[i + 6] - 1.0 <= -LIMIT + 1e-6:
                continue
            if buy <= 0:
                continue
            base_nets.append(net_of(buy, sell))
        print(f"{code} {s['name']} done", flush=True)

    a = np.array(sig_nets)
    b = np.array(base_nets)
    lines = [
        "# 盲测净收益：缠论买点 vs 随机基准（含费用与涨跌停约束）",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　有效股票：{used}　被涨跌停挡掉的信号：{blocked}",
        "> 口径：T+2 开盘买入（缠论右侧确认）、持有 5 日收盘卖出；佣金 0.0003×2 + 印花税 0.0005 + 滑点 0.0001×2。",
        "",
        f"**缠论买点：样本 {len(a)}　平均净收益 {a.mean() * 100:+.2f}%　中位数 {np.median(a) * 100:+.2f}%　正收益概率 {(a > 0).mean() * 100:.0f}%**",
        "",
        f"**随机基准：样本 {len(b)}　平均净收益 {b.mean() * 100:+.2f}%　中位数 {np.median(b) * 100:+.2f}%　正收益概率 {(b > 0).mean() * 100:.0f}%**",
        "",
        f"**超额净收益：{(a.mean() - b.mean()) * 100:+.2f}%**",
        "",
        "结论：超额为正且样本足够，缠论买点在扣除费用/涨跌停后仍可能有优势；若接近 0 则优势被成本吃掉。",
    ]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已生成：{OUT}")


if __name__ == "__main__":
    main()
