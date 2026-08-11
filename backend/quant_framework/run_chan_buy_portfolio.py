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
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import astock  # noqa: E402
from quant_framework.chan import analyze_chan_locked  # noqa: E402
from run_blind_test import fetch_universe  # noqa: E402
import requests  # noqa: E402

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


def build_events(df: pd.DataFrame, market_ok: dict[str, bool] | None = None) -> list[dict]:
    """生成买点事件（含缠论卖点离场信息）。

    chan_sell_day/chan_sell_px：持有窗口内第一个 S1/S2/S3 的离场执行日
    （S 点点日期 j → j+2 开盘卖出），无则 None（到期卖出）。
    combo_sell_day/combo_sell_px/combo_reason：组合离场（缠论卖点/止损/
    止盈/趋势破坏/到期，取最早触发者）。
    """
    opens = df["open"].astype(float).values
    closes = df["close"].astype(float).values
    dates = df["datetime"].dt.strftime("%Y-%m-%d").values
    im = {str(pd.Timestamp(ts))[:16].replace(" 00:00", ""): i for i, ts in enumerate(df["datetime"])}
    ma20 = pd.Series(closes).rolling(20).mean().values
    out: list[dict] = []
    chan = analyze_chan_locked(df)
    sell_exec: dict[str, float] = {}
    for p in chan["points"]:
        if p["kind"].startswith("sell") and not p["kind"].endswith("_warn"):
            j = im.get(p["date"])
            if j is not None:
                k = max(j + 2, p.get("known_at", j) + 1)
                if k < len(closes):
                    sell_exec[dates[k]] = opens[k]
    for p in chan["points"]:
        j = im.get(p["date"])
        if j is None or not p["kind"].startswith("buy"):
            continue
        b = max(j + 2, p.get("known_at", j) + 1)
        if b + HOLD >= len(closes):
            continue
        prev = closes[b - 1]
        buy = opens[b]
        if prev <= 0 or buy <= 0:
            continue
        if buy / prev - 1.0 >= LIMIT - 1e-6:
            continue  # 涨停开盘买不进
        sell = closes[b + HOLD]
        blocked = False
        if sell / closes[b + HOLD - 1] - 1.0 <= -LIMIT + 1e-6:
            blocked = True  # 跌停收盘卖不出，按估值
        chan_sell_day = None
        chan_sell_px = None
        for k in range(b + 1, min(b + HOLD, len(dates))):
            d = dates[k]
            if d in sell_exec and d > dates[b]:
                chan_sell_day = d
                chan_sell_px = sell_exec[d]
                break
        # 组合离场：取最早触发（同日按 stop > trend > chan > take > expire）
        pri = {"stop": 0, "trend": 1, "chan": 2, "take": 3, "expire": 4}
        cands: list[tuple] = []
        if chan_sell_day:
            cands.append((chan_sell_day, chan_sell_px, "chan"))
        for k in range(b + 2, min(b + HOLD + 1, len(dates))):
            d = dates[k]
            ratio = closes[k] / buy - 1.0
            if ratio <= -0.08:
                cands.append((d, closes[k], "stop"))
                break
            if ratio >= 0.08:
                cands.append((d, closes[k], "take"))
                break
            if market_ok is not None and not market_ok.get(d, True) and closes[k] < ma20[k]:
                cands.append((d, closes[k], "trend"))
                break
        cands.append((dates[b + HOLD], sell, "expire"))
        best = min(cands, key=lambda x: (x[0], pri[x[2]]))
        out.append(
            {
                "code": p["kind"],
                "type": p["kind"],
                "buy_date": dates[b],
                "sell_date": dates[b + HOLD],
                "buy_px": buy,
                "sell_px": sell,
                "blocked": blocked,
                "chan_sell_day": chan_sell_day,
                "chan_sell_px": chan_sell_px,
                "combo_sell_day": best[0],
                "combo_sell_px": best[1],
                "combo_reason": best[2],
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
                trades.append({"date": day, "code": pos["code"], "type": pos["type"], "net": round(net, 2), "ret": round(sell_px / pos["cost"] - 1.0, 4), "blocked": pos.get("blocked", False)})
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
            if exit_rule in ("combo", "combo+mkt") and e.get("combo_sell_day"):
                positions.append(
                    {
                        "sell_date": e["combo_sell_day"],
                        "sell_px": e["combo_sell_px"] * (1 - SLIPPAGE),
                        "cost": buy_px,
                        "amount": amount,
                        "shares": shares,
                        "code": e["code"],
                        "type": e["type"],
                        "blocked": False,
                        "last_px": buy_px,
                        "reason": e.get("combo_reason"),
                    }
                )
            elif exit_rule in ("chan", "chan+mkt") and e.get("chan_sell_day"):
                positions.append(
                    {
                        "sell_date": e["chan_sell_day"],
                        "sell_px": e["chan_sell_px"] * (1 - SLIPPAGE),
                        "cost": buy_px,
                        "amount": amount,
                        "shares": shares,
                        "code": e["code"],
                        "type": e["type"],
                        "blocked": False,
                        "last_px": buy_px,
                    }
                )
            else:
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
        "trades": trades,
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
        idf = fetch_sina_kline("000001", 300, prefix="sh000001")
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
        df = fetch_sina_kline(code, 260)
        if df is None:
            continue
        if len(df) < 250:
            continue
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        for _, row in df.iterrows():
            d = str(row["datetime"].date())
            close_map.setdefault(d, {})[code] = float(row["close"])
        evs = build_events(df, market_ok)
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
    for rule in ("fixed", "both", "chan", "combo", "combo+mkt", "both+mkt"):
        for mp, cap in ((5, 0.1), (5, 0.2), (10, 0.1), (10, 0.2)):
            r = run_portfolio(
                events_all, mp, cap, close_map,
                exit_rule="both" if rule == "both+mkt" else ("chan" if rule == "chan+mkt" else ("combo" if rule == "combo+mkt" else rule)),
                market_ok=market_ok if rule in ("both+mkt", "chan+mkt", "combo+mkt") else None,
            )
            results.append(r)
            lines.append(
                f"| {rule} | {mp} | {cap:.0%} | {r['n_trades']} | {r['win_rate'] * 100:.0f}% | {r['total_ret'] * 100:+.1f}% | {r['mdd'] * 100:.1f}% | {r['final_equity']:,.0f} | {r['blocked_sells']} |"
            )

    best = max(results, key=lambda x: x["total_ret"])
    lines += ["", "## 结论", ""]
    lines.append("- 对比：固定持有 / 止损止盈 / 仅缠论卖点 / 组合离场（卖点+止损+止盈+趋势破坏+到期）/ 组合离场+大盘过滤。")
    lines.append("- 组合离场若在收益接近时显著降低回撤，说明卖出端组合策略有效。")
    lines += ["", "## 组合离场原因分布（事件预计算）", "", "| 离场原因 | 事件数 | 占比 |", "|---|---|---|"]
    from collections import Counter
    reasons = Counter(e.get("combo_reason", "expire") for e in events_all)
    for k in ("stop", "trend", "chan", "take", "expire"):
        n = reasons.get(k, 0)
        lines.append(f"| {k} | {n} | {n / max(1, len(events_all)) * 100:.0f}% |")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已生成：{OUT}")


if __name__ == "__main__":
    main()
