"""威科夫（Wyckoff）主力筹码阶段判断：吸筹 → 拉升 → 派发 → 下跌 循环。

简化口径（全部只用截至 T 日收盘的数据，无未来函数）：
- 吸筹 accumulation：低位横盘（均线缠绕 + 波动收窄 + 前期涨幅小）+ 缩量，
  出现放量长下影（Spring）为吸筹确认信号；
- 拉升 markup：价格站上 MA20/MA60 且 MA20 斜率向上（趋势跟踪）；
- 派发 distribution：高位横盘（前期涨幅大）+ 放量滞涨，
  出现放量长上影（Upthrust）为派发确认信号；
- 下跌 markdown：价格跌破 MA20/MA60 且 MA20 斜率向下。

主力成本区 = 最近一个吸筹/派发区间的价格带（成交密集区），
供判断当前价格相对主力成本的位置。
"""

from __future__ import annotations

import pandas as pd


def _slope(ma: pd.Series, window: int = 5) -> pd.Series:
    return ma / ma.shift(window) - 1.0


def analyze_wyckoff(
    df: pd.DataFrame,
    trend_period: int = 20,
    slow_period: int = 60,
    range_window: int = 40,
    range_band: float = 0.16,
    slope_threshold: float = 0.004,
    low_gain: float = 0.08,
    high_gain: float = 0.18,
    vol_ratio: float = 1.4,
) -> dict:
    d = df.copy()
    d["datetime"] = pd.to_datetime(d["datetime"])
    d = d.sort_values("datetime").reset_index(drop=True)
    close = d["close"].astype(float)
    high = d["high"].astype(float)
    low = d["low"].astype(float)
    vol = d["volume"].astype(float)

    ma_fast = close.rolling(trend_period, min_periods=trend_period).mean()
    ma_slow = close.rolling(slow_period, min_periods=slow_period).mean()
    slope = _slope(ma_fast)
    avg_vol = vol.rolling(trend_period, min_periods=trend_period).mean()
    # 近 range_window 日横盘判定：区间振幅 + 均线缠绕
    roll_high = high.rolling(range_window, min_periods=range_window).max()
    roll_low = low.rolling(range_window, min_periods=range_window).min()
    roll_range = (roll_high - roll_low) / close
    ma_gap = (ma_fast / ma_slow - 1.0).abs()
    flat = (roll_range < range_band) & (ma_gap < 0.025)
    gain60 = close / close.shift(slow_period) - 1.0
    gain20 = close / close.shift(trend_period) - 1.0

    up = (close > ma_fast) & (ma_fast > ma_slow) & (slope > slope_threshold)
    down = (close < ma_fast) & (ma_fast < ma_slow) & (slope < -slope_threshold)
    acc = flat & (gain60 < low_gain)
    dist = flat & (gain60 > high_gain)
    # 兜底：横盘但不高不低 → 按位置归入吸筹/派发（低位更偏吸筹）
    acc = acc | (flat & ~dist & ~up & ~down & (gain20 <= 0))
    dist = dist | (flat & ~acc & ~up & ~down & (gain20 > 0))

    states = pd.Series("range", index=d.index, dtype=object)
    states[acc] = "accumulation"
    states[dist] = "distribution"
    states[up & ~flat] = "markup"
    states[down & ~flat] = "markdown"

    # Spring / Upthrust 信号（需在对应阶段内 + 放量 + 影线足够长）
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / 14, min_periods=14, adjust=False).mean()
    lower_shadow = (pd.concat([close, d["open"].astype(float)], axis=1).min(axis=1) - low) / atr.replace(0, pd.NA)
    upper_shadow = (high - pd.concat([close, d["open"].astype(float)], axis=1).max(axis=1)) / atr.replace(0, pd.NA)
    vol_ok = vol > avg_vol * vol_ratio
    spring = (states == "accumulation") & vol_ok & (lower_shadow > 0.8)
    upthrust = (states == "distribution") & vol_ok & (upper_shadow > 0.8)

    bars: list[dict] = []
    signals: list[dict] = []
    for i in range(len(d)):
        bars.append(
            {
                "date": str(d["datetime"].iloc[i])[:16].replace(" 00:00", ""),
                "state": str(states.iloc[i]),
            }
        )
        if bool(spring.iloc[i]) if pd.notna(spring.iloc[i]) else False:
            signals.append(
                {
                    "date": bars[-1]["date"],
                    "kind": "spring",
                    "price": round(float(close.iloc[i]), 4),
                    "note": f"吸筹区放量长下影（下影 {lower_shadow.iloc[i]:.1f}×ATR），疑似主力吸筹确认（Spring）",
                }
            )
        if bool(upthrust.iloc[i]) if pd.notna(upthrust.iloc[i]) else False:
            signals.append(
                {
                    "date": bars[-1]["date"],
                    "kind": "upthrust",
                    "price": round(float(close.iloc[i]), 4),
                    "note": f"派发区放量长上影（上影 {upper_shadow.iloc[i]:.1f}×ATR），疑似主力派发确认（Upthrust）",
                }
            )

    # 阶段区间切分（连续同状态合并）
    phases: list[dict] = []
    for b in bars:
        if phases and phases[-1]["phase"] == b["state"]:
            phases[-1]["end"] = b["date"]
            continue
        phases.append({"start": b["date"], "end": b["date"], "phase": b["state"]})

    current = phases[-1] if phases else {"phase": "range", "start": "", "end": ""}
    # 主力成本区：最近一个吸筹/派发区间的价格带
    cost_zone: dict | None = None
    for ph in reversed(phases):
        if ph["phase"] in ("accumulation", "distribution"):
            mask = (states.index >= 0)  # 简化：按阶段区间索引
            seg = d[(d["datetime"].dt.strftime("%Y-%m-%d") >= ph["start"][:10]) & (d["datetime"].dt.strftime("%Y-%m-%d") <= ph["end"][:10])]
            if len(seg) >= 5:
                lo = float(seg["low"].min())
                hi = float(seg["high"].max())
                mid = float(seg["close"].median())
                cost_zone = {
                    "phase": ph["phase"],
                    "start": ph["start"],
                    "end": ph["end"],
                    "low": round(lo, 2),
                    "high": round(hi, 2),
                    "mid": round(mid, 2),
                }
            break

    last = float(close.iloc[-1]) if len(close) else 0.0
    return {
        "bars": bars,
        "phases": phases,
        "current": {"phase": current["phase"], "since": current["start"], "days": sum(1 for b in bars if b["date"] >= current["start"])},
        "cost_zone": cost_zone,
        "signals": signals,
        "last_close": round(last, 2),
        "note": "阶段用 T 日收盘计算、T+1 生效；主力成本区为最近吸筹/派发区间的价格带",
    }
