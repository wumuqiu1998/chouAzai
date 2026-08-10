"""全市场随机 50 只日K盲测：验证信号方向准确率是否依赖自选池。

口径：
- 股票池：东财沪深A全市场随机抽样 50 只（排除科创板 688/689、北交所 8/4、ST、退市），seed 固定可复现；
- 数据：腾讯日K（约 800 根 ≈ 3.3 年，qfq；接口上限所致，非 5 年，报告中注明）；
- 信号：ATR 顶/底、缠论 B/S/三卖预警、SMC 扫荡/结构（全部用当前默认参数，盲测前冻结）；
- 评估：信号后 **下一日开盘成交**，持有 5/10 日收益；
  卖点准确率=未来收益<0 比例，买点准确率=未来收益>0 比例。
"""

from __future__ import annotations

import random
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import astock  # noqa: E402
from quant_framework.atr import compute_atr  # noqa: E402
from quant_framework.chan import analyze_chan  # noqa: E402
from quant_framework.smc import analyze_smc  # noqa: E402

SEED = 20260810
N = 50
OUT = Path(__file__).resolve().parent / "data" / "blind_test.md"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0 Safari/537.36", "Referer": "https://quote.eastmoney.com/"}

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def fetch_universe() -> list[dict]:
    out: list[dict] = []
    for pn in range(1, 13):
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
        except Exception as e:  # noqa: BLE001
            print("universe warn", e)
        time.sleep(1.0)
    return out


def collect_signals(df: pd.DataFrame) -> list[dict]:
    im = {str(pd.Timestamp(ts))[:16].replace(" 00:00", ""): i for i, ts in enumerate(df["datetime"])}
    out: list[dict] = []
    for s in compute_atr(df)["signals"]:
        if s["kind"] not in ("top", "bottom"):
            continue
        i = im.get(s["date"])
        if i is not None:
            out.append({"i": i, "strategy": "ATR", "label": "顶" if s["kind"] == "top" else "底", "side": "sell" if s["kind"] == "top" else "buy"})
    label_map = {"buy1": "B1", "buy2": "B2", "buy3": "B3", "sell1": "S1", "sell2": "S2", "sell3": "S3", "sell3_warn": "警"}
    for p in analyze_chan(df)["points"]:
        i = im.get(p["date"])
        label = label_map.get(p["kind"])
        if i is None or label is None:
            continue
        out.append({"i": i, "strategy": "缠论", "label": label, "side": "sell" if p["kind"].startswith("sell") else "buy"})
    smc = analyze_smc(df, sweep_min_gap=15)
    for s in smc.get("sweeps") or []:
        i = im.get(s["date"])
        if i is not None:
            out.append({"i": i, "strategy": "SMC", "label": "扫", "side": "buy" if s["kind"] == "bullish" else "sell"})
    st = smc.get("structure") or {}
    for key, side in (("last_bos", None), ("last_choch", "sell")):
        item = st.get(key)
        if not item:
            continue
        i = im.get(item["date"])
        if i is None:
            continue
        if key == "last_bos":
            side = "buy" if item["kind"] == "bullish" else "sell"
        out.append({"i": i, "strategy": "SMC", "label": "突" if (key == "last_bos" and item["kind"] == "bullish") else ("破" if key == "last_bos" else "变"), "side": side})
    return out


def eval_signal(opens: np.ndarray, closes: np.ndarray, idx: int, horizon: int) -> dict | None:
    if idx + 1 + horizon >= len(closes):
        return None
    base = opens[idx + 1]
    if base <= 0:
        return None
    ret = closes[idx + 1 + horizon] / base - 1.0
    return {"ret": ret}


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    universe = fetch_universe()
    rng = random.Random(SEED)
    sample = rng.sample(universe, min(N, len(universe)))
    stats: dict[str, dict] = defaultdict(lambda: {"n": 0, "rets5": [], "rets10": []})
    used: list[str] = []

    for s in sample:
        code = s["code"]
        try:
            rows = astock.kline(code, category=4, offset=800)
        except Exception:  # noqa: BLE001
            continue
        if len(rows) < 250:
            continue
        df = pd.DataFrame(rows)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        opens = df["open"].astype(float).values
        closes = df["close"].astype(float).values
        used.append(f"{code} {s['name']}({len(df)}根)")
        for sig in collect_signals(df):
            e5 = eval_signal(opens, closes, sig["i"], 5)
            e10 = eval_signal(opens, closes, sig["i"], 10)
            key = f"{sig['strategy']}|{sig['side']}"
            if e5:
                stats[key]["n"] += 1
                stats[key]["rets5"].append(e5["ret"])
                stats[key]["rets10"].append(e10["ret"] if e10 else e5["ret"])
        print(f"{code} {s['name']} done", flush=True)

    lines = [
        "# 全市场随机 50 只盲测：信号方向准确率",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　seed={SEED}　有效股票：{len(used)}/{len(sample)}",
        "> 口径：腾讯日K（约800根≈3.3年，qfq；接口上限无法取满5年）；信号后下一日开盘成交；",
        "> 参数在盲测前冻结（ATR/缠论/SMC 默认值）。",
        "",
        "## 策略维度",
        "",
        "| 策略 | 方向 | 样本 | 5日平均收益 | 5日方向准确率 | 10日平均收益 | 10日方向准确率 |",
        "|---|---|---|---|---|---|---|",
    ]
    for strategy in ("ATR", "缠论", "SMC"):
        for side in ("buy", "sell"):
            key = f"{strategy}|{side}"
            v = stats.get(key)
            if not v or v["n"] == 0:
                lines.append(f"| {strategy} | {'买' if side == 'buy' else '卖'} | 0 | - | - | - | - |")
                continue
            r5, r10 = np.mean(v["rets5"]), np.mean(v["rets10"])
            acc5 = np.mean([1 if x < 0 else 0 for x in v["rets5"]]) if side == "sell" else np.mean([1 if x > 0 else 0 for x in v["rets5"]])
            acc10 = np.mean([1 if x < 0 else 0 for x in v["rets10"]]) if side == "sell" else np.mean([1 if x > 0 else 0 for x in v["rets10"]])
            lines.append(f"| {strategy} | {'买' if side == 'buy' else '卖'} | {v['n']} | {r5 * 100:+.2f}% | {acc5 * 100:.0f}% | {r10 * 100:+.2f}% | {acc10 * 100:.0f}% |")

    lines += ["", "## 股票清单", ""]
    lines += [f"- {u}" for u in used]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已生成：{OUT}（有效股票 {len(used)}/{len(sample)}）")


if __name__ == "__main__":
    main()
