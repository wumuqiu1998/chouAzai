"""缠论研究实现（简化教学口径，可回测、可审计）。

研究假设卡（简化版）：
- 市场观察：缠中说禅的"分形/笔/线段/中枢/背驰/三类买卖点"能刻画走势结构；
- 信号定义：按下方简化算法从 OHLC 中识别笔、中枢、背驰并输出 B1/B2/B3/S1/S2/S3；
- 数据时间：全部使用当日收盘后的数据计算，信号最早 T+1 可用；
- 失败标准：简化口径与官方严格定义存在偏差，信号必须经回测与对抗审计后再使用。

简化口径说明（非官方严格定义）：
1. K 线包含处理按方向合并（向上取高高/低高，向下取高低/低低）；
2. 分型使用合并后的三根 K 线判断；
3. 笔要求顶底分型交替且间隔 >= min_gap 根合并 K 线（默认 4，可调）；
4. 中枢 = 连续 3 笔的重叠区间 [ZD, ZG]；
5. 背驰 = 离开段相对进入段力度（笔的价差）更弱且创新高/低；
6. 三类买卖点按标准场景推导，供可视化与研究参考。
"""

from __future__ import annotations

import pandas as pd


def _dt_key(dt) -> str:
    s = str(pd.Timestamp(dt))[:16]
    return s[:-6] if s.endswith(" 00:00") else s  # "2025-11-19 00:00" -> "2025-11-19"


def merge_contained(df: pd.DataFrame) -> pd.DataFrame:
    """K 线包含关系处理：按方向合并，返回带 pos/date/end_date 的合并 K 线。"""
    if len(df) < 3:
        return df.copy()
    out: list[dict] = []
    direction = 0  # 1=向上处理, -1=向下处理
    for row in df.itertuples():
        date = _dt_key(row.datetime)
        bar = {
            "pos": len(out),
            "date": date,
            "end_date": date,
            "open": float(row.open),
            "close": float(row.close),
            "high": float(row.high),
            "low": float(row.low),
            "volume": float(getattr(row, "volume", 0) or 0),
        }
        if not out:
            out.append(bar)
            continue
        prev = out[-1]
        contains = (bar["high"] >= prev["high"] and bar["low"] <= prev["low"]) or (
            bar["high"] <= prev["high"] and bar["low"] >= prev["low"]
        )
        if not contains:
            if bar["high"] > prev["high"]:
                direction = 1
            elif bar["low"] < prev["low"]:
                direction = -1
            out.append(bar)
            continue
        # 包含合并
        if direction >= 0:
            prev["high"] = max(prev["high"], bar["high"])
            prev["low"] = max(prev["low"], bar["low"])
        else:
            prev["high"] = min(prev["high"], bar["high"])
            prev["low"] = min(prev["low"], bar["low"])
        prev["close"] = bar["close"]
        prev["volume"] += bar["volume"]
        prev["end_date"] = bar["end_date"]
    return pd.DataFrame(out)


def find_fractals(merged: pd.DataFrame) -> list[dict]:
    """顶/底分型：中间 K 线高低点均高于（低于）两侧。"""
    rows: list[dict] = []
    m = merged.reset_index(drop=True)
    for i in range(1, len(m) - 1):
        a, b, c = m.iloc[i - 1], m.iloc[i], m.iloc[i + 1]
        if b["high"] > a["high"] and b["high"] > c["high"] and b["low"] > a["low"] and b["low"] > c["low"]:
            rows.append({"pos": int(b["pos"]), "date": str(b["end_date"]), "price": float(b["high"]), "kind": "top"})
        elif b["low"] < a["low"] and b["low"] < c["low"] and b["high"] < a["high"] and b["high"] < c["high"]:
            rows.append({"pos": int(b["pos"]), "date": str(b["end_date"]), "price": float(b["low"]), "kind": "bottom"})
    return rows


