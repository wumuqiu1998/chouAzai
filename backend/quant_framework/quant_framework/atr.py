"""ATR 通道模块：跨周期超涨/超跌识别 + 潜在顶底信号。

规则（无未来函数，信号只用截至当前 K 线收盘的数据计算）：
- TR   = max(high-low, |high-prev_close|, |low-prev_close|)
- ATR  = TR 的 Wilder 平滑（period，默认 14）
- mid  = 收盘价 MA(ma_period，默认 20)
- upper = mid + mult * ATR；lower = mid - mult * ATR
- 超涨  : 收盘价 > upper（价格进入极端强势区，潜在顶预警）
- 超跌  : 收盘价 < lower（价格进入极端弱势区，潜在底预警）
- 顶确认: 前一根超涨且当前根收盘 < 前一根收盘（强势后开始回落）→ 潜在顶
- 底确认: 前一根超跌且当前根收盘 > 前一根收盘（弱势后开始反弹）→ 潜在底

适用于任意周期（1/5/15/30/60 分、日/周/月），不局限于日内。
"""

from __future__ import annotations

import pandas as pd


def _bar_key(dt) -> str:
    """K 线日期键归一化：与 chan._dt_key 一致。

    "2026-08-07 00:00" -> "2026-08-07"（日/周/月K）
    "2026-08-07 10:30" -> "2026-08-07 10:30"（分钟K）
    """
    s = str(pd.Timestamp(dt))[:16]
    return s[:-6] if s.endswith(" 00:00") else s


def _wilder_smooth(values: pd.Series, period: int) -> pd.Series:
    """Wilder 平滑（等价于 alpha=1/period 的 EMA，起点为前 period 均值）。"""
    return values.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()


