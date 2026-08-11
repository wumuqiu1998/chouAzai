"""全量卖出信号实验：买入固定缠论买点，卖出端轮换 skill 内所有卖出信号。

不再限制 5 日卖出日：每个卖出信号自由触发，仅保留 max_hold=120 日兜底强平。
卖出信号池：
- chan      ：缠论 S1/S2/S3（j+2 开盘）
- warn      ：三卖预警 sell3_warn（确认日 j+1 开盘）
- atr_top   ：ATR 顶（确认日 T+1 开盘）
- overheat  ：ATR 超涨（T+1 开盘）
- upthrust  ：威科夫派发 Upthrust（j+1 开盘）
- sweep     ：SMC 看跌扫荡（收回日 +1 开盘）
- break     ：SMC 向下破位 BOS（结构确认 +3 开盘）
- choch     ：SMC 结构变化 CHoCH（+3 开盘）
- vol_div   ：新高缩量（+1 开盘）
- ma20      ：跌破 MA20（+1 开盘）
- trail5/8/12：买入后最高点回撤 5%/8%/12%（触发日收盘）
- divergence：MACD 顶背离（+1 开盘）

每轮输出：单笔平均净收益、胜率、总收益、最大回撤、触发率，并写入 experiments.csv。
"""

from __future__ import annotations

import random
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from quant_framework.atr import compute_atr  # noqa: E402
from quant_framework.chan import analyze_chan  # noqa: E402
from quant_framework.experiments import ExperimentLog  # noqa: E402
from quant_framework.models import ExperimentRecord  # noqa: E402
from quant_framework.smc import analyze_smc  # noqa: E402
from quant_framework.wyckoff import analyze_wyckoff  # noqa: E402
from run_blind_test import fetch_universe  # noqa: E402
from run_chan_buy_portfolio import fetch_sina_kline, run_portfolio  # noqa: E402

SEED = 20260810
N = 50
MAX_HOLD = 120
OUT = Path(__file__).resolve().parent / "data" / "exit_signals_all.md"
LOG_PATH = Path(__file__).resolve().parent / "data" / "experiments.csv"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def build_signal_maps(df: pd.DataFrame) -> dict[str, dict[str, float]]:
    """每只股票：各卖出信号 {执行日: 执行价}。"""
    opens = df["open"].astype(float).values
    closes = df["close"].astype(float).values
    vols = df["volume"].astype(float).values
    dates = df["datetime"].dt.strftime("%Y-%m-%d").values
    im = {str(pd.Timestamp(ts))[:16].replace(" 00:00", ""): i for i, ts in enumerate(df["datetime"])}
    maps: dict[str, dict[str, float]] = {k: {} for k in (
        "chan", "warn", "atr_top", "overheat", "upthrust", "sweep", "break", "choch", "vol_div", "ma20", "trail5", "trail8", "trail12", "divergence",
    )}

    chan = analyze_chan(df)
    for p in chan["points"]:
        j = im.get(p["date"])
        if j is None:
            continue
        if p["kind"] in ("sell1", "sell2", "sell3") and j + 2 < len(closes):
            maps["chan"][dates[j + 2]] = opens[j + 2]
        elif p["kind"] == "sell3_warn" and j + 1 < len(closes):
            maps["warn"][dates[j + 1]] = opens[j + 1]

    for s in compute_atr(df)["signals"]:
        t = im.get(s["date"])
        if t is None or t + 1 >= len(closes):
            continue
        if s["kind"] == "top":
            maps["atr_top"][dates[t + 1]] = opens[t + 1]
        elif s["kind"] == "overheat":
            maps["overheat"][dates[t + 1]] = opens[t + 1]

    for s in (analyze_wyckoff(df).get("signals") or []):
        j = im.get(s["date"])
        if j is not None and j + 1 < len(closes) and s["kind"] == "upthrust":
            maps["upthrust"][dates[j + 1]] = opens[j + 1]

    smc = analyze_smc(df, sweep_min_gap=0)
    for s in smc.get("sweeps") or []:
        j = im.get(s["date"])
        if j is not None and j + 1 < len(closes) and s["kind"] == "bearish":
            maps["sweep"][dates[j + 1]] = opens[j + 1]
    st = smc.get("structure") or {}
    for key, target in (("last_bos", "break"), ("last_choch", "choch")):
        item = st.get(key)
        if not item:
            continue
        j = im.get(item["date"])
        if j is not None and j + 3 < len(closes) and (key != "last_bos" or item["kind"] == "bearish"):
            maps[target][dates[j + 3]] = opens[j + 3]

    ma20 = pd.Series(closes).rolling(20).mean().values
    for k in range(21, len(closes) - 1):
        if closes[k] < ma20[k]:
            maps["ma20"][dates[k + 1]] = opens[k + 1]
    for k in range(20, len(closes)):
        prev_high = closes[k - 20:k].max()
        if closes[k] >= prev_high:
            v_avg = vols[k - 5:k].mean()
            if v_avg > 0 and vols[k] <= v_avg * 0.85 and k + 1 < len(closes):
                maps["vol_div"][dates[k + 1]] = opens[k + 1]

    ema12 = pd.Series(closes).ewm(span=12, adjust=False).mean().values
    ema26 = pd.Series(closes).ewm(span=26, adjust=False).mean().values
    dif = ema12 - ema26
    new_highs: list[int] = []
    for k in range(20, len(closes)):
        if closes[k] > closes[k - 20:k].max():
            if new_highs and dif[k] < dif[new_highs[-1]] and k + 1 < len(closes):
                maps["divergence"][dates[k + 1]] = opens[k + 1]
            new_highs.append(k)
    return maps