def find_bi(fractals: list[dict], min_gap: int = 4) -> list[dict]:
    """笔：顶底分型交替，间隔 >= min_gap 根合并 K 线；同类型取更极端。"""
    bis: list[dict] = []
    for f in fractals:
        if not bis:
            bis.append(dict(f))
            continue
        last = bis[-1]
        if f["kind"] == last["kind"]:
            better = (f["kind"] == "top" and f["price"] > last["price"]) or (
                f["kind"] == "bottom" and f["price"] < last["price"]
            )
            if better:
                bis[-1] = dict(f)
            continue
        if f["pos"] - last["pos"] < min_gap:
            continue
        bis.append(dict(f))
    return bis


def find_zhongshu(bis: list[dict], min_overlap: int = 3) -> list[dict]:
    """中枢：连续 min_overlap 笔的重叠区间 [ZD, ZG]。"""
    zs: list[dict] = []
    for i in range(len(bis) - min_overlap):
        seg = bis[i : i + min_overlap + 1]
        lows = [min(seg[j]["price"], seg[j + 1]["price"]) for j in range(min_overlap)]
        highs = [max(seg[j]["price"], seg[j + 1]["price"]) for j in range(min_overlap)]
        zd, zg = max(lows), min(highs)
        if zd < zg:
            zs.append(
                {
                    "start_pos": seg[0]["pos"],
                    "end_pos": seg[-1]["pos"],
                    "start_date": seg[0]["date"],
                    "end_date": seg[-1]["date"],
                    "zd": round(zd, 2),
                    "zg": round(zg, 2),
                }
            )
    # 简化口径：保留每个"连续 3 笔重叠窗"作为独立中枢，不做激进合并，
    # 避免合成/震荡行情把多个中枢并成一个。相邻同区间窗可在后续版本做去重。
    return zs


def _bi_force(bis: list[dict], idx: int) -> float:
    if idx <= 0 or idx >= len(bis):
        return 0.0
    return abs(bis[idx]["price"] - bis[idx - 1]["price"])


def buy_sell_points(bis: list[dict], zhongshu: list[dict], min_same_kind_gap: int = 20) -> list[dict]:
    """三类买卖点（简化场景推导）。

    min_same_kind_gap：同一类买卖点（如 buy1）之间至少间隔多少根合并 K 线，
    既允许一段长行情中出现多个同类型点，又过滤重叠中枢产生的紧邻重复点。
    """
    pts: list[dict] = []
    last_pos: dict[str, int] = {}

    def add(kind: str, date: str, price: float, note: str, pos: int) -> None:
        if kind in last_pos and pos - last_pos[kind] < min_same_kind_gap:
            return
        last_pos[kind] = pos
        pts.append({"kind": kind, "date": date, "price": round(price, 2), "note": note})

    for z in zhongshu:
        start_idx = next((i for i, b in enumerate(bis) if b["pos"] == z["start_pos"]), None)
        end_idx = next((i for i, b in enumerate(bis) if b["pos"] == z["end_pos"]), None)
        if start_idx is None or end_idx is None or start_idx < 1 or end_idx >= len(bis) - 1:
            continue
        enter_bi = bis[start_idx - 1]
        leave_bi = bis[end_idx + 1]
        # 进入段 = 以 start_idx 为终点的笔；离开段 = 以 end_idx 为起点的笔
        enter_force = abs(bis[start_idx]["price"] - bis[start_idx - 1]["price"])
        leave_force = abs(bis[end_idx + 1]["price"] - bis[end_idx]["price"])
        leave_down = leave_bi["price"] < bis[end_idx]["price"]

        # 一买：向下离开中枢、跌破 ZD、力度弱于进入段（背驰）
        if leave_down and leave_bi["price"] < z["zd"] and leave_force < enter_force:
            add("buy1", leave_bi["date"], leave_bi["price"], "下跌背驰，中枢跌破后的一买", leave_bi["pos"])
            # 二买：一买之后的回调低点（高于一买价）
            for b in bis[end_idx + 2 :]:
                if b["kind"] == "bottom" and b["price"] > leave_bi["price"]:
                    add("buy2", b["date"], b["price"], "一买后回调不创新低（二买）", b["pos"])
                    break
        # 一卖：向上离开中枢、突破 ZG、力度弱于进入段
        elif not leave_down and leave_bi["price"] > z["zg"] and leave_force < enter_force:
            add("sell1", leave_bi["date"], leave_bi["price"], "上涨背驰，中枢突破后的一卖", leave_bi["pos"])
            for b in bis[end_idx + 2 :]:
                if b["kind"] == "top" and b["price"] < leave_bi["price"]:
                    add("sell2", b["date"], b["price"], "一卖后反弹不创新高（二卖）", b["pos"])
                    break

        # 三买：向上离开中枢后，回抽不破 ZG
        if leave_bi["price"] > z["zg"] and not leave_down:
            for b in bis[end_idx + 2 :]:
                if b["kind"] == "bottom" and b["price"] > z["zg"]:
                    add("buy3", b["date"], b["price"], "离开中枢后回抽不破 ZG（三买）", b["pos"])
                    break
        # 三卖：向下离开中枢后，回抽不破 ZD
        if leave_bi["price"] < z["zd"] and leave_down:
            for b in bis[end_idx + 2 :]:
                if b["kind"] == "top" and b["price"] < z["zd"]:
                    add("sell3", b["date"], b["price"], "离开中枢后回抽不破 ZD（三卖）", b["pos"])
                    break
    return pts


