"""今晚新增策略 vs 之前交易规则（B/S 做T）回测对比。

对比口径（统一复用 t_backtest.run_t_backtest，半仓 50%、收盘强制回补、
佣金双边 + 印花税卖出 + 滑点，逐股票独立）：
- B/S 基线：缠论买卖点做T（之前的交易规则）；
- B/S+三卖预警：把 sell3_warn 也作为卖出信号；
- ATR 顶底做T：新过滤版 ATR 顶=卖、ATR 底=买；
- B/S+回撤8%止盈：缠论买点不变，卖出改为“从买入后最高点回撤 8%”；
- ATR底买+回撤8%卖：买入用 ATR 底，卖出用回撤 8% 止盈；
- B/S+新高缩量卖：缠论 B/S 不变，叠加新高缩量卖出预警。

窗口：最近 20 个交易日（沿用之前做T回测口径）。
"""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import astock  # noqa: E402
from quant_framework.atr import compute_atr  # noqa: E402
from quant_framework.chan import _dt_key, analyze_chan  # noqa: E402
from quant_framework.t_backtest import run_t_backtest  # noqa: E402

CODES = ["000063", "600487", "000636"]
PLAN = [("30分", 2), ("15分", 1)]
DAYS = 20
OFFSET = 300
TRADE_PCT = 0.5
DRAWDOWN = 0.08
OUT = Path(__file__).resolve().parent / "data" / "new_strategy_compare.md"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ALL_NATIVE = ("buy1", "buy2", "buy3", "sell1", "sell2", "sell3")


def idx_map(df: pd.DataFrame) -> dict[str, int]:
    m: dict[str, int] = {}
    for i, ts in enumerate(df["datetime"]):
        m[_dt_key(ts)] = i
    return m


def atr_top_bottom_points(df: pd.DataFrame) -> list[dict]:
    im = idx_map(df)
    pts: list[dict] = []
    for s in compute_atr(df)["signals"]:
        if s["kind"] not in ("top", "bottom"):
            continue
        T = im.get(s["date"])
        if T is None or T < 1:
            continue
        pts.append(
            {
                "kind": "sell_atr_top" if s["kind"] == "top" else "buy_atr_bottom",
                "date": _dt_key(df["datetime"].iloc[T - 1]),
                "price": s["price"],
            }
        )
    return pts


def chan_buy_points(df: pd.DataFrame) -> list[dict]:
    return [p for p in analyze_chan(df)["points"] if p["kind"].startswith("buy")]


def trailing_sells(df: pd.DataFrame, buy_points: list[dict], dd: float = DRAWDOWN, max_look: int = 120) -> list[dict]:
    """从每个买点实际可交易 bar 起跟踪最高价，回撤 dd 后生成卖出点。"""
    im = idx_map(df)
    highs = df["high"].astype(float).values
    lows = df["low"].astype(float).values
    closes = df["close"].astype(float).values
    pts: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for bp in buy_points:
        T = im.get(str(bp["date"]))
        if T is None:
            continue
        exec_start = T + 2  # 点日期 bar T → 确认 T+1 → 执行 T+2 开盘
        if exec_start >= len(df):
            continue
        run_high = highs[exec_start - 1]
        for j in range(exec_start, min(len(df), exec_start + max_look)):
            run_high = max(run_high, highs[j])
            if lows[j] <= run_high * (1.0 - dd):
                key = (_dt_key(df["datetime"].iloc[j - 1]), "sell_trail")
                if key not in seen:
                    seen.add(key)
                    pts.append(
                        {
                            "kind": "sell_trail",
                            "date": _dt_key(df["datetime"].iloc[j - 1]),
                            "price": closes[j],
                        }
                    )
                break
    return pts


def volume_divergence_points(df: pd.DataFrame) -> list[dict]:
    closes = df["close"].astype(float).values
    highs = df["high"].astype(float).values
    vols = df["volume"].astype(float).values
    pts: list[dict] = []
    for T in range(20, len(df)):
        prev_high = highs[T - 20 : T].max()
        if closes[T] >= prev_high and highs[T] >= prev_high:
            v_avg = vols[T - 5 : T].mean()
            if v_avg > 0 and vols[T] <= v_avg * 0.85:
                pts.append(
                    {
                        "kind": "sell_vol_div",
                        "date": _dt_key(df["datetime"].iloc[T - 1]),
                        "price": closes[T],
                    }
                )
    return pts


def build_variants(df: pd.DataFrame) -> list[tuple[str, dict]]:
    atr = atr_top_bottom_points(df)
    atr_buys = [p for p in atr if p["kind"] == "buy_atr_bottom"]
    cbuys = chan_buy_points(df)
    return [
        ("B/S基线(之前规则)", {}),
        ("B/S+三卖预警", {"include_warns": True}),
        ("ATR顶底做T", {"skip_native_kinds": ALL_NATIVE, "extra_points": atr}),
        ("B/S+回撤8%止盈", {"skip_native_kinds": ("sell1", "sell2", "sell3"), "extra_points": trailing_sells(df, cbuys)}),
        ("ATR底买+回撤8%卖", {"skip_native_kinds": ALL_NATIVE, "extra_points": atr_buys + trailing_sells(df, atr_buys)}),
        ("B/S+新高缩量卖", {"extra_points": volume_divergence_points(df)}),
    ]


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [
        "# 新增策略 vs 之前交易规则（B/S 做T）回测对比",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　样本：{', '.join(CODES)}　窗口：最近 {DAYS} 个交易日",
        "> 口径：半仓 50%、信号后下一根开盘 ±滑点、收盘强制回补、佣金双边+印花税卖出。",
        "",
        "| 代码 | 周期 | 策略 | 配对 | 胜率 | T净收益 | 费用 | 正日/总日 | 日均T收益 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for code in CODES:
        for cat_name, cat in PLAN:
            try:
                rows = astock.kline(code, category=cat, offset=OFFSET)
                df = pd.DataFrame(rows)
                df["datetime"] = pd.to_datetime(df["datetime"])
            except Exception as e:  # noqa: BLE001
                lines.append(f"| {code} | {cat_name} | 数据失败 | {e} |")
                continue
            avail = len(pd.Series(df["datetime"].dt.date).unique())
            days = min(DAYS, avail)
            base_price = float(df["close"].iloc[0])
            for label, kw in build_variants(df):
                try:
                    res = run_t_backtest(
                        base_price=base_price,
                        base_shares=1000,
                        days=days,
                        category=cat,
                        offset=OFFSET,
                        df=df,
                        trade_pct=TRADE_PCT,
                        stamp_duty=0.0005,
                        **kw,
                    )
                    s = res["summary"]
                    lines.append(
                        "| {code} | {cat} | {label} | {pairs} | {win:.1%} | {pnl:+.0f} | {fees:.0f} | {pos}/{days} | {perday:+.0f} |".format(
                            code=code,
                            cat=cat_name,
                            label=label,
                            pairs=s["total_pairs"],
                            win=s["win_rate"],
                            pnl=s["t_pnl"],
                            fees=s["total_fees"],
                            pos=s["positive_days"],
                            days=days,
                            perday=s["t_pnl_per_day"],
                        )
                    )
                except Exception as e:  # noqa: BLE001
                    lines.append(f"| {code} | {cat_name} | {label} | 回测失败: {e} |")
                OUT.write_text("\n".join(lines), encoding="utf-8")
            print(f"{code} {cat_name} done", flush=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已生成：{OUT}")


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"finished in {time.time() - t0:.0f}s", flush=True)
