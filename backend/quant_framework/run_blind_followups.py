"""辩驳报告待办跟进：去重叠 / 沪深均衡 / 超跌因子直接对比。

1. 信号去重叠：同一股票 20 个交易日内只保留第一个买点，重算 5 日收益；
2. 沪深均衡：深市/沪市各 25 只重新盲测缠论买点，分开统计；
3. 超跌因子对比：同池同口径用“过去10日跌幅>10%”日期做买入信号，
   与缠论买点的单笔净收益直接对比。
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
SEED_MARKET = 20260811
N = 50
OUT = Path(__file__).resolve().parent / "data" / "blind_followups.md"
LIMIT = 0.098
COMMISSION = 0.0003
STAMP = 0.0005
SLIPPAGE = 0.0001

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def net_ret(opens: np.ndarray, closes: np.ndarray, idx: int, exec_offset: int) -> float | None:
    if idx + exec_offset + 5 >= len(closes):
        return None
    prev = closes[idx + exec_offset - 1]
    buy = opens[idx + exec_offset]
    if prev <= 0 or buy <= 0 or buy / prev - 1.0 >= LIMIT - 1e-6:
        return None
    sell = closes[idx + exec_offset + 5]
    if sell / closes[idx + exec_offset + 4] - 1.0 <= -LIMIT + 1e-6:
        return None
    return sell * (1 - SLIPPAGE) / (buy * (1 + SLIPPAGE)) - 1.0 - COMMISSION * 2 - STAMP


def chan_buy_points(df: pd.DataFrame) -> list[dict]:
    opens = df["open"].astype(float).values
    closes = df["close"].astype(float).values
    im = {str(pd.Timestamp(ts))[:16].replace(" 00:00", ""): i for i, ts in enumerate(df["datetime"])}
    out = []
    for p in analyze_chan(df)["points"]:
        i = im.get(p["date"])
        if i is None or not p["kind"].startswith("buy"):
            continue
        out.append({"i": i, "kind": p["kind"]})
    return out


def fetch_universe_more() -> list[dict]:
    """扩展版全市场列表：拉 20 页，尽量覆盖沪市。"""
    import requests
    import time

    UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0 Safari/537.36", "Referer": "https://quote.eastmoney.com/"}
    out: list[dict] = []
    for pn in range(1, 41):
        try:
            r = requests.get(
                "https://push2delay.eastmoney.com/api/qt/clist/get",
                params={
                    "pn": pn, "pz": 100, "po": 1, "np": 1, "fltt": 2, "invt": 2,
                    "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
                    "fields": "f12,f14",
                },
                headers=UA, timeout=20, proxies={"http": None, "https": None},
            )
            diff = (r.json().get("data") or {}).get("diff") or []
            if not diff:
                break
            for x in diff:
                code = str(x.get("f12", ""))
                name = str(x.get("f14", ""))
                if code.startswith(("688", "689", "8", "4")):
                    continue
                if "ST" in name.upper() or "退" in name:
                    continue
                out.append({"code": code, "name": name})
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.8)
    return out


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    universe = fetch_universe()

    # ---- 1) 原 50 只：去重叠 + 超跌因子对比 ----
    rng = random.Random(SEED)
    sample = rng.sample(universe, min(N, len(universe)))
    raw_rets, dedup_rets, oversold_rets = [], [], []
    for s in sample:
        rows = astock.kline(s["code"], category=4, offset=260)
        if not rows or len(rows) < 250:
            continue
        df = pd.DataFrame(rows)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        opens = df["open"].astype(float).values
        closes = df["close"].astype(float).values
        pts = sorted(chan_buy_points(df), key=lambda x: x["i"])
        last_dedup_i = -10**9
        for p in pts:
            r = net_ret(opens, closes, p["i"], 2)
            if r is None:
                continue
            raw_rets.append(r)
            if p["i"] - last_dedup_i >= 20:
                dedup_rets.append(r)
                last_dedup_i = p["i"]
        for i in range(20, len(closes) - 6):
            if closes[i] / closes[i - 10] - 1.0 <= -0.10:
                r = net_ret(opens, closes, i, 1)
                if r is not None:
                    oversold_rets.append(r)
        print(s["code"], "done", flush=True)

    # ---- 2) 沪深均衡 ----
    universe_more = fetch_universe_more()
    deep = [u for u in universe_more if u["code"].startswith(("0", "3"))]
    shang = [u for u in universe_more if u["code"].startswith(("6", "9"))]
    print(f"[debug] universe_more={len(universe_more)} deep={len(deep)} shang={len(shang)}", flush=True)
    rng2 = random.Random(SEED_MARKET)
    n_half = min(25, len(deep), len(shang))
    market_sample = rng2.sample(deep, n_half) + rng2.sample(shang, n_half)
    market_stat = {"深": {"n": 0, "rets": []}, "沪": {"n": 0, "rets": []}}
    for s in market_sample:
        rows = astock.kline(s["code"], category=4, offset=260)
        if not rows or len(rows) < 250:
            continue
        df = pd.DataFrame(rows)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        opens = df["open"].astype(float).values
        closes = df["close"].astype(float).values
        mkt = "深" if s["code"].startswith(("0", "3")) else "沪"
        for p in chan_buy_points(df):
            r = net_ret(opens, closes, p["i"], 2)
            if r is not None:
                market_stat[mkt]["n"] += 1
                market_stat[mkt]["rets"].append(r)
        print("market", s["code"], "done", flush=True)

    def stat(xs):
        a = np.array(xs)
        return len(a), a.mean(), (a > 0).mean()

    lines = [
        "# 辩驳待办跟进：去重叠 / 沪深均衡 / 超跌因子对比",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "> 口径：5 日持有、含费用（佣金0.0003×2+印花税0.0005+滑点0.0001×2）、涨停开盘买不进/跌停卖不出跳过。",
        "",
        "## 1. 信号去重叠（同股 20 日内只保留第一个买点）",
        "",
    ]
    n1, m1, p1 = stat(raw_rets)
    n2, m2, p2 = stat(dedup_rets)
    lines.append(f"- 原始买点：样本 {n1}　净收益 {m1 * 100:+.2f}%　正概率 {p1 * 100:.0f}%")
    lines.append(f"- 去重叠后：样本 {n2}　净收益 {m2 * 100:+.2f}%　正概率 {p2 * 100:.0f}%")
    lines.append("- 若两者接近，说明结果不是相邻信号重复贡献；若去重叠后大幅下降，说明优势依赖信号簇。")
    lines += ["", f"## 2. 沪深均衡盲测（各 {n_half} 只）", "", "| 市场 | 样本 | 平均净收益 | 正概率 |", "|---|---|---|---|"]
    for mkt in ("深", "沪"):
        n, m, p = stat(market_stat[mkt]["rets"])
        lines.append(f"| {mkt} | {n} | {m * 100:+.2f}% | {p * 100:.0f}% |")
    lines.append("- 若沪市也显著为正，结论可外推；若仅深市为正，结论改写为深市风格因子。")
    lines += ["", "## 3. 超跌因子直接对比（同池同口径）", ""]
    n3, m3, p3 = stat(oversold_rets)
    lines.append(f"- 缠论买点：样本 {n1}　净收益 {m1 * 100:+.2f}%　正概率 {p1 * 100:.0f}%")
    lines.append(f"- 超跌因子（过去10日跌>10%）：样本 {n3}　净收益 {m3 * 100:+.2f}%　正概率 {p3 * 100:.0f}%")
    lines.append(f"- 差额：{(m1 - m3) * 100:+.2f}%（>0 说明缠论买点相对纯超跌因子有增量）")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已生成：{OUT}")


if __name__ == "__main__":
    main()
