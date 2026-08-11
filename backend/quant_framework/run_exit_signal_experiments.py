"""卖出信号消融实验：买入端固定缠论买点，卖出端轮换不同信号。

卖出信号：
- expire    ：固定持有 5 日到期卖出（基线）
- chan      ：缠论 S1/S2/S3（点日期 j → j+2 开盘卖出）
- atr_top   ：ATR 顶（超涨段回落 ≥1×ATR 确认日 T → T+1 开盘卖出）
- divergence：MACD 顶背离（收盘创 20 日新高但 DIF 低于上一个新高日的 DIF → 次日开盘卖出）

每轮用组合资金模拟（100 万、持仓上限 5/10、单票仓位 10%/20%），
并把结果写入 experiments.csv（含失败/未验证实验）。
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
from run_blind_test import fetch_universe  # noqa: E402
from run_chan_buy_portfolio import fetch_sina_kline, run_portfolio  # noqa: E402

SEED = 20260810
N = 50
OUT = Path(__file__).resolve().parent / "data" / "exit_signal_experiments.md"
LOG_PATH = Path(__file__).resolve().parent / "data" / "experiments.csv"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def precompute_exits(df: pd.DataFrame) -> dict[str, dict]:
    """对每只股票预计算所有卖出信号执行日 → 开盘价。"""
    opens = df["open"].astype(float).values
    closes = df["close"].astype(float).values
    dates = df["datetime"].dt.strftime("%Y-%m-%d").values
    im = {str(pd.Timestamp(ts))[:16].replace(" 00:00", ""): i for i, ts in enumerate(df["datetime"])}
    chan = analyze_chan(df)

    # 缠论卖点：S 点点日期 j → j+2 开盘
    chan_exit: dict[str, float] = {}
    for p in chan["points"]:
        if p["kind"].startswith("sell") and not p["kind"].endswith("_warn"):
            j = im.get(p["date"])
            if j is not None and j + 2 < len(closes):
                chan_exit[dates[j + 2]] = opens[j + 2]

    # ATR 顶：确认日 T → T+1 开盘
    atr_exit: dict[str, float] = {}
    for s in compute_atr(df)["signals"]:
        if s["kind"] == "top":
            t = im.get(s["date"])
            if t is not None and t + 1 < len(closes):
                atr_exit[dates[t + 1]] = opens[t + 1]

    # MACD 顶背离：收盘创 20 日新高但 DIF 低于上一个新高日的 DIF → 次日开盘
    ema12 = pd.Series(closes).ewm(span=12, adjust=False).mean().values
    ema26 = pd.Series(closes).ewm(span=26, adjust=False).mean().values
    dif = ema12 - ema26
    new_highs: list[int] = []
    div_exit: dict[str, float] = {}
    for k in range(20, len(closes)):
        if closes[k] > closes[k - 20:k].max():
            if new_highs and dif[k] < dif[new_highs[-1]] and k + 1 < len(closes):
                div_exit[dates[k + 1]] = opens[k + 1]
            new_highs.append(k)
    return {"chan": chan_exit, "atr": atr_exit, "div": div_exit, "dates": dates, "opens": opens}


def pick_exit(exits: dict[str, dict], buy_idx: int, buy_day: str, hold: int = 5) -> tuple[str | None, str | None, float | None]:
    """在买入后 hold 日窗口内取第一个可执行卖出信号（执行日严格晚于买入执行日）。"""
    dates = exits["dates"]
    result: dict[str, tuple] = {}
    for sig in ("chan", "atr", "div"):
        m = exits[sig]
        for k in range(buy_idx + 2, min(buy_idx + 2 + hold + 1, len(dates))):
            d = dates[k]
            if d in m and d > buy_day:
                result[sig] = (d, m[d])
                break
    if not result:
        return None, None, None
    best_sig = min(result, key=lambda s: result[s][0])
    return best_sig, result[best_sig][0], result[best_sig][1]


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
        exits = precompute_exits(df)
        exits["dates"] = dates
        im = {str(pd.Timestamp(ts))[:16].replace(" 00:00", ""): i for i, ts in enumerate(df["datetime"])}
        chan = analyze_chan(df)
        for p in chan["points"]:
            i = im.get(p["date"])
            if i is None or not p["kind"].startswith("buy") or i + 7 >= len(closes):
                continue
            prev = closes[i + 1]
            buy = opens[i + 2]
            if prev <= 0 or buy <= 0 or buy / prev - 1.0 >= 0.098:
                continue
            buy_day = dates[i + 2]
            expire_day = dates[i + 7]
            expire_px = closes[i + 7]
            sig, sig_day, sig_px = pick_exit(exits, i, buy_day)
            events.append(
                {
                    "code": code,
                    "type": p["kind"],
                    "buy_date": buy_day,
                    "buy_px": buy,
                    "sell_date": expire_day,
                    "sell_px": expire_px,
                    "blocked": False,
                    "expire_day": expire_day,
                    "expire_px": expire_px,
                    "chan_day": sig_day if sig == "chan" else None,
                    "chan_px": sig_px if sig == "chan" else None,
                    "atr_day": sig_day if sig == "atr" else None,
                    "atr_px": sig_px if sig == "atr" else None,
                    "div_day": sig_day if sig == "div" else None,
                    "div_px": sig_px if sig == "div" else None,
                    "earliest": sig,
                }
            )
        print(f"{code} done", flush=True)

    log = ExperimentLog(LOG_PATH)
    lines = [
        "# 卖出信号消融实验（买入端固定缠论买点）",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　信号数：{len(events)}",
        "> 卖出信号：expire=到期 / chan=缠论卖点 / atr_top=ATR顶 / divergence=MACD顶背离；",
        "> 组合：100万、持仓上限5/10、仓位10%/20%，含费用与涨跌停约束。",
        "",
        "| 卖出信号 | 持仓/仓位 | 笔数 | 胜率 | 总收益 | 最大回撤 |",
        "|---|---|---|---|---|---|",
    ]
    for signal, day_key, px_key in (
        ("expire", "expire_day", "expire_px"),
        ("chan", "chan_day", "chan_px"),
        ("atr_top", "atr_day", "atr_px"),
        ("divergence", "div_day", "div_px"),
    ):
        evs_round = []
        for e in events:
            d = e.get(day_key)
            if d:
                evs_round.append({**e, "sell_date": d, "sell_px": e[px_key], "blocked": False})
            else:
                evs_round.append(e)
        for mp, cap in ((5, 0.1), (10, 0.2)):
            r = run_portfolio(evs_round, mp, cap, close_map, exit_rule="fixed")
            lines.append(
                f"| {signal} | {mp}/{cap:.0%} | {r['n_trades']} | {r['win_rate'] * 100:.0f}% | {r['total_ret'] * 100:+.1f}% | {r['mdd'] * 100:.1f}% |"
            )
            log.append(
                ExperimentRecord(
                    experiment_id=f"EXIT-{signal.upper()}-{mp}-{int(cap * 100)}",
                    hypothesis=f"卖出信号对比：{signal}（买入端=缠论买点）",
                    unique_change=f"exit_signal={signal}, max_positions={mp}, cap={cap}",
                    expected="不同卖出信号对收益/回撤的影响",
                    dev_result=f"胜率 {r['win_rate'] * 100:.0f}%，总收益 {r['total_ret'] * 100:+.1f}%，最大回撤 {r['mdd'] * 100:.1f}%",
                    val_result="",
                    cost_result=f"笔数 {r['n_trades']}",
                    passed=False,
                    failure_reason="一年窗口/单一样本池，未做样本外与盲测",
                    code_version=subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip() or "dev",
                )
            )
    lines += ["", "## 结论", ""]
    lines.append("- 对比不同卖出信号的收益/回撤：到期>缠论卖点≈ATR顶>顶背离（若数据如此）。")
    lines.append("- 每轮已写入 experiments.csv。")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已生成：{OUT}，实验日志已追加 {len(events) and 8} 条")


if __name__ == "__main__":
    main()
