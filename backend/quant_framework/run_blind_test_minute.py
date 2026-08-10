"""分钟级跨行业小样本盲测（数据源受限版）。

腾讯 5 分钟K 接口上限约 320 根（≈7 个交易日），无法做长窗口分钟盲测。
这里先跑 10 只随机股票的 7 日方向准确率作为初步方向，结论仅作参考。
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
from quant_framework.atr import compute_atr  # noqa: E402
from quant_framework.chan import analyze_chan  # noqa: E402
from quant_framework.smc import analyze_smc  # noqa: E402
from run_blind_test import fetch_universe  # noqa: E402

SEED = 20260811
N = 10
CAT = 0  # 5分钟
OFFSET = 320
HORIZON = 6  # 30分钟
OUT = Path(__file__).resolve().parent / "data" / "blind_test_minute.md"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def collect(df: pd.DataFrame) -> list[dict]:
    im = {str(pd.Timestamp(ts))[:16].replace(" 00:00", ""): i for i, ts in enumerate(df["datetime"])}
    out: list[dict] = []
    for s in compute_atr(df)["signals"]:
        if s["kind"] in ("top", "bottom") and im.get(s["date"]) is not None:
            out.append({"i": im[s["date"]], "strategy": "ATR", "side": "sell" if s["kind"] == "top" else "buy", "offset": 1})
    lm = {"buy1": "B1", "buy2": "B2", "buy3": "B3", "sell1": "S1", "sell2": "S2", "sell3": "S3", "sell3_warn": "警"}
    for p in analyze_chan(df)["points"]:
        i = im.get(p["date"])
        if i is not None and p["kind"] in lm:
            out.append({"i": i, "strategy": "缠论", "side": "sell" if p["kind"].startswith("sell") else "buy", "offset": 2})
    smc = analyze_smc(df, sweep_min_gap=0)
    for s in smc.get("sweeps") or []:
        i = im.get(s["date"])
        if i is not None:
            out.append({"i": i, "strategy": "SMC", "side": "buy" if s["kind"] == "bullish" else "sell", "offset": 3})
    st = smc.get("structure") or {}
    for key in ("last_bos", "last_choch"):
        item = st.get(key)
        if not item:
            continue
        i = im.get(item["date"])
        if i is None:
            continue
        side = "buy" if (key == "last_bos" and item["kind"] == "bullish") else "sell"
        out.append({"i": i, "strategy": "SMC", "side": side, "offset": 3})
    return out


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    universe = fetch_universe()
    rng = random.Random(SEED)
    sample = rng.sample(universe, min(N, len(universe)))
    stats: dict[str, list] = defaultdict(list)
    used = 0
    for s in sample:
        code = s["code"]
        try:
            rows = astock.kline(code, category=CAT, offset=OFFSET)
        except Exception:  # noqa: BLE001
            continue
        if len(rows) < 100:
            continue
        df = pd.DataFrame(rows)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        opens = df["open"].astype(float).values
        closes = df["close"].astype(float).values
        used += 1
        for sig in collect(df):
            off = sig["offset"]
            if sig["i"] + off + HORIZON >= len(closes):
                continue
            base = opens[sig["i"] + off]
            if base <= 0:
                continue
            ret = closes[sig["i"] + off + HORIZON] / base - 1.0
            stats[f"{sig['strategy']}|{sig['side']}"].append(ret)
        print(f"{code} {s['name']} done", flush=True)

    lines = [
        "# 分钟级跨行业小样本盲测（5分钟K，10只随机）",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　有效股票：{used}　数据：腾讯5分钟K约320根（≈7个交易日）",
        "> 信号后按确认延迟成交（ATR+1根/缠论+2根/SMC+3根），持有 30 分钟（6根）。",
        "> ⚠️ 样本极小且窗口仅 7 天，仅作初步方向，不构成验证。",
        "",
        "| 策略 | 方向 | 样本 | 30分钟平均收益 | 方向准确率 |",
        "|---|---|---|---|---|",
    ]
    for strategy in ("ATR", "缠论", "SMC"):
        for side in ("buy", "sell"):
            v = stats.get(f"{strategy}|{side}", [])
            if not v:
                lines.append(f"| {strategy} | {'买' if side == 'buy' else '卖'} | 0 | - | - |")
                continue
            arr = np.array(v)
            acc = np.mean([1 if x < 0 else 0 for x in arr]) if side == "sell" else np.mean([1 if x > 0 else 0 for x in arr])
            lines.append(f"| {strategy} | {'买' if side == 'buy' else '卖'} | {len(arr)} | {arr.mean() * 100:+.2f}% | {acc * 100:.0f}% |")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已生成：{OUT}")


if __name__ == "__main__":
    main()