def compute_atr(
    df: pd.DataFrame,
    period: int = 14,
    mult: float = 2.5,
    ma_period: int = 20,
    confirm_amp_mult: float = 1.0,
    min_same_kind_gap: int = 5,
    max_confirm_bars: int = 3,
    warn_min_gap: int = 10,
) -> dict:
    """计算 ATR 通道与超涨/超跌/顶底信号。

    参数：
      df                : K线 DataFrame，需含 datetime/open/high/low/close
      period            : ATR 平滑周期
      mult              : 通道倍数（上/下轨 = mid ± mult*ATR）
      ma_period         : 中轨均线周期
      confirm_amp_mult  : 顶/底确认的最小回落/反弹幅度（×ATR）。
                          仅“超涨后回落 ≥ confirm_amp_mult×ATR”才算顶，
                          过滤主升浪/主跌浪中的小回调反复触发。
      min_same_kind_gap : 同类顶/底信号之间的最小 K 线间隔，防止连续抖动重复标记。
      max_confirm_bars  : 超涨/超跌段结束后，最多再等几根 K 线确认顶/底
                          （幅度未达阈值时顺延，价格反向则作废）。
      warn_min_gap      : 超涨/超跌预警之间的最小 K 线间隔（预警只提示“进入极端区”，
                          连续贴轨不重复标记，避免图上出现几十个三角）。

    返回：
      {
        "bars":   [{date, mid, upper, lower, atr}],  # 与 K 线对齐
        "signals":[{date, kind: overheat|oversold|top|bottom, price, note}]
      }
    """
    d = df.copy()
    d["datetime"] = pd.to_datetime(d["datetime"])
    d = d.sort_values("datetime").reset_index(drop=True)
    high = d["high"].astype(float)
    low = d["low"].astype(float)
    close = d["close"].astype(float)
    prev_close = close.shift(1)

    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = _wilder_smooth(tr, period)
    mid = close.rolling(ma_period, min_periods=ma_period).mean()
    upper = mid + mult * atr
    lower = mid - mult * atr

    overheat = close > upper
    oversold = close < lower

    bars: list[dict] = []
    for i in range(len(d)):
        bars.append(
            {
                "date": _bar_key(d["datetime"].iloc[i]),
                "mid": round(float(mid.iloc[i]), 2) if pd.notna(mid.iloc[i]) else None,
                "upper": round(float(upper.iloc[i]), 2) if pd.notna(upper.iloc[i]) else None,
                "lower": round(float(lower.iloc[i]), 2) if pd.notna(lower.iloc[i]) else None,
                "atr": round(float(atr.iloc[i]), 2) if pd.notna(atr.iloc[i]) else None,
            }
        )

    signals: list[dict] = []
    last_top_i = -10**9
    last_bottom_i = -10**9
    last_overheat_i = -10**9
    last_oversold_i = -10**9
    heat_run: dict | None = None   # 当前连续超涨段：段内最高价/日期/段末收盘
    cold_run: dict | None = None   # 当前连续超跌段
    heat_pending: dict | None = None
    cold_pending: dict | None = None
    for i in range(len(d)):
        date = _bar_key(d["datetime"].iloc[i])
        is_heat = pd.notna(overheat.iloc[i]) and bool(overheat.iloc[i])
        is_cold = pd.notna(oversold.iloc[i]) and bool(oversold.iloc[i])

        if is_heat:
            if i - last_overheat_i >= warn_min_gap:
                signals.append(
                    {
                        "date": date,
                        "kind": "overheat",
                        "price": round(float(close.iloc[i]), 2),
                        "note": f"收盘 {close.iloc[i]:.2f} 突破上轨 {upper.iloc[i]:.2f}（MA{ma_period}+{mult}×ATR{atr.iloc[i]:.2f}），进入极端强势区，警惕见顶",
                    }
                )
                last_overheat_i = i
            if heat_run is None:
                heat_run = {"max_high": float(high.iloc[i]), "max_high_i": i, "prev_close": float(close.iloc[i])}
            else:
                if float(high.iloc[i]) > heat_run["max_high"]:
                    heat_run["max_high"] = float(high.iloc[i])
                    heat_run["max_high_i"] = i
                heat_run["prev_close"] = float(close.iloc[i])

        if is_cold:
            if i - last_oversold_i >= warn_min_gap:
                signals.append(
                    {
                        "date": date,
                        "kind": "oversold",
                        "price": round(float(close.iloc[i]), 2),
                        "note": f"收盘 {close.iloc[i]:.2f} 跌破下轨 {lower.iloc[i]:.2f}（MA{ma_period}-{mult}×ATR{atr.iloc[i]:.2f}），进入极端弱势区，警惕见底",
                    }
                )
                last_oversold_i = i
            if cold_run is None:
                cold_run = {"min_low": float(low.iloc[i]), "min_low_i": i, "prev_close": float(close.iloc[i])}
            else:
                if float(low.iloc[i]) < cold_run["min_low"]:
                    cold_run["min_low"] = float(low.iloc[i])
                    cold_run["min_low_i"] = i
                cold_run["prev_close"] = float(close.iloc[i])

        # 超涨段结束 → 进入待确认状态（最多顺延 max_confirm_bars 根）
        if heat_run is not None and not is_heat:
            heat_pending = {
                "max_high": heat_run["max_high"],
                "max_high_i": heat_run["max_high_i"],
                "last_close": heat_run["prev_close"],
                "bars": 0,
            }
            heat_run = None

        # 顶确认：回落幅度达到阈值（可在段结束后的 max_confirm_bars 根内延迟确认）
        if heat_pending is not None:
            # 待确认期间若盘中创出更高价，顶价同步上移（仍用历史数据，无未来函数）
            if float(high.iloc[i]) > heat_pending["max_high"]:
                heat_pending["max_high"] = float(high.iloc[i])
                heat_pending["max_high_i"] = i
            if float(close.iloc[i]) < heat_pending["last_close"]:
                drop = heat_pending["last_close"] - float(close.iloc[i])
                heat_pending["bars"] += 1
                if drop >= confirm_amp_mult * float(atr.iloc[i]):
                    if i - last_top_i >= min_same_kind_gap:
                        extreme = _bar_key(d["datetime"].iloc[heat_pending["max_high_i"]])
                        signals.append(
                            {
                            "date": date,
                            "kind": "top",
                            "price": round(heat_pending["max_high"], 2),
                                "note": (
                                    f"超涨段最高 {heat_pending['max_high']:.2f}（{extreme}）后回落 "
                                    f"{drop:.2f}（≥{confirm_amp_mult}×ATR{atr.iloc[i]:.2f}），确认潜在顶部"
                                ),
                            }
                        )
                        last_top_i = i
                    heat_pending = None
                elif heat_pending["bars"] >= max_confirm_bars:
                    heat_pending = None
            else:
                heat_pending = None

        # 超跌段结束 → 进入待确认状态
        if cold_run is not None and not is_cold:
            cold_pending = {
                "min_low": cold_run["min_low"],
                "min_low_i": cold_run["min_low_i"],
                "last_close": cold_run["prev_close"],
                "bars": 0,
            }
            cold_run = None

        # 底确认：反弹幅度达到阈值（可延迟确认）
        if cold_pending is not None:
            # 待确认期间若盘中创出更低价，底价与基准收盘同步下移（8-03 这类“未超跌但创新低”也能接上）
            if float(low.iloc[i]) < cold_pending["min_low"]:
                cold_pending["min_low"] = float(low.iloc[i])
                cold_pending["min_low_i"] = i
            if float(close.iloc[i]) > cold_pending["last_close"]:
                rise = float(close.iloc[i]) - cold_pending["last_close"]
                cold_pending["bars"] += 1
                if rise >= confirm_amp_mult * float(atr.iloc[i]):
                    if i - last_bottom_i >= min_same_kind_gap:
                        extreme = _bar_key(d["datetime"].iloc[cold_pending["min_low_i"]])
                        signals.append(
                            {
                                "date": date,
                                "kind": "bottom",
                                "price": round(cold_pending["min_low"], 2),
                                "note": (
                                    f"超跌段最低 {cold_pending['min_low']:.2f}（{extreme}）后反弹 "
                                    f"{rise:.2f}（≥{confirm_amp_mult}×ATR{atr.iloc[i]:.2f}），确认潜在底部"
                                ),
                            }
                        )
                        last_bottom_i = i
                    cold_pending = None
                elif cold_pending["bars"] >= max_confirm_bars:
                    cold_pending = None
            else:
                # 仍在探底：基准收盘下移并重置计时，等真正反弹
                cold_pending["last_close"] = float(close.iloc[i])
                cold_pending["bars"] = 0

    return {
        "config": {
            "period": period,
            "mult": mult,
            "ma_period": ma_period,
            "confirm_amp_mult": confirm_amp_mult,
            "min_same_kind_gap": min_same_kind_gap,
            "max_confirm_bars": max_confirm_bars,
            "warn_min_gap": warn_min_gap,
        },
        "bars": bars,
        "signals": signals,
    }


