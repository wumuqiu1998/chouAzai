"""新手综合信号量：把趋势/ATR/缠论/量能加权成一个 -100~+100 的单一分数。

设计目标（新手友好）：
- 只看一个数：分数越高越偏多，越低越危险；
- 档位：>=40 加仓 / 10~40 偏多持有 / -10~10 观望 / -40~-10 偏空减仓 / <=-40 规避；
- 分项可展开看原因，默认只看总分。

分项权重（合计 100）：
- 趋势 30：收盘 vs MA20/MA60、均线多空排列、距 60 日高点回撤档位；
- ATR 25：超涨/超跌、已确认顶/底（复用 atr.compute_atr 过滤版）；
- 缠论 25：最近 30 根内的最后一个买卖点（含三卖预警）；
- 量能 20：新高缩量（顶部预警）、放量新高、放量破位。

时间审计：所有字段只用截至当前 K 线收盘的数据；信号 T 日收盘后可用，
最早 T+1 日开盘交易。计算历史任一点时传入 df.iloc[:i+1]。
"""

from __future__ import annotations

import pandas as pd

from quant_framework.atr import compute_atr
from quant_framework.chan import analyze_chan


def _pos_of(df: pd.DataFrame, date: str) -> int | None:
    """把指标信号日期映射回 df 行号（用于比较先后）。"""
    for i in range(len(df) - 1, -1, -1):
        s = str(pd.Timestamp(df["datetime"].iloc[i]))[:16]
        if s == date or s[:10] == date[:10]:
            return i
    return None


