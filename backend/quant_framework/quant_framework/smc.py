"""ICT/SMC（聪明钱概念）结构标注：订单块 / 公平价值缺口 / 流动性扫荡 / 结构突破。

核心思想：机构（聪明钱）的挂单与止损是价格行为的"流动性"，价格会主动去
扫掉这些流动性再反转。本模块把四个最可落地、可审计的概念做成 K 线结构信号：

1. FVG 公平价值缺口（Imbalance）：三根 K 线之间未被填补的缺口区间，
   价格有回补倾向（看涨缺口 = K1.high < K3.low）。
2. OB 订单块（Order Block）：一段反向推动前的最后一根 K 线（机构建仓痕迹），
   回踩该区间是潜在入场区。
3. 流动性扫荡（Liquidity Sweep）：价格突破最近高点/低点（触发止损）后快速收回，
   是反转的强信号。
4. BOS/CHoCH 市场结构：突破同向前高/前低（趋势延续）或反向突破（趋势变化）。

全部只用已收盘 K 线，结构点需右侧确认（无未来函数）。
"""

from __future__ import annotations

import pandas as pd


def _filter_sweep_gap(sweeps: list[dict], min_gap: int) -> list[dict]:
    """扫荡信号按日期做最小间隔过滤，避免主升浪中反复交替出现。"""
    if min_gap <= 0 or len(sweeps) <= 1:
        return sweeps
    kept: list[dict] = []
    last = ""
    for s in sweeps:
        d = str(s.get("date", ""))[:10]
        if not last or (pd.Timestamp(d) - pd.Timestamp(last)).days >= min_gap:
            kept.append(s)
            last = d
    return kept


def _swings(df: pd.DataFrame, left: int = 2, right: int = 2) -> list[dict]:
    """局部高低点（分型）：中间 K 线高于/低于左右各 right 根。需右侧确认。"""
    highs = df["high"].astype(float).values
    lows = df["low"].astype(float).values
    dts = df["datetime"].values
    out: list[dict] = []
    for i in range(left, len(df) - right):
        win_h = highs[i - left : i + right + 1]
        win_l = lows[i - left : i + right + 1]
        if highs[i] == win_h.max() and lows[i] == win_l.max():
            out.append({"pos": i, "date": str(pd.Timestamp(dts[i]))[:16].replace(" 00:00", ""), "price": float(highs[i]), "kind": "high"})
        elif lows[i] == win_l.min() and highs[i] == win_h.min():
            out.append({"pos": i, "date": str(pd.Timestamp(dts[i]))[:16].replace(" 00:00", ""), "price": float(lows[i]), "kind": "low"})
    return out


