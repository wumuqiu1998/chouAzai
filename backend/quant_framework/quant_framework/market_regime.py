"""市场趋势分析：道士理论（高低点结构）+ 趋势跟踪（指数均线斜率）的现代应用。

对主要宽基指数分别做三态（上升/下跌/震荡）判定，再按权重聚合出市场总趋势，
并输出各指数的 20 日涨跌幅与结构状态。全部使用已收盘数据，T 日收盘后可用。
"""

from __future__ import annotations

import pandas as pd

from quant_framework.regime import classify_regime

# 主要宽基指数（腾讯代码）
INDICES = [
    ("上证指数", "sh000001", 0.3),
    ("沪深300", "sh000300", 0.3),
    ("创业板指", "sz399006", 0.2),
    ("深证成指", "sz399001", 0.2),
]

STATE_SCORE = {"up": 1.0, "range": 0.0, "down": -1.0}


def _regime_label(score: float) -> str:
    if score >= 0.6:
        return "strong_up"
    if score >= 0.2:
        return "up"
    if score > -0.2:
        return "range"
    if score > -0.6:
        return "down"
    return "strong_down"


def analyze_market(
    trend_period: int = 20,
    slow_period: int = 60,
    slope_threshold: float = 0.004,
    offset: int = 320,
) -> dict:
    """分析市场趋势。返回各指数状态 + 市场总评级 + 结构摘要。"""
    import astock

    details: list[dict] = []
    score_sum = 0.0
    weight_sum = 0.0
    for name, code, weight in INDICES:
        try:
            rows = astock.index_kline(code, offset=offset)
        except Exception:
            rows = []
        if not rows:
            continue
        df = pd.DataFrame(rows)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        close = df["close"].astype(float)
        states = classify_regime(
            close,
            trend_period=trend_period,
            slow_period=slow_period,
            slope_threshold=slope_threshold,
        )
        state = str(states.iloc[-1]) if len(states) else "range"
        ret20 = float(close.iloc[-1] / close.iloc[-21] - 1) if len(close) > 21 else 0.0
        ma20 = float(close.rolling(trend_period).mean().iloc[-1]) if len(close) >= trend_period else None
        last = float(close.iloc[-1])
        # 道士理论：最近高低点结构（T-1 已确认的高低点）
        highs = df["high"].astype(float)
        lows = df["low"].astype(float)
        higher_high = bool(len(highs) > 22 and highs.iloc[-2] > highs.iloc[-22] and lows.iloc[-2] > lows.iloc[-22])
        lower_low = bool(len(lows) > 22 and lows.iloc[-2] < lows.iloc[-22] and highs.iloc[-2] < highs.iloc[-22])
        details.append(
            {
                "name": name,
                "code": code,
                "state": state,
                "last": round(last, 2),
                "ma20": round(ma20, 2) if ma20 else None,
                "ret20_pct": round(ret20 * 100, 2),
                "structure": "higher_high" if higher_high else ("lower_low" if lower_low else "mixed"),
            }
        )
        score_sum += STATE_SCORE[state] * weight
        weight_sum += weight

    market_score = score_sum / weight_sum if weight_sum else 0.0
    market_state = _regime_label(market_score)
    # 多头/空头占比
    up_n = sum(1 for d in details if d["state"] == "up")
    down_n = sum(1 for d in details if d["state"] == "down")
    return {
        "market": {
            "state": market_state,
            "score": round(market_score, 3),
            "label": {
                "strong_up": "强上升趋势",
                "up": "上升趋势",
                "range": "震荡市",
                "down": "下跌趋势",
                "strong_down": "强下跌趋势",
            }[market_state],
            "up_count": up_n,
            "down_count": down_n,
            "total": len(details),
        },
        "indices": details,
        "note": "趋势状态按 T 日收盘计算，T+1 生效；道士结构用最近高低点是否抬高/压低判断",
    }