def compute_signal_score(
    df: pd.DataFrame,
    peak_lookback: int = 60,
    trailing_drawdown: float = 0.08,
    chan_window: int = 30,
) -> dict:
    """计算截至最后一根 K 线的综合信号量。

    df 需含 datetime/open/high/low/close/volume，按时间升序。
    返回：score / level / advice / parts(分项) / trailing_stop / volume_divergence。
    """
    d = df.copy()
    d["datetime"] = pd.to_datetime(d["datetime"])
    d = d.sort_values("datetime").reset_index(drop=True)
    if len(d) < 60:
        return {"score": 0, "level": "观望", "advice": "K线不足60根，无法计算", "parts": {}, "trailing_stop": None}

    close = d["close"].astype(float)
    high = d["high"].astype(float)
    low = d["low"].astype(float)
    vol = d["volume"].astype(float)
    last = len(d) - 1
    price = float(close.iloc[last])
    ma20 = float(close.rolling(20).mean().iloc[last])
    ma60 = float(close.rolling(60).mean().iloc[last])

    # ---------- 趋势分（30） ----------
    trend = 0
    trend_reasons: list[str] = []
    trend += 5 if price > ma20 else -5
    trend_reasons.append(f"收盘{price:.2f} {'>' if price > ma20 else '<'} MA20={ma20:.2f} {'+5' if price > ma20 else '-5'}")
    trend += 5 if price > ma60 else -5
    trend_reasons.append(f"收盘{' >' if price > ma60 else ' <'} MA60={ma60:.2f} {'+5' if price > ma60 else '-5'}")
    trend += 10 if ma20 > ma60 else -10
    trend_reasons.append(f"MA20{' >' if ma20 > ma60 else ' <'} MA60，{'多头排列 +10' if ma20 > ma60 else '空头排列 -10'}")

    peak_high = float(high.iloc[-peak_lookback:].max())
    drawdown = price / peak_high - 1.0
    if drawdown >= -trailing_drawdown:
        trend += 0
        trend_reasons.append(f"距60日高点回撤 {drawdown:.1%}（未触发移动止盈，0）")
    elif drawdown >= -0.15:
        trend -= 10
        trend_reasons.append(f"距60日高点回撤 {drawdown:.1%}（已触发移动止盈线，-10）")
    else:
        trend -= 15
        trend_reasons.append(f"距60日高点回撤 {drawdown:.1%}（已深跌，-15）")

    # ---------- ATR 分（25） ----------
    atr = compute_atr(d)
    atr_score = 0
    atr_reasons: list[str] = []
    top_pos = bottom_pos = -1
    heat_now = cold_now = False
    for s in atr["signals"]:
        p = _pos_of(d, s["date"])
        if p is None:
            continue
        if s["kind"] == "top":
            top_pos = max(top_pos, p)
        elif s["kind"] == "bottom":
            bottom_pos = max(bottom_pos, p)
        elif s["kind"] == "overheat" and p == last:
            heat_now = True
        elif s["kind"] == "oversold" and p == last:
            cold_now = True
    if top_pos >= 0 and top_pos > bottom_pos:
        atr_score -= 20
        atr_reasons.append("最近确认 ATR 顶（-20）")
    elif bottom_pos >= 0 and bottom_pos > top_pos:
        atr_score += 20
        atr_reasons.append("最近确认 ATR 底（+20）")
    else:
        atr_reasons.append("无 ATR 顶/底确认（0）")
    if heat_now:
        atr_score -= 5
        atr_reasons.append("当前超涨（-5）")
    if cold_now:
        atr_score += 5
        atr_reasons.append("当前超跌（+5）")

    # ---------- 缠论分（25） ----------
    chan = analyze_chan(d)
    chan_score = 0
    chan_reasons: list[str] = []
    latest_point = None
    for p in chan["points"]:
        pos = p.get("pos")
        if pos is None:
            pos = _pos_of(d, p["date"])
        if pos is None or pos > last or pos < last - chan_window:
            continue
        if latest_point is None or pos > latest_point["pos"]:
            latest_point = {"pos": pos, "kind": p["kind"], "date": p["date"]}
    if latest_point:
        if latest_point["kind"].startswith("buy"):
            chan_score += 20
            chan_reasons.append(f"最近缠论买点 {latest_point['kind'].upper()}（{latest_point['date']}，+20）")
        else:
            chan_score -= 20
            chan_reasons.append(f"最近缠论卖点/预警 {latest_point['kind'].upper()}（{latest_point['date']}，-20）")
    else:
        chan_reasons.append(f"近{chan_window}根无缠论买卖点（0）")

    # ---------- 量能分（20） ----------
    vol_score = 0
    vol_reasons: list[str] = []
    vol_divergence: list[dict] = []
    avg5 = float(vol.iloc[max(0, last - 5) : last].mean())
    # 新高缩量（近 20 根内出现）
    for i in range(max(1, last - 20), last + 1):
        prev_high = float(high.iloc[max(0, i - 20) : i].max())
        if float(close.iloc[i]) >= prev_high and float(high.iloc[i]) >= prev_high:
            v_avg = float(vol.iloc[max(0, i - 5) : i].mean())
            if v_avg > 0 and float(vol.iloc[i]) <= v_avg * 0.85:
                vol_divergence.append({"date": str(pd.Timestamp(d["datetime"].iloc[i]))[:16], "price": round(float(close.iloc[i]), 2)})
    if vol_divergence:
        vol_score -= 15
        vol_reasons.append(f"新高缩量 {len(vol_divergence)} 次（顶部预警，-15）")
    # 当前放量新高 / 放量破位
    prev20_high = float(high.iloc[max(0, last - 20) : last].max())
    prev20_low = float(low.iloc[max(0, last - 20) : last].min())
    if price >= prev20_high and avg5 > 0 and float(vol.iloc[last]) >= avg5 * 1.2:
        vol_score += 10
        vol_reasons.append("放量创20日新高（+10）")
    elif price <= prev20_low and avg5 > 0 and float(vol.iloc[last]) >= avg5 * 1.2:
        vol_score -= 10
        vol_reasons.append("放量跌破20日低点（-10）")
    else:
        vol_reasons.append("量能无极端信号（0）")

    total = max(-100, min(100, trend + atr_score + chan_score + vol_score))
    if total >= 40:
        level, advice = "加仓", "偏多强势：可分批介入，跌破MA20或信号量转负再减"
    elif total >= 10:
        level, advice = "偏多", "趋势尚可：持有为主，回撤超8%开始减仓"
    elif total > -10:
        level, advice = "观望", "多空不明：空仓等待，不追高不抄底"
    elif total > -40:
        level, advice = "偏空", "弱势减仓：逢反弹减仓，不接飞刀"
    else:
        level, advice = "规避", "强风险区：清仓规避，等信号量回到0上方再看"

    stop_price = peak_high * (1.0 - trailing_drawdown)
    return {
        "score": total,
        "level": level,
        "advice": advice,
        "price": round(price, 2),
        "parts": {
            "trend": {"score": trend, "weight": 30, "reasons": trend_reasons},
            "atr": {"score": atr_score, "weight": 25, "reasons": atr_reasons},
            "chan": {"score": chan_score, "weight": 25, "reasons": chan_reasons},
            "volume": {"score": vol_score, "weight": 20, "reasons": vol_reasons},
        },
        "trailing_stop": {
            "peak_high": round(peak_high, 2),
            "peak_date": str(pd.Timestamp(d["datetime"].iloc[int(high.iloc[-peak_lookback:].idxmax())]))[:10],
            "stop_price": round(stop_price, 2),
            "drawdown_pct": round(drawdown * 100, 2),
            "triggered": bool(low.iloc[last] <= stop_price),
        },
        "volume_divergence": vol_divergence,
    }
