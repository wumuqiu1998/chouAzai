"""缠论买点组合级成本回测（50 只随机股票）。

在方向/净收益单笔验证（+3.17% 超额）之后，做组合级验证：
- 信号：缠论 B1/B2/B3 买点（日K），右侧确认后 T+2 开盘买入；
- 资金：100 万池，单票仓位 cap × 资金，同时持仓上限 max_positions；
- 约束：涨停开盘买不进跳过；跌停收盘卖不出按收盘估值并标记；
- 费用：佣金 0.0003×2 + 印花税 0.0005 + 滑点 0.0001×2；
- 扫描：max_positions ∈ {5,10}，per_trade_cap ∈ {0.1,0.2}。
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
CAPITAL = 1_000_000.0
COMMISSION = 0.0003
STAMP = 0.0005
SLIPPAGE = 0.0001
LIMIT = 0.098
HOLD = 5
OUT = Path(__file__).resolve().parent / "data" / "chan_buy_portfolio.md"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def build_events(df: pd.DataFrame) -> list[dict]:
    """生成买点事件：{code, buy_date, sell_date, buy_px, sell_px, type, blocked}"""
    opens = df["open"].astype(float).values
    closes = df["close"].astype(float).values
    dates = df["datetime"].dt.strftime("%Y-%m-%d").values
    im = {str(pd.Timestamp(ts))[:16].replace(" 00:00", ""): i for i, ts in enumerate(df["datetime"])}
    out: list[dict] = []
    chan = analyze_chan(df)
    for p in chan["points"]:
        i = im.get(p["date"])
        if i is None or not p["kind"].startswith("buy") or i + 2 + HOLD >= len(closes):
            continue
        prev = closes[i + 1]
        buy = opens[i + 2]
        if prev <= 0 or buy <= 0:
            continue
        if buy / prev - 1.0 >= LIMIT - 1e-6:
            continue  # 涨停开盘买不进
        sell = closes[i + 2 + HOLD]
        blocked = False
        if sell / closes[i + 1 + HOLD] - 1.0 <= -LIMIT + 1e-6:
            blocked = True  # 跌停收盘卖不出，按估值
        out.append(
            {
                "code": p["kind"],
                "type": p["kind"],
                "buy_date": dates[i + 2],
                "sell_date": dates[i + 2 + HOLD],
                "buy_px": buy,
                "sell_px": sell,
                "blocked": blocked,
            }
        )
    return out


def run_portfolio(
    events: list[dict],
    max_positions: int,
    per_trade_cap: float,
    close_map: dict[str, dict[str, float]],
    exit_rule: str = "fixed",
    stop_loss: float = 0.08,
    take_profit: float = 0.08,
    market_ok: dict[str, bool] | None = None,
) -> dict:
    """按日期顺序执行；持仓每日按当日收盘价估值，退出规则可选：
    fixed=到期卖出；stop=跌破-8%止损；take=涨超+8%止盈；both=止损+止盈。
    """
    ev = sorted(events, key=lambda x: (x["buy_date"], {"buy1": 0, "buy2": 1, "buy3": 2}.get(x["type"], 3)))
    by_buy: dict[str, list] = defaultdict(list)
    for e in ev:
        by_buy[e["buy_date"]].append(e)

    cash = CAPITAL
    positions: list[dict] = []  # {sell_date, sell_px, cost, shares, code, type, last_px}
    trades: list[dict] = []
    daily: list[dict] = []
    all_dates = sorted({e["buy_date"] for e in ev} | {e["sell_date"] for e in ev})
    equity = CAPITAL
    last_close_vals: dict[str, float] = {}

    for day in all_dates:
        # 1) 先处理到期卖出与提前退出（止损/止盈）
        remaining: list[dict] = []
        day_closes = close_map.get(day, {})
        for pos in positions:
            exit_now = pos["sell_date"] == day
            exit_px = pos["sell_px"]
            if not exit_now and exit_rule != "fixed":
                px = day_closes.get(pos["code"], pos["last_px"])
                ratio = px / pos["cost"] - 1.0
                if exit_rule in ("stop", "both") and ratio <= -stop_loss:
                    exit_now = True
                    exit_px = px
                elif exit_rule in ("take", "both") and ratio >= take_profit:
                    exit_now = True
                    exit_px = px
            if exit_now:
                sell_px = exit_px
                gross = pos["shares"] * sell_px
                fee = gross * (COMMISSION + STAMP + SLIPPAGE)
                cash += gross - fee
                net = (sell_px / pos["cost"] - 1.0) * pos["amount"]
                trades.append({"date": day, "code": pos["code"], "type": pos["type"], "net": round(net, 2), "blocked": pos.get("blocked", False)})
            else:
                remaining.append(pos)
        positions = remaining

        # 2) 买入当日信号（受持仓上限与现金约束）
        for e in by_buy.get(day, []):
            if market_ok is not None and not market_ok.get(day, True):
                break  # 大盘弱势日不开新仓（市场过滤）
            if len(positions) >= max_positions:
                break
            budget = min(cash, CAPITAL * per_trade_cap)
            if budget < 10000:
                break
            buy_px = e["buy_px"] * (1 + SLIPPAGE)
            shares = int(budget / buy_px / 100) * 100
            if shares <= 0:
                continue
            amount = shares * buy_px
            fee = amount * COMMISSION
            if amount + fee > cash:
                continue
            cash -= amount + fee
            positions.append(
                {
                    "sell_date": e["sell_date"],
                    "sell_px": e["sell_px"] * (1 - SLIPPAGE),
                    "cost": buy_px,
                    "amount": amount,
                    "shares": shares,
                    "code": e["code"],
                    "type": e["type"],
                    "blocked": e["blocked"],
                    "last_px": buy_px,
                }
            )
            trades.append({"date": day, "side": "buy", "code": e["type"], "type": e["type"], "amount": round(amount, 2)})

        # 3) 盯市估值：用当日收盘价（缺失时沿用上次收盘价）
        for p in positions:
            px = day_closes.get(p["code"], p["last_px"])
            p["last_px"] = px
        pos_val = sum(p["shares"] * p["last_px"] for p in positions)
        equity = cash + pos_val
        daily.append({"date": day, "equity": round(equity, 2)})

    closed = [t for t in trades if t.get("side") != "buy"]
    wins = [t for t in closed if t["net"] > 0]
    peak = max(d["equity"] for d in daily) if daily else CAPITAL
    mdd = min(d["equity"] / peak - 1.0 for d in daily) if daily else 0.0
    total_ret = daily[-1]["equity"] / CAPITAL - 1.0 if daily else 0.0
    return {
        "max_positions": max_positions,
        "per_trade_cap": per_trade_cap,
        "total_ret": total_ret,
        "mdd": mdd,
        "final_equity": daily[-1]["equity"] if daily else CAPITAL,
        "n_trades": len(closed),
        "win_rate": len(wins) / len(closed) if closed else 0.0,
        "blocked_sells": sum(1 for t in closed if t.get("blocked")),
        "daily": daily,
        "period_days": len(daily),
    }


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    universe = fetch_universe()
    rng = random.Random(SEED)
    sample = rng.sample(universe, min(N, len(universe)))
    events_all: list[dict] = []
    close_map: dict[str, dict[str, float]] = {}
    used = 0
    # 大盘过滤：上证指数收盘 > MA20（用前一日数据判断，T-1 生效，无未来函数）
    market_ok: dict[str, bool] | None = None
    try:
        idx = astock.index_kline("sh000001", offset=300)
        idf = pd.DataFrame(idx)
        idf["datetime"] = pd.to_datetime(idf["datetime"])
        idf = idf.sort_values("datetime").reset_index(drop=True)
        idf["ma20"] = idf["close"].rolling(20).mean()
        idf["ok"] = (idf["close"].shift(1) > idf["ma20"].shift(1)).fillna(True)
        market_ok = {str(row["datetime"].date()): bool(row["ok"]) for _, row in idf.iterrows()}
        print(f"[info] 大盘过滤已启用：指数 {len(market_ok)} 个交易日", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 大盘过滤不可用：{e}", flush=True)
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
        for _, row in df.iterrows():
            d = str(row["datetime"].date())
            close_map.setdefault(d, {})[code] = float(row["close"])
        evs = build_events(df)
        for e in evs:
            e["code"] = code
        events_all.extend(evs)
        used += 1
        print(f"{code} {s['name']} events={len(evs)}", flush=True)

    lines = [
        "# 缠论买点组合级成本回测（50 只随机）",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　有效股票：{used}　信号总数：{len(events_all)}",
        "> 口径：T+2 开盘买入、持有 5 日收盘卖出；佣金 0.0003×2 + 印花税 0.0005 + 滑点 0.0001×2；",
        "> 涨停开盘买不进跳过、跌停收盘卖不出按估值并标记；资金池 100 万。",
        "",
        "| 退出规则 | 持仓上限 | 单票仓位 | 交易笔数 | 胜率 | 总收益 | 最大回撤 | 期末权益 | 跌停估值笔数 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    results = []
    for rule in ("fixed", "both", "stop", "take", "both+mkt"):
        for mp, cap in ((5, 0.1), (5, 0.2), (10, 0.1), (10, 0.2)):
            r = run_portfolio(
                events_all, mp, cap, close_map,
                exit_rule="both" if rule == "both+mkt" else rule,
                market_ok=market_ok if rule == "both+mkt" else None,
            )
            results.append(r)
            lines.append(
                f"| {rule} | {mp} | {cap:.0%} | {r['n_trades']} | {r['win_rate'] * 100:.0f}% | {r['total_ret'] * 100:+.1f}% | {r['mdd'] * 100:.1f}% | {r['final_equity']:,.0f} | {r['blocked_sells']} |"
            )

    best = max(results, key=lambda x: x["total_ret"])
    lines += ["", "## 结论", ""]
    lines.append(f"- 固定持有 vs 动态退出：对比止损-8%/止盈+8%/两者组合，看回撤与收益变化。")
    lines.append("- 若动态退出显著改善回撤且不伤收益，固定持有口径确实高估/低估了真实可交易性。")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已生成：{OUT}")


if __name__ == "__main__":
    main()
