"""固定 combo_top5 的样本外回测 + 大盘 MA 周期扫描。

样本外 A：全新随机 50 只（seed=20260811，组合从未见过）；
样本外 B：同一批股票但更早时段（新浪日K取前 260 根，约 2023 年中~2024 年中）；
大盘扫描：原池最近一年，combo_top5 + 大盘过滤，MA 周期 10/20/30。

combo_top5 = divergence + overheat + warn + trail12 + sweep（谁先触发谁离场，
120 日强平），与样本内完全一致，参数/组成不再调整。
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

from quant_framework.chan import analyze_chan  # noqa: E402
from run_blind_test import fetch_universe  # noqa: E402
from run_chan_buy_portfolio import fetch_sina_kline, run_portfolio  # noqa: E402
from run_exit_signals_all import MAX_HOLD, build_signal_maps, first_exit, trailing_exit  # noqa: E402

SEED_OOS = 20260811
N = 50
COMBO = ("divergence", "overheat", "warn", "trail12", "sweep")
OUT = Path(__file__).resolve().parent / "data" / "oos_combo.md"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def build_events_from_df(df: pd.DataFrame) -> list[dict]:
    opens = df["open"].astype(float).values
    closes = df["close"].astype(float).values
    dates = df["datetime"].dt.strftime("%Y-%m-%d").values
    im = {str(pd.Timestamp(ts))[:16].replace(" 00:00", ""): i for i, ts in enumerate(df["datetime"])}
    maps = build_signal_maps(df)
    events: list[dict] = []
    for p in analyze_chan(df)["points"]:
        i = im.get(p["date"])
        if i is None or not p["kind"].startswith("buy") or i + 7 >= len(closes):
            continue
        prev = closes[i + 1]
        buy = opens[i + 2]
        if prev <= 0 or buy <= 0 or buy / prev - 1.0 >= 0.098:
            continue
        exits: dict[str, tuple] = {}
        for sig in ("divergence", "overheat", "warn", "sweep"):
            ex = first_exit(maps[sig], dates, i)
            if ex:
                exits[sig] = ex
        for pct, key in ((0.12, "trail12"),):
            ex = trailing_exit(closes, dates, i, pct)
            if ex:
                exits[key] = ex
        fallback_k = min(i + 2 + MAX_HOLD, len(closes) - 1)
        events.append(
            {
                "code": p["kind"],
                "type": p["kind"],
                "buy_date": dates[i + 2],
                "buy_px": buy,
                "blocked": False,
                "exits": exits,
                "fallback": (dates[fallback_k], closes[fallback_k]),
            }
        )
    return events


def run_combo(events: list[dict], close_map: dict, mp: int, cap: float, market_ok=None) -> dict:
    evs_round = []
    for e in events:
        cands = [(e["exits"][s][0], e["exits"][s][1]) for s in COMBO if s in e["exits"]]
        ex = min(cands, key=lambda x: x[0]) if cands else e["fallback"]
        evs_round.append({**e, "sell_date": ex[0], "sell_px": ex[1]})
    return run_portfolio(evs_round, mp, cap, close_map, exit_rule="fixed", market_ok=market_ok)


def market_map(n: int = 300) -> dict[str, bool] | None:
    try:
        idf = fetch_sina_kline("000001", n, prefix="sh000001")
        idf["datetime"] = pd.to_datetime(idf["datetime"])
        idf = idf.sort_values("datetime").reset_index(drop=True)
        out = {}
        for ma in (10, 20, 30):
            idf[f"ma{ma}"] = idf["close"].rolling(ma).mean()
            idf[f"ok{ma}"] = (idf["close"].shift(1) > idf[f"ma{ma}"].shift(1)).fillna(True)
            out[ma] = {str(row["datetime"].date()): bool(row[f"ok{ma}"]) for _, row in idf.iterrows()}
        return out
    except Exception as e:  # noqa: BLE001
        print("warn 指数", e)
        return None


def collect(sample: list[dict], df: pd.DataFrame | None, code: str, close_map: dict) -> list[dict]:
    if df is None or len(df) < 200:
        return []
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)
    for _, row in df.iterrows():
        d = str(row["datetime"].date())
        close_map.setdefault(d, {})[code] = float(row["close"])
    evs = build_events_from_df(df)
    for e in evs:
        e["code"] = code
    return evs


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    universe = fetch_universe()
    lines = [
        "# 固定 combo_top5 样本外回测 + 大盘 MA 扫描",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　combo=divergence+overheat+warn+trail12+sweep",
        "",
        "## 样本内（原 50 只，最近一年，参考）",
        "",
        "| 池 | 时间 | 持仓/仓位 | 单笔 | 胜率 | 总收益 | 回撤 |",
        "|---|---|---|---|---|---|---|",
    ]

    # 样本外 A：全新 50 只
    rng = random.Random(SEED_OOS)
    sample_a = rng.sample(universe, min(N, len(universe)))
    close_map: dict[str, dict[str, float]] = {}
    events_all: list[dict] = []
    for s in sample_a:
        df = fetch_sina_kline(s["code"], 260)
        events_all.extend(collect(sample_a, df, s["code"], close_map))
    r = run_combo(events_all, close_map, 10, 0.2)
    lines.append(f"| 新50只 | 最近一年 | 10/20% | +{np.mean([t['ret'] for t in r['trades'] if t.get('ret') is not None]) * 100:.2f}% | {r['win_rate'] * 100:.0f}% | {r['total_ret'] * 100:+.1f}% | {r['mdd'] * 100:.1f}% |")

    # 样本外 B：原池更早时段（新浪取 700 根，用前 260 根）
    rng2 = random.Random(20260810)
    sample_b = rng2.sample(universe, min(N, len(universe)))
    close_map2: dict[str, dict[str, float]] = {}
    events_early: list[dict] = []
    for s in sample_b:
        df = fetch_sina_kline(s["code"], 700)
        if df is None or len(df) < 520:
            continue
        df = df.sort_values("datetime").reset_index(drop=True).iloc[:260].reset_index(drop=True)
        events_early.extend(collect(sample_b, df, s["code"], close_map2))
    r2 = run_combo(events_early, close_map2, 10, 0.2)
    lines.append(f"| 原50只 | 更早一年 | 10/20% | +{np.mean([t['ret'] for t in r2['trades'] if t.get('ret') is not None]) * 100:.2f}% | {r2['win_rate'] * 100:.0f}% | {r2['total_ret'] * 100:+.1f}% | {r2['mdd'] * 100:.1f}% |")

    # 大盘 MA 周期扫描（原池最近一年）
    rng3 = random.Random(20260810)
    sample_c = rng3.sample(universe, min(N, len(universe)))
    close_map3: dict[str, dict[str, float]] = {}
    events_cur: list[dict] = []
    for s in sample_c:
        df = fetch_sina_kline(s["code"], 260)
        events_cur.extend(collect(sample_c, df, s["code"], close_map3))
    maps = market_map()
    lines += ["", "## 大盘 MA 周期扫描（原池最近一年，combo+mkt）", "", "| MA周期 | 持仓/仓位 | 总收益 | 回撤 |", "|---|---|---|---|"]
    if maps:
        for ma in (10, 20, 30):
            r = run_combo(events_cur, close_map3, 10, 0.2, market_ok=maps[ma])
            lines.append(f"| MA{ma} | 10/20% | {r['total_ret'] * 100:+.1f}% | {r['mdd'] * 100:.1f}% |")
    lines += ["", "## 结论", ""]
    lines.append("- 样本外收益/胜率若接近样本内（+64.5%/-39.4%），说明组合可外推；大幅缩水则选择偏差坐实。")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已生成：{OUT}")


if __name__ == "__main__":
    main()
