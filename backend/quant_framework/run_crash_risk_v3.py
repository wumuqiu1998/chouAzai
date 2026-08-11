"""暴跌风控 V3：V2 修正版（2026-08-11）。

相对 V2 的修正（对应遗留项 1/3）：
1. 抽样扩大到 800 只（大/中/小 × 沪深均衡）；
2. 同行业基准改为“剔除自身”（组内其他股票等权）；
3. 一字板判定修正：D+1 开盘涨幅≥9.8% 且 high==low（一字板）才算买不进；
   另统计“次日大涨但开盘可买”（V 型反弹买得到）的比例；
4. 消息源保持业绩预告利空（减持/立案批量接口不可用，标注局限）。
"""

from __future__ import annotations

import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import astock  # noqa: E402
from quant_framework.experiments import ExperimentLog  # noqa: E402
from quant_framework.models import ExperimentRecord  # noqa: E402
from run_crash_risk_v2 import load_kline_qfq, load_bad_forecast_dates, st  # noqa: E402
from run_factor_ic_health import fetch_market_with_size  # noqa: E402

SEED = 20260811
N_TOTAL = 800
OUT = Path(__file__).resolve().parent / "data" / "crash_risk_v3.md"
LOG_PATH = Path(__file__).resolve().parent / "data" / "experiments.csv"
IN_START, IN_END = "2025-08-11", "2026-08-11"
OOS_START, OOS_END = "2024-08-11", "2025-08-11"
COST = 0.0003 * 2 + 0.0005 + 0.0001 * 2

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    print("抽样股票池（800）...", flush=True)
    market = fetch_market_with_size()
    by_cap = sorted(market, key=lambda x: x["float_cap"])
    n = len(by_cap)
    layers = [by_cap[: n // 3], by_cap[n // 3 : 2 * n // 3], by_cap[2 * n // 3 :]]
    rng = random.Random(SEED)
    sample = []
    per_layer = N_TOTAL // 3
    for lay in layers:
        sh = [m for m in lay if m["code"].startswith(("6", "9"))]
        sz = [m for m in lay if not m["code"].startswith(("6", "9"))]
        half = per_layer // 2
        sample.extend(rng.sample(sh, min(half, len(sh))))
        sample.extend(rng.sample(sz, min(per_layer - min(half, len(sh)), len(sz))))
    print(f"抽样 {len(sample)} 只", flush=True)

    frames = []
    for i, s in enumerate(sample):
        df = load_kline_qfq(s["code"])
        if df is None:
            continue
        df["code"] = s["code"]
        df["industry"] = s["industry"]
        frames.append(df)
        if (i + 1) % 200 == 0:
            print(f"已加载 {len(frames)}/{i + 1}", flush=True)
    print(f"有效股票 {len(frames)}", flush=True)
    data = pd.concat(frames, ignore_index=True)
    data["date"] = pd.to_datetime(data["datetime"]).dt.date
    data = data.sort_values(["code", "date"]).reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume"):
        data[col] = data[col].astype(float)
    data["ret"] = data.groupby("code")["close"].pct_change()
    data["vol20"] = data.groupby("code")["volume"].transform(lambda x: x.rolling(20).mean())
    data["vol_ratio"] = data["volume"] / data["vol20"]
    data["pos60"] = data.groupby("code")["close"].transform(lambda x: x / x.shift(60) - 1)
    data["ma20"] = data.groupby("code")["close"].transform(lambda x: x.rolling(20).mean())
    data["ma60"] = data.groupby("code")["close"].transform(lambda x: x.rolling(60).mean())
    data["broken"] = (data["close"] < data["ma20"]) & (data["close"] < data["ma60"])
    for h in (5, 10, 20):
        data[f"fwd{h}"] = data.groupby("code")["close"].transform(lambda x, o=h: x.shift(-o) / x - 1)
        g = data.groupby(["date", "industry"])[f"fwd{h}"]
        s = g.transform("sum")
        c = g.transform("count")
        data[f"bench_fwd{h}"] = (s - data[f"fwd{h}"]) / (c - 1).replace(0, np.nan)
        data[f"ex{h}"] = data[f"fwd{h}"] - data[f"bench_fwd{h}"]
        data[f"exnet{h}"] = data[f"ex{h}"] - COST
    data["fwd_late15"] = data.groupby("code")["close"].transform(lambda x: x.shift(-15) / x.shift(5) - 1)
    g = data.groupby(["date", "industry"])["fwd_late15"]
    s = g.transform("sum")
    c = g.transform("count")
    data["bench_late15"] = (s - data["fwd_late15"]) / (c - 1).replace(0, np.nan)
    data["ex_late15"] = data["fwd_late15"] - data["bench_late15"]
    data["d1_open"] = data.groupby("code")["open"].shift(-1)
    data["d1_high"] = data.groupby("code")["high"].shift(-1)
    data["d1_low"] = data.groupby("code")["low"].shift(-1)
    data = data.replace([np.inf, -np.inf], np.nan)

    bad_forecast = load_bad_forecast_dates()
    data["crash"] = (data["ret"] <= -0.07) & (data.groupby("code")["ret"].shift(1) > -0.09)
    ev = data[data["crash"]].copy()
    ev["period"] = np.where((ev["date"].astype(str) >= OOS_START) & (ev["date"].astype(str) < IN_START), "样本外(24-25)", "样本内(25-26)")
    ev["limit_buy_blocked"] = (ev["d1_open"] / ev["close"] - 1.0 >= 0.098) & (ev["d1_high"] == ev["d1_low"])
    ev["d1_big_up_buyable"] = (ev["d1_open"] / ev["close"] - 1.0 >= 0.07) & ~(ev["d1_high"] == ev["d1_low"])
    ev["limit_sell_blocked"] = ev["d1_open"] / ev["close"] - 1.0 <= -0.098
    ev["has_msg"] = ev.apply(
        lambda r: any(
            pd.Timestamp(n).date() <= r["date"] <= pd.Timestamp(n).date() + pd.Timedelta(days=10)
            for n in bad_forecast.get(r["code"], set())
        ),
        axis=1,
    )
    print(f"暴跌事件 {len(ev)}（样本内 {(ev['period'] == '样本内(25-26)').sum()}，样本外 {(ev['period'] == '样本外(24-25)').sum()}）", flush=True)

    groups = {
        "全部暴跌": np.ones(len(ev), dtype=bool),
        "缩量(<0.8)": ev["vol_ratio"] < 0.8,
        "放量(>1.5)": ev["vol_ratio"] > 1.5,
        "高位(前60日>30%)": ev["pos60"] > 0.30,
        "低位(前60日<-10%)": ev["pos60"] < -0.10,
        "未破位": ~ev["broken"],
        "破位": ev["broken"],
        "疑似洗盘(缩量+未破位)": (ev["vol_ratio"] < 1.0) & (~ev["broken"]),
        "有消息(业绩利空10日内)": ev["has_msg"],
        "无消息": ~ev["has_msg"],
    }

    log = ExperimentLog(LOG_PATH)
    lines = [
        "# 暴跌风控 V3：800只 + 基准剔除自身 + 一字板修正（2026-08-11）",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　抽样 {len(frames)} 只（腾讯前复权 700 根）",
        "> 同行业基准剔除自身；事件=单日≤-7%且前一日>-9%；含费用。",
        "",
        "## 一、样本内 vs 样本外（D+1~20 净超额）",
        "",
        "| 分组 | 样本内 n | 样本内净超额 | 样本外 n | 样本外净超额 | 外推一致? |",
        "|---|---|---|---|---|---|",
    ]
    for label, mask in groups.items():
        sub = ev[mask]
        cells = [label]
        pair = {}
        for period in ("样本内(25-26)", "样本外(24-25)"):
            s = st(sub.loc[sub["period"] == period, "exnet20"].dropna())
            pair[period] = s
            cells.append(f"n={s['n']} {s['mean'] * 100:+.2f}% t={s['t']:+.2f}")
        si, oo = pair["样本内(25-26)"], pair["样本外(24-25)"]
        same = "是" if (si["mean"] < 0) == (oo["mean"] < 0) and si["n"] > 30 and oo["n"] > 30 else "否/样本不足"
        cells.append(same)
        lines.append("| " + " | ".join(cells) + " |")

    lines += ["", "## 二、机会成本（合并）", "",
              "| 持有 | n | 平均净超额 | t | 正比例 | 中位 | 正尾部 | 负尾部 | 延迟D+6买15日 |",
              "|---|---|---|---|---|---|---|---|---|"]
    for h in (5, 10, 20):
        s = st(ev[f"exnet{h}"].dropna())
        late = st(ev["ex_late15"].dropna())
        lines.append(
            f"| D+1买持{h}日 | {s['n']} | {s['mean'] * 100:+.2f}% | {s['t']:+.2f} | {s['pos'] * 100:.0f}% | "
            f"{s['med'] * 100:+.2f}% | {s['pos_tail'] * 100:+.2f}% | {s['neg_tail'] * 100:+.2f}% | "
            f"n={late['n']} {late['mean'] * 100:+.2f}% t={late['t']:+.2f} |"
        )
    lines += ["", "## 三、可执行性（一字板修正）", ""]
    lines.append(
        f"- 一字涨停买不进：{int(ev['limit_buy_blocked'].sum())}（{ev['limit_buy_blocked'].mean() * 100:.1f}%）；"
        f"次日开盘大涨≥7%但可买：{int(ev['d1_big_up_buyable'].sum())}（{ev['d1_big_up_buyable'].mean() * 100:.1f}%）；"
        f"一字跌停卖不出：{int(ev['limit_sell_blocked'].sum())}"
    )
    lines += ["", "## 四、消息匹配", "", "| 分组 | n | D+1~20 净超额 | t |", "|---|---|---|---|"]
    for label in ("有消息(业绩利空10日内)", "无消息"):
        s = st(ev.loc[groups[label], "exnet20"].dropna())
        lines.append(f"| {label} | {s['n']} | {s['mean'] * 100:+.2f}% | {s['t']:+.2f} |")
    lines += ["", "## 结论", ""]
    lines.append("- 若核心分组样本外方向与样本内一致，V2 结论在更大样本+更严基准下仍然成立。")
    lines.append("- 局限：消息源仅业绩预告（减持/立案批量接口不可用）；抽样 800 只。")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    code_version = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip() or "dev"
    for label in ("全部暴跌", "疑似洗盘(缩量+未破位)", "有消息(业绩利空10日内)"):
        sub = ev[groups[label]]
        for period in ("样本内(25-26)", "样本外(24-25)"):
            s = st(sub.loc[sub["period"] == period, "exnet20"].dropna())
            log.append(
                ExperimentRecord(
                    experiment_id=f"CRASHV3-{label[:8]}-{period[:4]}",
                    hypothesis=f"暴跌风控V3：{label} {period} 净超额（800只+剔自身基准）",
                    unique_change=f"n=800, bench_excl_self=True, limit_fix=True",
                    expected="样本外方向与样本内一致",
                    dev_result=f"n={s['n']} {s['mean'] * 100:+.2f}% t={s['t']:+.2f}",
                    val_result="",
                    cost_result=f"正比例 {s['pos'] * 100:.0f}%",
                    passed=False,
                    failure_reason="消息源仅业绩预告/单样本外时段",
                    code_version=code_version,
                )
            )
    print(f"\n报告已生成：{OUT}，日志追加 {len(groups) * 2} 条")


if __name__ == "__main__":
    main()
