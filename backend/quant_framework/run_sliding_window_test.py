"""滑动窗口大环境测试：观察窗口收缩为 60 个交易日。

对同一支股票的约一年历史（260 个交易日），用 60 日滑动窗口（步长 20）切分不同大环境，
统计每个环境下缠论买点信号的表现，回答“策略是否环境依赖”。

环境定义：信号日前 60 个交易日的涨跌幅（ret60）：
- 大涨：ret60 > +8%
- 震荡：-8% <= ret60 <= +8%
- 大跌：ret60 < -8%

信号口径与盲测一致：B1/B2/B3，T+2 开盘买入、持有 5 日收盘收益。
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
WINDOW = 60
STEP = 20
OUT = Path(__file__).resolve().parent / "data" / "sliding_window_test.md"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def env_of(ret60: float) -> str:
    if ret60 > 0.08:
        return "大涨"
    if ret60 < -0.08:
        return "大跌"
    return "震荡"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    universe = fetch_universe()
    rng = random.Random(SEED)
    sample = rng.sample(universe, min(N, len(universe)))

    env_agg: dict[str, dict] = defaultdict(lambda: {"n": 0, "rets": []})
    env_year: dict[str, dict] = defaultdict(lambda: defaultdict(list))
    per_code: dict[str, dict] = defaultdict(lambda: defaultdict(lambda: {"n": 0, "rets": []}))
    windows_total = 0
    windows_with_sig = 0
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
        last = str(df["datetime"].iloc[-1].date())
        if last < "2026-01-01":
            continue  # 排除退市/数据异常
        closes = df["close"].astype(float).values
        opens = df["open"].astype(float).values
        dates = df["datetime"].dt.strftime("%Y-%m-%d").values
        used += 1

        # 信号：与盲测一致（T+2 买入，5 日收益）
        sig_days: set[int] = set()
        sig_list: list[dict] = []
        im = {str(pd.Timestamp(ts))[:16].replace(" 00:00", ""): i for i, ts in enumerate(df["datetime"])}
        for p in analyze_chan(df)["points"]:
            i = im.get(p["date"])
            if i is None or not p["kind"].startswith("buy") or i + 7 >= len(closes):
                continue
            base = opens[i + 2]
            if base <= 0:
                continue
            ret = closes[i + 7] / base - 1.0
            sig_days.add(i)
            sig_list.append({"i": i, "ret": ret, "date": dates[i]})

        # 滑动窗口（60 日，步长 20）：统计每个窗口内出现的信号
        n_win = 0
        for start in range(0, len(df) - WINDOW, STEP):
            n_win += 1
            end = start + WINDOW
            win_sigs = [sg for sg in sig_list if start <= sg["i"] < end]
            if win_sigs:
                windows_with_sig += 1
            win_ret = closes[end] / closes[start] - 1.0
            env = env_of(win_ret)
            for sg in win_sigs:
                env_agg[env]["n"] += 1
                env_agg[env]["rets"].append(sg["ret"])
                env_year[env][sg["date"][:4]].append(sg["ret"])
                per_code[code][env]["n"] += 1
                per_code[code][env]["rets"].append(sg["ret"])
        windows_total += n_win
        print(f"{code} {s['name']} done", flush=True)

    lines = [
        "# 滑动窗口大环境测试（60 日观察窗口）",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　有效股票：{used}　"
        f"滑动窗口：60 日、步长 20（每只约 {n_win} 个窗口，共 {windows_total} 个）",
        "> 环境 = 信号/窗口前 60 日涨跌幅：大涨 >+8%、震荡 ±8%、大跌 <-8%。",
        "",
        "## 按环境汇总",
        "",
        "| 环境 | 样本 | 平均收益 | 胜率 |",
        "|---|---|---|---|",
    ]
    order = ("大涨", "震荡", "大跌")
    for env in order:
        v = env_agg.get(env)
        if not v or v["n"] == 0:
            lines.append(f"| {env} | 0 | - | - |")
            continue
        arr = np.array(v["rets"])
        lines.append(f"| {env} | {v['n']} | {arr.mean() * 100:+.2f}% | {(arr > 0).mean() * 100:.0f}% |")

    lines += ["", "## 环境 × 年份", "", "| 环境 | 年份 | 样本 | 平均收益 | 胜率 |", "|---|---|---|---|---|"]
    for env in order:
        for yr in sorted(env_year.get(env, {})):
            arr = np.array(env_year[env][yr])
            if len(arr) < 5:
                continue
            lines.append(f"| {env} | {yr} | {len(arr)} | {arr.mean() * 100:+.2f}% | {(arr > 0).mean() * 100:.0f}% |")

    lines += ["", "## 每只股票按环境（样本>=5）", "", "| 股票 | 环境 | 样本 | 平均收益 | 胜率 |", "|---|---|---|---|---|"]
    for code in sorted(per_code):
        for env in order:
            v = per_code[code].get(env)
            if not v or v["n"] < 5:
                continue
            arr = np.array(v["rets"])
            lines.append(f"| {code} | {env} | {v['n']} | {arr.mean() * 100:+.2f}% | {(arr > 0).mean() * 100:.0f}% |")

    lines += ["", "## 结论", ""]
    lines.append("- 若三档环境胜率/收益接近，策略不依赖环境；若大跌环境显著更高，说明本质是超跌反弹策略；")
    lines.append("- 若大涨环境样本少或为负，说明追涨端无效，应只在超跌环境使用。")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已生成：{OUT}")


if __name__ == "__main__":
    main()
