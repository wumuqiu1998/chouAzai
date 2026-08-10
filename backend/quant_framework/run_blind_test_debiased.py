"""缠论 B/S 盲测基准去偏：信号后 5 日收益 vs 同股票全日期基准。

回答对抗审计的关键疑问：缠论买点 88% 方向准确率是独立 Alpha，
还是“买点出现在下跌后、均值回归 + 市场 beta”造成的假象？

口径：
- 股票池与 run_blind_test.py 完全一致（seed=20260810，随机 50 只）；
- 收益：信号后下一日开盘成交，持有 5 日收盘；
- 基准：同股票所有可计算日期（排除信号日期）的后 5 日收益；
- 拆分：按月份、按 MA20/MA60 市场状态（up/down/range）。
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
from quant_framework.chan import analyze_chan  # noqa: E402
from run_blind_test import fetch_universe  # noqa: E402

SEED = 20260810
N = 50
OUT = Path(__file__).resolve().parent / "data" / "blind_test_debiased.md"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def regime_of(closes: np.ndarray, i: int) -> str:
    if i < 60:
        return "range"
    ma20 = closes[i - 19 : i + 1].mean()
    ma60 = closes[i - 59 : i + 1].mean()
    if closes[i] > ma20 > ma60:
        return "up"
    if closes[i] < ma20 < ma60:
        return "down"
    return "range"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    universe = fetch_universe()
    rng = random.Random(SEED)
    sample = rng.sample(universe, min(N, len(universe)))

    buy_sig: dict[str, list] = defaultdict(list)
    sell_sig: dict[str, list] = defaultdict(list)
    base_all: list[float] = []
    base_by_month: dict[str, list] = defaultdict(list)
    base_by_regime: dict[str, list] = defaultdict(list)
    sig_by_month: dict[str, list] = defaultdict(list)
    sig_by_regime: dict[str, list] = defaultdict(list)
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
        dates = df["datetime"].dt.strftime("%Y-%m-%d").values
        used += 1

        sig_i: set[int] = set()
        chan = analyze_chan(df)
        label_map = {"buy1": "B1", "buy2": "B2", "buy3": "B3", "sell1": "S1", "sell2": "S2", "sell3": "S3", "sell3_warn": "警"}
        im = {str(pd.Timestamp(ts))[:16].replace(" 00:00", ""): i for i, ts in enumerate(df["datetime"])}
        for p in chan["points"]:
            i = im.get(p["date"])
            label = label_map.get(p["kind"])
            if i is None or label is None or i + 7 >= len(closes):
                continue
            sig_i.add(i)
            # 点 date 为分型日：+1 收盘确认，最早 +2 开盘可交易
            base = opens[i + 2]
            if base <= 0:
                continue
            ret = closes[i + 7] / base - 1.0
            ym = dates[i][:7]
            rg = regime_of(closes, i)
            if p["kind"].startswith("buy"):
                buy_sig["ret"].append(ret)
                buy_sig["ym"].append(ym)
                buy_sig["regime"].append(rg)
                sig_by_month[ym].append(ret)
                sig_by_regime[rg].append(ret)
            else:
                sell_sig["ret"].append(ret)
                sell_sig["ym"].append(ym)
                sell_sig["regime"].append(rg)

        for i in range(len(closes) - 7):
            if i in sig_i or i + 1 in sig_i or i + 2 in sig_i:
                continue
            base = opens[i + 2]
            if base <= 0:
                continue
            ret = closes[i + 7] / base - 1.0
            base_all.append(ret)
            base_by_month[dates[i][:7]].append(ret)
            base_by_regime[regime_of(closes, i)].append(ret)
        print(f"{code} {s['name']} done", flush=True)

    def stat(xs: list[float]) -> tuple[int, float, float]:
        a = np.array(xs)
        return len(a), float(a.mean()), float((a > 0).mean())

    n_b, m_b, p_b = stat(base_all)
    lines = [
        "# 缠论 B/S 盲测基准去偏",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　有效股票：{used}　基准样本：{n_b}",
        "> 收益口径：信号/基准日期后下一日开盘成交、持有 5 日收盘；基准=同股票非信号日期。",
        "",
        f"**全日期基准：均值 {m_b * 100:+.2f}%，正收益概率 {p_b * 100:.0f}%**",
        "",
        "## 缠论买点（B1/B2/B3）",
        "",
    ]
    nb, mb, pb = stat(buy_sig["ret"])
    lines.append(f"- 样本 {nb}　信号均值 **{mb * 100:+.2f}%**　信号正概率 **{pb * 100:.0f}%**")
    lines.append(f"- 基准均值 {m_b * 100:+.2f}%　超额 **{(mb - m_b) * 100:+.2f}%**　正概率差 {pb - p_b:+.0%}")
    lines += ["", "## 缠论卖点（S1/S2/S3/警）", ""]
    ns, ms, ps = stat(sell_sig["ret"])
    lines.append(f"- 样本 {ns}　信号均值 **{ms * 100:+.2f}%**　信号负收益概率 **{(1 - ps) * 100:.0f}%**")
    lines.append(f"- 基准均值 {m_b * 100:+.2f}%　信号低于基准 **{ms - m_b:+.2f}%**（负值=卖点方向有效）")

    lines += ["", "## 按市场状态（MA20/MA60）", "", "| 状态 | 买点样本 | 买点均值 | 基准均值 | 超额 | 卖点样本 | 卖点均值 |", "|---|---|---|---|---|---|---|"]
    for rg in ("up", "down", "range"):
        bm = np.mean(base_by_regime[rg]) if base_by_regime[rg] else 0.0
        bret = [r for r, g in zip(buy_sig["ret"], buy_sig["regime"]) if g == rg]
        sret = [r for r, g in zip(sell_sig["ret"], sell_sig["regime"]) if g == rg]
        lines.append(
            f"| {rg} | {len(bret)} | {np.mean(bret) * 100:+.2f}% | {bm * 100:+.2f}% | {(np.mean(bret) - bm) * 100:+.2f}% | {len(sret)} | {np.mean(sret) * 100:+.2f}% |"
        )

    lines += ["", "## 按月份（样本>=5 的月份）", "", "| 月份 | 买点均值 | 基准均值 | 超额 |", "|---|---|---|---|"]
    for ym in sorted(sig_by_month):
        if len(sig_by_month[ym]) < 5:
            continue
        bm = np.mean(base_by_month[ym]) if base_by_month[ym] else 0.0
        lines.append(f"| {ym} | {np.mean(sig_by_month[ym]) * 100:+.2f}% | {bm * 100:+.2f}% | {(np.mean(sig_by_month[ym]) - bm) * 100:+.2f}% |")

    lines += ["", "## 结论", ""]
    lines.append("- 若超额收益明显为正且跨月份/状态稳定，缠论买点方向优势不完全是均值回归；")
    lines.append("- 若超额接近 0 或集中在少数月份/状态，则 88% 准确率主要来自市场 beta/均值回归。")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已生成：{OUT}")


if __name__ == "__main__":
    main()
