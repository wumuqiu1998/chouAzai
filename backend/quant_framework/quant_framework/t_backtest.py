"""缠论日内做T回测（简化口径，研究用）。

规则：
- 持有底仓 base_shares（成本 base_price），A股 T+1：只能卖底仓、当日买回，不卖当日新买；
- 信号：对截至当前 bar 的历史做缠论分析（因果、无未来函数），当天出现的 S 点触发卖出、B 点触发买回；
- 成交：信号后一根 K 线开盘价 ± 滑点；单次量 = 底仓 × trade_pct（整手）；
- 当日收盘强制买回剩余卖出部分，保持底仓不变；
- 费用：佣金（双边）+ 印花税（卖出）+ 滑点。

输出：日级 T 净收益、配对盈亏、费用与汇总。底仓浮盈仅作参考，不计入 T 收益。
"""

from __future__ import annotations

import pandas as pd

from quant_framework.chan import _dt_key, analyze_chan


def run_t_backtest(
    code: str = "000063",
    base_price: float = 43.0,
    base_shares: int = 1000,
    days: int = 30,
    category: int = 11,
    offset: int = 500,
    trade_pct: float = 0.2,
    commission: float = 0.0003,
    stamp_duty: float = 0.0005,
    slippage: float = 0.0001,
    lot: int = 100,
    min_warmup: int = 60,
    df: pd.DataFrame | None = None,
) -> dict:
    if df is None:
        import astock

        rows = astock.kline(code, category=category, offset=offset)
        if not rows:
            raise ValueError("K 线数据为空")
        df = pd.DataFrame(rows)
        df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)

    all_dates = list(pd.Series(df["datetime"].dt.date).unique())
    if len(all_dates) < days:
        raise ValueError(f"数据不足：仅 {len(all_dates)} 个交易日，需要 {days} 天")
    backtest_dates = all_dates[-days:]
    backtest_set = set(backtest_dates)
    trade_size = max(lot, (base_shares * trade_pct) // lot * lot)
    if trade_size > base_shares:
        trade_size = (base_shares // lot) * lot

    opens = df["open"].values
    closes = df["close"].values
    dts = df["datetime"].values
    last_idx_by_day = df.groupby(df["datetime"].dt.date).apply(lambda g: g.index[-1]).to_dict()

    # 1) 逐 bar 因果生成信号（只用截至当前 bar 的数据）
    signals: list[dict] = []
    for i in range(min_warmup, len(df)):
        cur = pd.Timestamp(dts[i])
        if cur.date() not in backtest_set:
            continue
        res = analyze_chan(df.iloc[: i + 1])
        # 分型/笔需要下一根 K 线确认：点所在 bar = 上一根 bar 时，说明刚被当前 bar 确认
        prev_key = _dt_key(dts[i - 1])
        for p in res["points"]:
            if p["date"] != prev_key:
                continue
            if i + 1 >= len(df) or pd.Timestamp(dts[i + 1]).date() != cur.date():
                continue  # 下一根跨日：做T不隔夜，跳过
            signals.append({"exec_i": i + 1, "day": cur.date(), "kind": p["kind"], "price": p["price"]})

    # 2) 逐日执行
    available = base_shares
    t_cash = 0.0
    fees_total = 0.0
    trades_log: list[dict] = []
    daily: list[dict] = []

    for day in backtest_dates:
        day_start = t_cash
        pending_sells: list[dict] = []
        sell_count = 0
        buy_count = 0
        day_signals = [s for s in signals if s["day"] == day]
        for s in day_signals:
            i = s["exec_i"]
            exec_price = float(opens[i])
            if s["kind"].startswith("sell") and available >= trade_size:
                px = exec_price * (1 - slippage)
                amount = px * trade_size
                fee = amount * (commission + stamp_duty)
                t_cash += amount - fee
                fees_total += fee
                available -= trade_size
                sell_count += 1
                pending_sells.append({"price": px, "shares": trade_size})
                trades_log.append({"date": day, "side": "sell", "kind": s["kind"], "price": round(px, 3), "shares": trade_size})
            elif not s["kind"].startswith("sell") and pending_sells:
                px = exec_price * (1 + slippage)
                amount = px * trade_size
                fee = amount * commission
                t_cash -= amount + fee
                fees_total += fee
                available += trade_size
                buy_count += 1
                ps = pending_sells.pop(0)
                gross = (ps["price"] - px) * trade_size
                trades_log.append(
                    {
                        "date": day,
                        "side": "buy",
                        "kind": s["kind"],
                        "price": round(px, 3),
                        "shares": trade_size,
                        "paired_pnl": round(gross, 2),
                    }
                )

        # 收盘强制买回剩余，保持底仓
        if pending_sells:
            last_idx = last_idx_by_day[day]
            px = float(closes[last_idx]) * (1 + slippage)
            rem = sum(p["shares"] for p in pending_sells)
            amount = px * rem
            fee = amount * commission
            t_cash -= amount + fee
            fees_total += fee
            available += rem
            for ps in pending_sells:
                gross = (ps["price"] - px) * ps["shares"]
                trades_log.append(
                    {
                        "date": day,
                        "side": "force_buy",
                        "kind": "restore",
                        "price": round(px, 3),
                        "shares": ps["shares"],
                        "paired_pnl": round(gross, 2),
                    }
                )

        daily.append(
            {
                "date": str(day),
                "t_pnl": round(t_cash - day_start, 2),
                "sells": sell_count,
                "buys": buy_count,
                "signals": len(day_signals),
            }
        )

    pairs = [t for t in trades_log if "paired_pnl" in t]
    wins = [t for t in pairs if t["paired_pnl"] > 0]
    t_pnl = sum(d["t_pnl"] for d in daily)
    last_close = float(closes[-1])
    return {
        "config": {
            "code": code,
            "base_price": base_price,
            "base_shares": base_shares,
            "days": days,
            "category": category,
            "trade_size": trade_size,
            "commission": commission,
            "stamp_duty": stamp_duty,
            "slippage": slippage,
        },
        "period": {"start": str(backtest_dates[0]), "end": str(backtest_dates[-1]), "last_close": last_close},
        "daily": daily,
        "summary": {
            "total_pairs": len(pairs),
            "win_pairs": len(wins),
            "win_rate": round(len(wins) / len(pairs), 4) if pairs else 0.0,
            "t_pnl": round(t_pnl, 2),
            "total_fees": round(fees_total, 2),
            "positive_days": sum(1 for d in daily if d["t_pnl"] > 0),
            "base_mtm": round(base_shares * (last_close - base_price), 2),
            "t_pnl_per_day": round(t_pnl / len(daily), 2),
        },
        "trades": trades_log,
    }