def first_exit(signal_map: dict[str, float], dates: list[str], buy_idx: int, max_hold: int = MAX_HOLD) -> tuple[str, float] | None:
    buy_day = dates[buy_idx + 2]
    for k in range(buy_idx + 2, min(buy_idx + 2 + max_hold + 1, len(dates))):
        d = dates[k]
        if d in signal_map and d > buy_day:
            return d, signal_map[d]
    return None


def trailing_exit(closes: np.ndarray, dates: list[str], buy_idx: int, pct: float, max_hold: int = MAX_HOLD) -> tuple[str, float] | None:
    buy_day = dates[buy_idx + 2]
    run_high = closes[buy_idx + 1]
    for k in range(buy_idx + 2, min(buy_idx + 2 + max_hold + 1, len(closes))):
        run_high = max(run_high, closes[k])
        if closes[k] <= run_high * (1 - pct):
            return dates[k], closes[k]
    return None


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    universe = fetch_universe()
    rng = random.Random(SEED)
    sample = rng.sample(universe, min(N, len(universe)))
    events: list[dict] = []
    close_map: dict[str, dict[str, float]] = {}

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
        for _, row in df.iterrows():
            d = str(row["datetime"].date())
            close_map.setdefault(d, {})[code] = float(row["close"])
        maps = build_signal_maps(df)
        im = {str(pd.Timestamp(ts))[:16].replace(" 00:00", ""): i for i, ts in enumerate(df["datetime"])}
        for p in analyze_chan(df)["points"]:
            i = im.get(p["date"])
            if i is None or not p["kind"].startswith("buy") or i + 7 >= len(closes):
                continue
            prev = closes[i + 1]
            buy = opens[i + 2]
            if prev <= 0 or buy <= 0 or buy / prev - 1.0 >= 0.098:
                continue
            e: dict = {
                "code": code,
                "type": p["kind"],
                "buy_date": dates[i + 2],
                "buy_px": buy,
                "blocked": False,
                "exits": {},
            }
            for sig in ("chan", "warn", "atr_top", "overheat", "upthrust", "sweep", "break", "choch", "vol_div", "ma20", "divergence"):
                ex = first_exit(maps[sig], dates, i)
                if ex:
                    e["exits"][sig] = ex
            for pct, key in ((0.05, "trail5"), (0.08, "trail8"), (0.12, "trail12")):
                ex = trailing_exit(closes, dates, i, pct)
                if ex:
                    e["exits"][key] = ex
            # 兜底：max_hold 日强平
            fallback_k = min(i + 2 + MAX_HOLD, len(closes) - 1)
            e["fallback"] = (dates[fallback_k], closes[fallback_k])
            events.append(e)
        print(f"{code} done", flush=True)

    log = ExperimentLog(LOG_PATH)
    lines = [
        "# 全量卖出信号实验（不限制卖出日，max_hold=120日兜底）",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　信号数：{len(events)}",
        "> 买入固定缠论买点；卖出信号自由触发，120 日无信号则强平。",
        "",
        "| 卖出信号 | 持仓/仓位 | 笔数 | 触发率 | 单笔平均净收益 | 胜率 | 总收益 | 最大回撤 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    signals = ("chan", "warn", "atr_top", "overheat", "upthrust", "sweep", "break", "choch", "vol_div", "ma20", "trail5", "trail8", "trail12", "divergence")
    for sig in signals:
        for mp, cap in ((5, 0.1), (10, 0.2)):
            evs_round = []
            trig = 0
            for e in events:
                ex = e["exits"].get(sig) or e["fallback"]
                if e["exits"].get(sig):
                    trig += 1
                evs_round.append({**e, "sell_date": ex[0], "sell_px": ex[1]})
            r = run_portfolio(evs_round, mp, cap, close_map, exit_rule="fixed")
            nets = [t["ret"] for t in r["trades"] if t.get("ret") is not None]
            avg_net = float(np.mean(nets)) if nets else 0.0
            lines.append(
                f"| {sig} | {mp}/{cap:.0%} | {r['n_trades']} | {trig / max(1, len(events)) * 100:.0f}% | "
                f"{avg_net * 100:+.2f}% | {r['win_rate'] * 100:.0f}% | {r['total_ret'] * 100:+.1f}% | {r['mdd'] * 100:.1f}% |"
            )
            log.append(
                ExperimentRecord(
                    experiment_id=f"EXITALL-{sig.upper()}-{mp}-{int(cap * 100)}",
                    hypothesis=f"全量卖出信号：{sig}（不限制卖出日，max_hold=120）",
                    unique_change=f"exit_signal={sig}, max_positions={mp}, cap={cap}",
                    expected="不同卖出信号对单笔收益/回撤的影响",
                    dev_result=f"触发率 {trig / max(1, len(events)) * 100:.0f}%，单笔均值 {avg_net * 100:+.2f}%，胜率 {r['win_rate'] * 100:.0f}%",
                    val_result="",
                    cost_result=f"总收益 {r['total_ret'] * 100:+.1f}%，回撤 {r['mdd'] * 100:.1f}%",
                    passed=False,
                    failure_reason="一年窗口/单一样本池，未做样本外与盲测",
                    code_version=subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip() or "dev",
                )
            )
    lines += ["", "## 结论", ""]
    lines.append("- 对比触发率/单笔均值/胜率/总收益/回撤，筛选最有效卖出信号。")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已生成：{OUT}，日志追加 {len(signals) * 2} 条")


if __name__ == "__main__":
    main()
