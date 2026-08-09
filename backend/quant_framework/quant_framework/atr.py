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


def _wilder_smooth(values: pd.Series, period: int) -> pd.Series:
    """Wilder 平滑（等价于 alpha=1/period 的 EMA，起点为前 period 均值）。"""
    return values.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()


def compute_atr(
    df: pd.DataFrame,
    period: int = 14,
    mult: float = 2.5,
    ma_period: int = 20,
) -> dict:
    """计算 ATR 通道与超涨/超跌/顶底信号。

    参数：
      df       : K线 DataFrame，需含 datetime/open/high/low/close
      period   : ATR 平滑周期
      mult     : 通道倍数（上/下轨 = mid ± mult*ATR）
      ma_period: 中轨均线周期

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
    top = overheat.shift(1) & (close < close.shift(1))
    bottom = oversold.shift(1) & (close > close.shift(1))

    bars: list[dict] = []
    for i in range(len(d)):
        bars.append(
            {
                "date": str(d["datetime"].iloc[i]),
                "mid": round(float(mid.iloc[i]), 4) if pd.notna(mid.iloc[i]) else None,
                "upper": round(float(upper.iloc[i]), 4) if pd.notna(upper.iloc[i]) else None,
                "lower": round(float(lower.iloc[i]), 4) if pd.notna(lower.iloc[i]) else None,
                "atr": round(float(atr.iloc[i]), 4) if pd.notna(atr.iloc[i]) else None,
            }
        )

    signals: list[dict] = []
    for i in range(len(d)):
        date = str(d["datetime"].iloc[i])
        if pd.notna(overheat.iloc[i]) and bool(overheat.iloc[i]):
            signals.append(
                {
                    "date": date,
                    "kind": "overheat",
                    "price": round(float(close.iloc[i]), 4),
                    "note": f"收盘 {close.iloc[i]:.2f} 突破上轨 {upper.iloc[i]:.2f}（MA{ma_period}+{mult}×ATR{atr.iloc[i]:.2f}），进入极端强势区，警惕见顶",
                }
            )
        if pd.notna(oversold.iloc[i]) and bool(oversold.iloc[i]):
            signals.append(
                {
                    "date": date,
                    "kind": "oversold",
                    "price": round(float(close.iloc[i]), 4),
                    "note": f"收盘 {close.iloc[i]:.2f} 跌破下轨 {lower.iloc[i]:.2f}（MA{ma_period}-{mult}×ATR{atr.iloc[i]:.2f}），进入极端弱势区，警惕见底",
                }
            )
        if pd.notna(top.iloc[i]) and bool(top.iloc[i]):
            signals.append(
                {
                    "date": date,
                    "kind": "top",
                    "price": round(float(close.iloc[i]), 4),
                    "note": f"超涨后回落（收盘 {close.iloc[i]:.2f} < 前收 {close.iloc[i-1]:.2f}），确认潜在顶部",
                }
            )
        if pd.notna(bottom.iloc[i]) and bool(bottom.iloc[i]):
            signals.append(
                {
                    "date": date,
                    "kind": "bottom",
                    "price": round(float(close.iloc[i]), 4),
                    "note": f"超跌后反弹（收盘 {close.iloc[i]:.2f} > 前收 {close.iloc[i-1]:.2f}），确认潜在底部",
                }
            )

    return {
        "config": {"period": period, "mult": mult, "ma_period": ma_period},
        "bars": bars,
        "signals": signals,
    }


def atr_signal_stats(
    df: pd.DataFrame,
    period: int = 14,
    mult: float = 2.5,
    ma_period: int = 20,
    horizon: int = 5,
) -> dict:
    """顶/底信号的样本外统计：信号后 horizon 根 K 线的涨跌概率与平均收益。"""
    d = df.copy()
    d["datetime"] = pd.to_datetime(d["datetime"])
    d = d.sort_values("datetime").reset_index(drop=True)
    closes = d["close"].astype(float)
    res = compute_atr(d, period=period, mult=mult, ma_period=ma_period)
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