def zhongshu_break_warns(bars: list[dict], zhongshu: list[dict], min_same_kind_gap: int = 20) -> list[dict]:
    """中枢破坏预警（三卖预警）：向下离开后收盘跌破中枢上沿 ZG。

    严格三卖需要“离开中枢后回抽不破 ZD”，回抽笔确认通常滞后（主升浪后
    往往要等完整回抽笔形成）。这里在收盘价跌破 ZG 时先给 sell3_warn，
    比等回抽笔确认提前数根 K 线，供做空/减仓侧预警。

    bars 元素需含 datetime/close；zhongshu 需含 end_date/zg。
    """
    candidates: list[dict] = []
    for z in sorted(zhongshu, key=lambda x: x["start_pos"]):
        for i, b in enumerate(bars):
            if str(b["datetime"]) <= str(z["end_date"]):
                continue
            try:
                close = float(b["close"])
            except (TypeError, ValueError):
                continue
            if close < z["zg"]:
                candidates.append(
                    {
                        "kind": "sell3_warn",
                        "date": str(b["datetime"]),
                        "price": round(close, 2),
                        "note": f"收盘跌破中枢上沿 ZG={z['zg']:.2f}，三卖预警（等回抽不破 ZD={z['zd']:.2f} 确认三卖）",
                        "pos": i,
                    }
                )
                break
    # 不同中枢的首次跌破日可能不按时间顺序，先按 bar 位置排序再统一做最小间隔过滤
    candidates.sort(key=lambda x: x["pos"])
    warns: list[dict] = []
    last_i = -10**9
    for c in candidates:
        if c["pos"] - last_i >= min_same_kind_gap:
            warns.append(c)
            last_i = c["pos"]
    return warns


def analyze_chan(df: pd.DataFrame, min_gap: int = 4, min_same_kind_gap: int = 20, warn_gap: int = 30) -> dict:
    """对 OHLC DataFrame 做缠论分析，返回 bars/points/zhongshu/bi。"""
    df = df.sort_values("datetime").reset_index(drop=True)
    merged = merge_contained(df)
    fractals = find_fractals(merged)
    bis = find_bi(fractals, min_gap=min_gap)
    zhongshu = find_zhongshu(bis)
    points = buy_sell_points(bis, zhongshu, min_same_kind_gap=min_same_kind_gap)
    bars = [
        {
            "datetime": _dt_key(r.datetime),
            "open": float(r.open),
            "high": float(r.high),
            "low": float(r.low),
            "close": float(r.close),
            "volume": float(getattr(r, "volume", 0) or 0),
        }
        for r in df.itertuples()
    ]
    points.extend(zhongshu_break_warns(bars, zhongshu, min_same_kind_gap=warn_gap))
    return {
        "bars": bars,
        "points": points,
        "zhongshu": zhongshu,
        "bi": bis,
        "params": {"min_gap": min_gap, "min_same_kind_gap": min_same_kind_gap, "warn_gap": warn_gap},
    }
