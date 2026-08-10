"""缠论买点组合回测的胜负归因分析。

对每笔完整交易（B 点 T+2 开盘买入、持有 5 日、含费用/涨跌停）统计特征：
- 信号类型 B1/B2/B3；
- 个股相对 MA20（上方/下方）；
- 大盘（上证）相对 MA20（上方/下方）；
- 信号前 5/10 日收益（超跌程度）；
- 买入日开盘相对昨收（高开/平开/低开）。

输出：总体胜率、分组胜率、盈利笔 vs 亏损笔特征对比。
"""

from __future__ import annotations

import random
import sys
import json
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
import requests  # noqa: E402

SEED = 20260810
N = 50
LIMIT = 0.098
COMMISSION = 0.0003
STAMP = 0.0005
SLIPPAGE = 0.0001
OUT = Path(__file__).resolve().parent / "data" / "chan_winloss_analysis.md"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def net_ret(opens, closes, idx) -> float | None:
    if idx + 7 >= len(closes):
        return None
    prev = closes[idx + 1]
    buy = opens[idx + 2]
    if prev <= 0 or buy <= 0 or buy / prev - 1.0 >= LIMIT - 1e-6:
        return None
    sell = closes[idx + 7]
    if sell / closes[idx + 6] - 1.0 <= -LIMIT + 1e-6:
        return None
    return sell * (1 - SLIPPAGE) / (buy * (1 + SLIPPAGE)) - 1.0 - COMMISSION * 2 - STAMP


