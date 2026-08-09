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
    regime: dict | None = None,
    df: pd.DataFrame | None = None,
    extra_points: list[dict] | None = None,
    include_warns: bool = False,
    skip_native_kinds: tuple[str, ...] = (),
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
        all_pts = [p for p in res["points"] if p["kind"] not in skip_native_kinds]
        if extra_points:
            all_pts += [ep for ep in extra_points if ep.get("date") == prev_key]
        for p in all_pts:
            if p["date"] != prev_key:
                continue
            if p["kind"].endswith("_warn") and not include_warns:
                continue  # 三卖/中枢破坏预警只是提示，不直接作为做T交易信号
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
        pending_buys: list[dict] = []
        sell_count = 0
        buy_count = 0
        state = (regime or {}).get(day, "range")
        day_signals = [s for s in signals if s["day"] == day]
        for s in day_signals:
            i = s["exec_i"]
            exec_price = float(opens[i])
            if state == "up":
                # 板块上升：顺趋势做多T（B点买入 → S点卖出；当日新买部分当日平，简化口径同中枢long腿）
                if not s["kind"].startswith("sell"):
                    px = exec_price * (1 + slippage)
                    amount = px * trade_size
                    fee = amount * commission
                    t_cash -= amount + fee
                    fees_total += fee
                    pending_buys.append({"price": px, "shares": trade_size})
                    buy_count += 1
                    trades_log.append({"date": day, "side": "buy", "kind": s["kind"], "price": round(px, 3), "shares": trade_size})
                elif s["kind"].startswith("sell") and pending_buys:
                    px = exec_price * (1 - slippage)
                    amount = px * trade_size
                    fee = amount * (commission + stamp_duty)
                    t_cash += amount - fee
                    fees_total += fee
                    pb = pending_buys.pop(0)
                    gross = (px - pb["price"]) * trade_size
                    sell_count += 1
                    trades_log.append(
                        {
                            "date": day,
                            "side": "sell",
                            "kind": s["kind"],
                            "price": round(px, 3),
                            "shares": trade_size,
                            "paired_pnl": round(gross, 2),
                        }
                    )
            elif s["kind"].startswith("sell") and available >= trade_size:
                # 板块下跌/震荡：原做空T（S点卖底仓 → B点买回）
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

        # 收盘强制回补，保持底仓（up 状态强制平掉当日新买部分）
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
        elif pending_buys:
            last_idx = last_idx_by_day[day]
            px = float(closes[last_idx]) * (1 - slippage)
            rem = sum(p["shares"] for p in pending_buys)
            amount = px * rem
            fee = amount * (commission + stamp_duty)
            t_cash += amount - fee
            fees_total += fee
            for pb in pending_buys:
                gross = (px - pb["price"]) * pb["shares"]
                trades_log.append(
                    {
                        "date": day,
                        "side": "force_sell",
                        "kind": "restore",
                        "price": round(px, 3),
                        "shares": pb["shares"],
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
                "regime": state,
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
            "regime": "up/down/range 状态切换" if regime else "无状态切换",
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


def run_band_t_backtest(
    code: str = "000063",
    base_price: float = 43.0,
    base_shares: int = 1000,
    days: int = 20,
    category: int = 11,
    offset: int = 800,
    trade_pct: float = 0.2,
    commission: float = 0.0003,
    stamp_duty: float = 0.0005,
    slippage: float = 0.0001,
    lot: int = 100,
    min_warmup: int = 60,
    use_beichi_filter: bool = False,
    beichi_window: int = 24,
    vp_shrink_ratio: float = 0.0,
    vp_surge_ratio: float = 0.0,
    vol_window: int = 20,
    trend_window: int = 0,
    trend_period: int = 20,
    daily_df: pd.DataFrame | None = None,
    regime: dict | None = None,
    df: pd.DataFrame | None = None,
) -> dict:
    """中枢上下轨做T：ZD（下沿）低吸 / ZG（上沿）高抛。

    因果实现：只使用截至当前 bar 的数据确认中枢与背驰；触发后下一根开盘执行；
    当日先买后卖/先卖后买均可（T+1 只卖底仓），收盘强制回补保持底仓。
    use_beichi_filter=True 时，只在最近确认过同向缠论买卖点后才开新仓。
    """
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
    lows = df["low"].values
    highs = df["high"].values
    dts = df["datetime"].values
    vols = df["volume"].values
    avg_vol = df["volume"].rolling(vol_window, min_periods=vol_window).mean().values
    last_idx_by_day = df.groupby(df["datetime"].dt.date).apply(lambda g: g.index[-1]).to_dict()

    # 大级别方向：日线收盘 vs MA(trend_period)，用前一日收盘判定当日方向（无未来函数）
    direction: dict = {}
    if trend_window > 0:
        if daily_df is not None:
            ddf = daily_df.copy()
            ddf["datetime"] = pd.to_datetime(ddf["datetime"])
            dclose = ddf.groupby(ddf["datetime"].dt.date)["close"].last()
        else:
            dclose = df.groupby(df["datetime"].dt.date)["close"].last()
        dma = dclose.rolling(trend_period, min_periods=trend_period).mean()
        prev_close = dclose.shift(1)
        prev_ma = dma.shift(1)
        for day in backtest_dates:
            if day in prev_close.index and pd.notna(prev_close[day]) and pd.notna(prev_ma[day]):
                direction[day] = "up" if prev_close[day] > prev_ma[day] else "down"
            else:
                direction[day] = "neutral"

    # 板块/概念状态优先：up→禁空、down→禁多、range→双向
    if regime:
        for day in backtest_dates:
            r = regime.get(day, "neutral")
            direction[day] = "up" if r == "up" else ("down" if r == "down" else "neutral")

    # 1) 逐 bar 因果扫描：确认中枢与背驰点，生成上下轨触发
    triggers: list[dict] = []
    last_buy_pos: int | None = None
    last_sell_pos: int | None = None
    for i in range(min_warmup, len(df) - 1):
        cur = pd.Timestamp(dts[i])
        exec_day = pd.Timestamp(dts[i + 1]).date()
        if cur.date() != exec_day:
            continue
        if cur.date() not in backtest_set:
            continue
        res = analyze_chan(df.iloc[: i + 1])
        # 记录刚被确认的背驰买卖点（点所在 bar = 上一根 bar）
        prev_key = _dt_key(dts[i - 1])
        for p in res["points"]:
            if p["date"] == prev_key:
                if p["kind"].endswith("_warn"):
                    continue
                if p["kind"].startswith("buy"):
                    last_buy_pos = i - 1
                elif p["kind"].startswith("sell"):
                    last_sell_pos = i - 1
        # 取已完成的最近中枢（end_pos <= i-1）
        completed = [z for z in res["zhongshu"] if z["end_pos"] <= i - 1]
        if not completed:
            continue
        z = max(completed, key=lambda x: x["end_pos"])
        vol_ok_buy = vp_shrink_ratio <= 0 or (vols[i] <= avg_vol[i] * vp_shrink_ratio)
        vol_ok_sell = vp_surge_ratio <= 0 or (vols[i] >= avg_vol[i] * vp_surge_ratio)
        if lows[i] <= z["zd"] and vol_ok_buy:
            triggers.append({"exec_i": i + 1, "day": exec_day, "side": "buy", "ref_zd": z["zd"], "ref_zg": z["zg"]})
        elif highs[i] >= z["zg"] and vol_ok_sell:
            triggers.append({"exec_i": i + 1, "day": exec_day, "side": "sell", "ref_zd": z["zd"], "ref_zg": z["zg"]})

    # 2) 逐日执行：开/平仓配对，收盘强制回补
    t_cash = 0.0
    fees_total = 0.0
    trades_log: list[dict] = []
    daily: list[dict] = []

    for day in backtest_dates:
        day_start = t_cash
        legs: list[dict] = []  # {"dir": long/short, "price": 开仓价, "size": 手数股数}
        day_triggers = [t for t in triggers if t["day"] == day]
        for t in day_triggers:
            i = t["exec_i"]
            exec_price = float(opens[i])
            if t["side"] == "buy":
                # 关闭空头腿（先卖后买场景）
                shorts = [lg for lg in legs if lg["dir"] == "short"]
                if shorts:
                    lg = shorts.pop(0)
                    legs.remove(lg)
                    px = exec_price * (1 + slippage)
                    amount = px * trade_size
                    fee = amount * commission
                    t_cash -= amount + fee
                    fees_total += fee
                    gross = (lg["price"] - px) * trade_size
                    trades_log.append({"date": day, "side": "buy", "kind": "close_short", "price": round(px, 3), "shares": trade_size, "paired_pnl": round(gross, 2)})
                elif not any(lg["dir"] == "long" for lg in legs) and direction.get(day, "neutral") != "down":
                    # 开多（先买后卖场景）：背驰过滤
                    if use_beichi_filter and (last_buy_pos is None or i - last_buy_pos > beichi_window):
                        continue
                    px = exec_price * (1 + slippage)
                    amount = px * trade_size
                    fee = amount * commission
                    t_cash -= amount + fee
                    fees_total += fee
                    legs.append({"dir": "long", "price": px, "size": trade_size})
                    trades_log.append({"date": day, "side": "buy", "kind": "open_long", "price": round(px, 3), "shares": trade_size})
            else:
                longs = [lg for lg in legs if lg["dir"] == "long"]
                if longs:
                    lg = longs.pop(0)
                    legs.remove(lg)
                    px = exec_price * (1 - slippage)
                    amount = px * trade_size
                    fee = amount * (commission + stamp_duty)
                    t_cash += amount - fee
                    fees_total += fee
                    gross = (px - lg["price"]) * trade_size
                    trades_log.append({"date": day, "side": "sell", "kind": "close_long", "price": round(px, 3), "shares": trade_size, "paired_pnl": round(gross, 2)})
                elif not any(lg["dir"] == "short" for lg in legs) and direction.get(day, "neutral") != "up":
                    if use_beichi_filter and (last_sell_pos is None or i - last_sell_pos > beichi_window):
                        continue
                    px = exec_price * (1 - slippage)
                    amount = px * trade_size
                    fee = amount * (commission + stamp_duty)
                    t_cash += amount - fee
                    fees_total += fee
                    legs.append({"dir": "short", "price": px, "size": trade_size})
                    trades_log.append({"date": day, "side": "sell", "kind": "open_short", "price": round(px, 3), "shares": trade_size})

        # 收盘强制回补，保持底仓
        if legs:
            last_idx = last_idx_by_day[day]
            px = float(closes[last_idx])
            for lg in legs:
                if lg["dir"] == "long":
                    sell_px = px * (1 - slippage)
                    amount = sell_px * lg["size"]
                    fee = amount * (commission + stamp_duty)
                    t_cash += amount - fee
                    fees_total += fee
                    gross = (sell_px - lg["price"]) * lg["size"]
                    trades_log.append({"date": day, "side": "sell", "kind": "force_close_long", "price": round(sell_px, 3), "shares": lg["size"], "paired_pnl": round(gross, 2)})
                else:
                    buy_px = px * (1 + slippage)
                    amount = buy_px * lg["size"]
                    fee = amount * commission
                    t_cash -= amount + fee
                    fees_total += fee
                    gross = (lg["price"] - buy_px) * lg["size"]
                    trades_log.append({"date": day, "side": "buy", "kind": "force_close_short", "price": round(buy_px, 3), "shares": lg["size"], "paired_pnl": round(gross, 2)})

        daily.append(
            {
                "date": str(day),
                "t_pnl": round(t_cash - day_start, 2),
                "triggers": len(day_triggers),
                "trend": direction.get(day, "neutral"),
                "regime": (regime or {}).get(day, "neutral"),
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
            "use_beichi_filter": use_beichi_filter,
            "beichi_window": beichi_window,
            "vp_shrink_ratio": vp_shrink_ratio,
            "vp_surge_ratio": vp_surge_ratio,
            "vol_window": vol_window,
            "trend_window": trend_window,
            "trend_period": trend_period,
            "regime": "板块状态切换" if regime else "无状态切换",
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