def analyze_smc(
    df: pd.DataFrame,
    swing_left: int = 2,
    swing_right: int = 2,
    lookback: int = 80,
    sweep_min_gap: int = 15,
) -> dict:
    d = df.copy()
    d["datetime"] = pd.to_datetime(d["datetime"])
    d = d.sort_values("datetime").reset_index(drop=True)
    high = d["high"].astype(float)
    low = d["low"].astype(float)
    close = d["close"].astype(float)
    open_ = d["open"].astype(float)

    # 1) FVG：三根 K 线缺口（T+2 确认）
    fvg: list[dict] = []
    for i in range(len(d) - 2):
        if high.iloc[i] < low.iloc[i + 2] - 1e-9:
            fvg.append(
                {
                    "date": str(d["datetime"].iloc[i + 2])[:16].replace(" 00:00", ""),
                    "kind": "bullish",
                    "bottom": round(float(high.iloc[i]), 4),
                    "top": round(float(low.iloc[i + 2]), 4),
                }
            )
        elif low.iloc[i] > high.iloc[i + 2] + 1e-9:
            fvg.append(
                {
                    "date": str(d["datetime"].iloc[i + 2])[:16].replace(" 00:00", ""),
                    "kind": "bearish",
                    "bottom": round(float(high.iloc[i + 2]), 4),
                    "top": round(float(low.iloc[i]), 4),
                }
            )
    # 标记是否已被回补（用截至当前的价格区间）
    for g in fvg:
        g["filled"] = bool(close.max() >= g["bottom"] and close.min() <= g["top"])

    # 2) OB 订单块：一段反向推进前的最后一根 K 线
    ob: list[dict] = []
    for i in range(2, len(d) - 1):
        # 看涨 OB：前面 2+ 根阴线（或低点走低），当前为阳线
        bearish_before = (close.iloc[i - 1] < open_.iloc[i - 1]) and (close.iloc[i - 2] < open_.iloc[i - 2])
        if bearish_before and close.iloc[i] > open_.iloc[i]:
            ob.append(
                {
                    "date": str(d["datetime"].iloc[i])[:16].replace(" 00:00", ""),
                    "kind": "bullish",
                    "bottom": round(float(low.iloc[i]), 4),
                    "top": round(float(high.iloc[i]), 4),
                }
            )
        # 看跌 OB：前面 2+ 根阳线，当前为阴线
        bullish_before = (close.iloc[i - 1] > open_.iloc[i - 1]) and (close.iloc[i - 2] > open_.iloc[i - 2])
        if bullish_before and close.iloc[i] < open_.iloc[i]:
            ob.append(
                {
                    "date": str(d["datetime"].iloc[i])[:16].replace(" 00:00", ""),
                    "kind": "bearish",
                    "bottom": round(float(low.iloc[i]), 4),
                    "top": round(float(high.iloc[i]), 4),
                }
            )
    # 只保留最近 lookback 个，去重（同方向连续只取最后）
    dedup: list[dict] = []
    for g in ob:
        if dedup and dedup[-1]["kind"] == g["kind"]:
            dedup[-1] = g
        else:
            dedup.append(g)
    ob = dedup[-lookback:]

    # 3) 流动性扫荡：突破最近 swing high/low 后收盘收回
    swings = _swings(d, swing_left, swing_right)
    sweeps: list[dict] = []
    recent_high = next((s for s in reversed(swings) if s["kind"] == "high"), None)
    recent_low = next((s for s in reversed(swings) if s["kind"] == "low"), None)
    for i in range(swing_left + swing_right, len(d)):
        if recent_high and high.iloc[i] > recent_high["price"] and close.iloc[i] < recent_high["price"]:
            sweeps.append(
                {
                    "date": str(d["datetime"].iloc[i])[:16].replace(" 00:00", ""),
                    "kind": "bearish",
                    "price": round(float(close.iloc[i]), 4),
                    "note": f"突破前高 {recent_high['price']:.2f} 后收回，扫掉追多止损（卖方流动性）→ 潜在反转",
                }
            )
        if recent_low and low.iloc[i] < recent_low["price"] and close.iloc[i] > recent_low["price"]:
            sweeps.append(
                {
                    "date": str(d["datetime"].iloc[i])[:16].replace(" 00:00", ""),
                    "kind": "bullish",
                    "price": round(float(close.iloc[i]), 4),
                    "note": f"跌破前低 {recent_low['price']:.2f} 后收回，扫掉割肉止损（买方流动性）→ 潜在反转",
                }
            )

    # 4) 市场结构：最后两个 swing 的方向 + 最近突破
    structure = {"state": "range", "last_bos": None, "last_choch": None}
    if len(swings) >= 4:
        s1, s2, s3 = swings[-3], swings[-2], swings[-1]
        # 最后确认的结构方向
        if s2["kind"] == "high" and s2["price"] > s1["price"] and s3["kind"] == "low" and s3["price"] > s1["price"]:
            structure["state"] = "bullish"
        elif s2["kind"] == "low" and s2["price"] < s1["price"] and s3["kind"] == "high" and s3["price"] < s1["price"]:
            structure["state"] = "bearish"
        last = swings[-1]
        if last["kind"] == "high":
            prev_high = next((s for s in reversed(swings[:-1]) if s["kind"] == "high"), None)
            if prev_high:
                if last["price"] > prev_high["price"]:
                    structure["last_bos"] = {"date": last["date"], "kind": "bullish", "price": last["price"], "note": f"突破前高 {prev_high['price']:.2f}（BOS，趋势延续）"}
                else:
                    structure["last_choch"] = {"date": last["date"], "kind": "bearish", "price": last["price"], "note": f"未能突破前高 {prev_high['price']:.2f} 且结构反向（CHoCH 候选）"}
        elif last["kind"] == "low":
            prev_low = next((s for s in reversed(swings[:-1]) if s["kind"] == "low"), None)
            if prev_low:
                if last["price"] < prev_low["price"]:
                    structure["last_bos"] = {"date": last["date"], "kind": "bearish", "price": last["price"], "note": f"跌破前低 {prev_low['price']:.2f}（BOS，趋势延续）"}
                else:
                    structure["last_choch"] = {"date": last["date"], "kind": "bullish", "price": last["price"], "note": f"未跌破前低 {prev_low['price']:.2f} 且结构反向（CHoCH 候选）"}

    return {
        "fvg": fvg[-lookback:],
        "ob": ob,
        "sweeps": _filter_sweep_gap(sweeps[-20:], sweep_min_gap),
        "structure": structure,
        "note": "ICT/SMC 结构标注：FVG/OB/扫荡/结构突破，全部用已收盘数据、结构点需右侧确认",
    }