def fetch_sina_kline(code: str, n: int = 260, prefix: str = "") -> pd.DataFrame | None:
    """新浪日K（腾讯WAF临时不可用时备用）。"""
    symbol = prefix or ("sh" if code.startswith(("5", "6", "9")) else "sz") + code
    try:
        r = requests.get(
            "https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20data=/CN_MarketDataService.getKLineData",
            params={"symbol": symbol, "scale": "240", "ma": "no", "datalen": str(n)},
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"},
            timeout=15, proxies={"http": None, "https": None},
        )
        txt = r.text
        data = json.loads(txt[txt.find("(") + 1:txt.rfind(")")])
        if not data:
            return None
        return pd.DataFrame(
            [
                {
                    "datetime": d["day"],
                    "open": float(d["open"]),
                    "high": float(d["high"]),
                    "low": float(d["low"]),
                    "close": float(d["close"]),
                    "volume": float(d["volume"]),
                }
                for d in data
            ]
        )
    except Exception as e:  # noqa: BLE001
        print(f"warn sina {code}: {e}")
        return None


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    universe = fetch_universe()
    rng = random.Random(SEED)
    sample = rng.sample(universe, min(N, len(universe)))

    # 大盘 MA20 状态（T-1 判定）
    market_ok: dict[str, bool] = {}
    try:
        idf = fetch_sina_kline("000001", 300, prefix="sh000001")
        idf["datetime"] = pd.to_datetime(idf["datetime"])
        idf = idf.sort_values("datetime").reset_index(drop=True)
        idf["ma20"] = idf["close"].rolling(20).mean()
        idf["ok"] = (idf["close"].shift(1) > idf["ma20"].shift(1)).fillna(True)
        market_ok = {str(row["datetime"].date()): bool(row["ok"]) for _, row in idf.iterrows()}
    except Exception as e:  # noqa: BLE001
        print("warn 指数", e)

    trades: list[dict] = []
    for s in sample:
        code = s["code"]
        df = fetch_sina_kline(code, 260)
        if df is None or len(df) < 250:
            continue
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        opens = df["open"].astype(float).values
        closes = df["close"].astype(float).values
        dates = df["datetime"].dt.strftime("%Y-%m-%d").values
        ma20 = pd.Series(closes).rolling(20).mean().values
        im = {str(pd.Timestamp(ts))[:16].replace(" 00:00", ""): i for i, ts in enumerate(df["datetime"])}
        for p in analyze_chan(df)["points"]:
            i = im.get(p["date"])
            if i is None or not p["kind"].startswith("buy"):
                continue
            r = net_ret(opens, closes, i)
            if r is None or i < 20:
                continue
            pre5 = closes[i] / closes[i - 5] - 1.0
            pre10 = closes[i] / closes[i - 10] - 1.0
            pre20 = closes[i] / closes[i - 20] - 1.0
            gap = opens[i + 2] / closes[i + 1] - 1.0
            trades.append(
                {
                    "code": code,
                    "kind": p["kind"],
                    "net": r,
                    "pre5": pre5,
                    "pre10": pre10,
                    "pre20": pre20,
                    "gap": gap,
                    "above_ma20": bool(closes[i] > ma20[i]),
                    "market_ok": market_ok.get(dates[i], True),
                    "date": dates[i],
                }
            )
        print(f"{code} done", flush=True)

    t = pd.DataFrame(trades)
    lines = [
        "# 缠论买点胜负归因分析（组合回测逐笔）",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　交易笔数：{len(t)}　胜率：{(t['net'] > 0).mean() * 100:.0f}%",
        "> 口径：B 点 T+2 开盘买入、持有 5 日、含费用与涨跌停约束（与组合回测一致）。",
        "",
        "## 盈利笔 vs 亏损笔特征对比",
        "",
        "| 特征 | 盈利笔均值 | 亏损笔均值 |",
        "|---|---|---|",
    ]
    win = t[t["net"] > 0]
    lose = t[t["net"] <= 0]
    for col, label in (("pre5", "信号前5日收益"), ("pre10", "信号前10日收益"), ("pre20", "信号前20日收益"), ("gap", "买入日开盘gap")):
        lines.append(f"| {label} | {win[col].mean() * 100:+.2f}% | {lose[col].mean() * 100:+.2f}% |")
    lines += ["", "## 按信号类型", "", "| 类型 | 笔数 | 胜率 | 平均净收益 |", "|---|---|---|---|"]
    for k in ("buy1", "buy2", "buy3"):
        sub = t[t["kind"] == k]
        if len(sub) == 0:
            continue
        lines.append(f"| {k.upper()} | {len(sub)} | {(sub['net'] > 0).mean() * 100:.0f}% | {sub['net'].mean() * 100:+.2f}% |")
    lines += ["", "## 按大盘 MA20 状态（T-1）", "", "| 状态 | 笔数 | 胜率 | 平均净收益 |", "|---|---|---|---|"]
    for ok, label in ((True, "大盘均线上方"), (False, "大盘均线下方")):
        sub = t[t["market_ok"] == ok]
        lines.append(f"| {label} | {len(sub)} | {(sub['net'] > 0).mean() * 100:.0f}% | {sub['net'].mean() * 100:+.2f}% |")
    lines += ["", "## 按个股 MA20 状态", "", "| 状态 | 笔数 | 胜率 | 平均净收益 |", "|---|---|---|---|"]
    for ok, label in ((True, "个股均线上方"), (False, "个股均线下方")):
        sub = t[t["above_ma20"] == ok]
        lines.append(f"| {label} | {len(sub)} | {(sub['net'] > 0).mean() * 100:.0f}% | {sub['net'].mean() * 100:+.2f}% |")
    lines += ["", "## 按超跌程度（信号前10日收益）", "", "| 分组 | 笔数 | 胜率 | 平均净收益 |", "|---|---|---|---|"]
    for lo, hi, label in ((-999, -0.10, "<-10%"), (-0.10, 0, "-10%~0"), (0, 999, ">0")):
        sub = t[(t["pre10"] >= lo) & (t["pre10"] < hi)]
        if len(sub) == 0:
            continue
        lines.append(f"| {label} | {len(sub)} | {(sub['net'] > 0).mean() * 100:.0f}% | {sub['net'].mean() * 100:+.2f}% |")
    lines += ["", "## 按买入日开盘 gap", "", "| 分组 | 笔数 | 胜率 | 平均净收益 |", "|---|---|---|---|"]
    for lo, hi, label in ((-999, -0.005, "低开"), (-0.005, 0.005, "平开"), (0.005, 999, "高开>0.5%")):
        sub = t[(t["gap"] >= lo) & (t["gap"] < hi)]
        if len(sub) == 0:
            continue
        lines.append(f"| {label} | {len(sub)} | {(sub['net'] > 0).mean() * 100:.0f}% | {sub['net'].mean() * 100:+.2f}% |")
    lines += ["", "## 规律小结", ""]
    lines.append("- 对比盈利/亏损笔特征，若某特征差异明显（如盈利笔超跌更深/大盘均线上方占比更高），即为胜负规律；")
    lines.append("- 分组胜率显著高于总体（>80%）的分组可作为条件过滤候选。")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已生成：{OUT}")


if __name__ == "__main__":
    main()
