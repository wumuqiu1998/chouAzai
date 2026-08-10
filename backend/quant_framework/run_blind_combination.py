"""缠论买点组合级验证：逐股显著性 + B1/B2/B3 拆分 + 行业/市值分桶。

在 50 只随机盲测的基础上回答：
1) 缠论买点优势是普遍现象还是集中在少数股票？
2) B1/B2/B3 哪个贡献最大？
3) 收益是否集中在特定行业/市值段？
"""

from __future__ import annotations

import math
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
from quant_framework.chan import analyze_chan  # noqa: E402

SEED = 20260810
N = 50
OUT = Path(__file__).resolve().parent / "data" / "blind_combination.md"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0 Safari/537.36", "Referer": "https://quote.eastmoney.com/"}

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def fetch_universe_rich() -> list[dict]:
    out: list[dict] = []
    for pn in range(1, 13):
        try:
            r = requests.get(
                "https://push2delay.eastmoney.com/api/qt/clist/get",
                params={
                    "pn": pn, "pz": 100, "po": 1, "np": 1, "fltt": 2, "invt": 2,
                    "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
                    "fields": "f12,f14,f100,f20",
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
                try:
                    mcap = float(x.get("f20") or 0)
                except (TypeError, ValueError):
                    mcap = 0.0
                out.append({"code": code, "name": name, "industry": str(x.get("f100", "")), "mcap": mcap})
        except Exception as e:  # noqa: BLE001
            print("universe warn", e)
        time.sleep(1.0)
    return out


def ztest(mean1: float, n1: int, var1: float, mean2: float, n2: int, var2: float) -> float:
    se = math.sqrt(var1 / n1 + var2 / n2)
    if se <= 0:
        return 0.0
    return (mean1 - mean2) / se


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    universe = fetch_universe_rich()
    rng = random.Random(SEED)
    sample = rng.sample(universe, min(N, len(universe)))

    by_type: dict[str, list] = defaultdict(list)
    by_code: dict[str, dict] = defaultdict(lambda: {"n": 0, "rets": [], "base": []})
    by_industry: dict[str, list] = defaultdict(list)
    by_mcap: dict[str, list] = defaultdict(list)
    base_all: list[float] = []
    oversold_base: list[float] = []
    buy_all: list[float] = []
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
        mcap = s.get("mcap") or 0
        industry = s.get("industry") or "未知"
        used += 1

        sig_i: set[int] = set()
        chan = analyze_chan(df)
        im = {str(pd.Timestamp(ts))[:16].replace(" 00:00", ""): i for i, ts in enumerate(df["datetime"])}
        for p in chan["points"]:
            i = im.get(p["date"])
            if i is None or not p["kind"].startswith("buy") or i + 7 >= len(closes):
                continue
            sig_i.add(i)
            base = opens[i + 2]
            if base <= 0:
                continue
            ret = closes[i + 7] / base - 1.0
            buy_all.append(ret)
            by_type[p["kind"]].append(ret)
            by_code[code]["n"] += 1
            by_code[code]["rets"].append(ret)
            by_industry[industry].append(ret)
            bucket = "大市值" if mcap >= 50e9 else ("中市值" if mcap >= 10e9 else "小市值")
            by_mcap[bucket].append(ret)

        for i in range(len(closes) - 7):
            if i in sig_i or i + 1 in sig_i or i + 2 in sig_i:
                continue
            base = opens[i + 2]
            if base <= 0:
                continue
            ret = closes[i + 7] / base - 1.0
            base_all.append(ret)
            if i >= 10 and closes[i] / closes[i - 10] - 1.0 <= -0.10:
                oversold_base.append(ret)
            by_code[code]["base"].append(ret)
        print(f"{code} {s['name']} done", flush=True)

    b = np.array(base_all)
    o = np.array(oversold_base) if oversold_base else np.array([0.0])
    buy = np.array(buy_all)
    lines = [
        "# 缠论买点组合级验证（50 只随机盲测）",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　有效股票：{used}",
        f"> 全日期基准：均值 {b.mean() * 100:+.2f}%、正概率 {(b > 0).mean() * 100:.0f}%；"
        f"超跌对照（过去10日跌超10%）：均值 {o.mean() * 100:+.2f}%、正概率 {(o > 0).mean() * 100:.0f}%、样本 {len(o)}",
        f"> 缠论买点 vs 超跌对照超额：**{(buy.mean() - o.mean()) * 100:+.2f}%**",
        "",
        "## B1/B2/B3 拆分",
        "",
        "| 类型 | 样本 | 平均收益 | 正概率 | 相对基准超额 |",
        "|---|---|---|---|---|",
    ]
    for k in ("buy1", "buy2", "buy3"):
        v = np.array(by_type.get(k, []))
        if len(v) == 0:
            lines.append(f"| {k.upper()} | 0 | - | - | - |")
            continue
        lines.append(f"| {k.upper()} | {len(v)} | {v.mean() * 100:+.2f}% | {(v > 0).mean() * 100:.0f}% | {(v.mean() - b.mean()) * 100:+.2f}% |")

    lines += ["", "## 行业分桶（样本>=5）", "", "| 行业 | 样本 | 平均收益 | 正概率 |", "|---|---|---|---|"]
    for ind in sorted(by_industry, key=lambda x: -len(by_industry[x])):
        v = np.array(by_industry[ind])
        if len(v) < 5:
            continue
        lines.append(f"| {ind} | {len(v)} | {v.mean() * 100:+.2f}% | {(v > 0).mean() * 100:.0f}% |")

    lines += ["", "## 市值分桶", "", "| 分桶 | 样本 | 平均收益 | 正概率 |", "|---|---|---|---|"]
    for bucket in ("小市值", "中市值", "大市值"):
        v = np.array(by_mcap.get(bucket, []))
        if len(v) == 0:
            continue
        lines.append(f"| {bucket} | {len(v)} | {v.mean() * 100:+.2f}% | {(v > 0).mean() * 100:.0f}% |")

    lines += ["", "## 逐股显著性（样本>=8，按超额排序）", "", "| 股票 | 样本 | 信号均值 | 基准均值 | 超额 | z值 |", "|---|---|---|---|---|---|"]
    rows = []
    for code, v in by_code.items():
        if v["n"] < 8 or len(v["base"]) < 30:
            continue
        a = np.array(v["rets"])
        bb = np.array(v["base"])
        z = ztest(a.mean(), len(a), a.var(), bb.mean(), len(bb), bb.var())
        rows.append((code, v["n"], a.mean(), bb.mean(), a.mean() - bb.mean(), z))
    for code, n, ms, mb_, ex, z in sorted(rows, key=lambda x: -x[4]):
        lines.append(f"| {code} | {n} | {ms * 100:+.2f}% | {mb_ * 100:+.2f}% | {ex * 100:+.2f}% | {z:+.2f} |")
    n_pos = sum(1 for r in rows if r[4] > 0 and r[5] > 1.96)
    lines += ["", "## 结论", ""]
    lines.append(f"- 50 只中显著（z>1.96）且超额为正的股票：{n_pos}/{len(rows)}（仅统计样本>=8 的股票）")
    lines.append("- 若显著股票占比低，说明优势集中在少数股票；若高，说明普遍存在。")
    lines.append(f"- 对照检查：缠论买点相对全日期超额 {(buy.mean() - b.mean()) * 100:+.2f}%，"
                 f"相对“超跌反转”对照超额 {(buy.mean() - o.mean()) * 100:+.2f}%；"
                 "若后者接近 0，说明买点只是超跌反弹代理，无独立 Alpha。")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已生成：{OUT}")


if __name__ == "__main__":
    main()