def atr_signal_stats(
    df: pd.DataFrame,
    period: int = 14,
    mult: float = 2.5,
    ma_period: int = 20,
    horizon: int = 5,
    confirm_amp_mult: float = 1.0,
    min_same_kind_gap: int = 5,
    max_confirm_bars: int = 3,
    warn_min_gap: int = 10,
) -> dict:
    """顶/底信号的样本外统计：信号后 horizon 根 K 线的涨跌概率与平均收益。"""
    d = df.copy()
    d["datetime"] = pd.to_datetime(d["datetime"])
    d = d.sort_values("datetime").reset_index(drop=True)
    closes = d["close"].astype(float)
    res = compute_atr(
        d,
        period=period,
        mult=mult,
        ma_period=ma_period,
        confirm_amp_mult=confirm_amp_mult,
        min_same_kind_gap=min_same_kind_gap,
        max_confirm_bars=max_confirm_bars,
        warn_min_gap=warn_min_gap,
    )
    idx_of = {str(row["datetime"]): i for i, row in d.iterrows()}

    stats = {"top": {"n": 0, "down": 0, "avg_fwd": 0.0, "hit_rate": 0.0}, "bottom": {"n": 0, "up": 0, "avg_fwd": 0.0, "hit_rate": 0.0}}
    for s in res["signals"]:
        kind = s["kind"]
        if kind not in stats:
            continue
        i = idx_of.get(s["date"])
        if i is None or i + horizon >= len(d):
            continue
        fwd = closes.iloc[i + horizon] / closes.iloc[i] - 1.0
        stats[kind]["n"] += 1
        stats[kind]["avg_fwd"] += fwd
        if kind == "top" and fwd < 0:
            stats[kind]["down"] += 1
        if kind == "bottom" and fwd > 0:
            stats[kind]["up"] += 1
    for k, v in stats.items():
        if v["n"]:
            v["avg_fwd"] = round(v["avg_fwd"] / v["n"] * 100, 3)
            v["hit_rate"] = round((v["down"] if k == "top" else v["up"]) / v["n"] * 100, 1)
    return stats
