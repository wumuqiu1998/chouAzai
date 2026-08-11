"""分时通俗信号 API：让分时图也显示“顶/底/B/S/扫/突/破/变/积/派”。

两类信号：
- intraday：把当日分时 points 聚合成 1 分钟 K 线（单点 OHLC），实时计算
  ATR 顶/底、缠论买卖点、SMC 扫荡/结构突破、威科夫 Spring/Upthrust；
- recent：截至“分时对应的前一交易日”的日K通俗信号（积/派/扫/突/破/变），
  作为水平参考位显示在分时图上（缠论 B/S 已由 day-ref 提供，不重复）。

无未来函数：所有模块只用已形成的数据；分时单点 OHLC 无影线，
Spring/Upthrust 需要影线，分钟级通常不触发（由 recent 日K信号补充）。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

import pandas as pd

from quant_framework.atr import compute_atr
from quant_framework.chan import analyze_chan_locked
from quant_framework.smc import analyze_smc
from quant_framework.wyckoff import analyze_wyckoff

router = APIRouter(prefix="/api/quant/minute-signals", tags=["quant-minute-signals"])

_CHAN_LABEL = {
    "buy1": "B1", "buy2": "B2", "buy3": "B3",
    "sell1": "S1", "sell2": "S2", "sell3": "S3", "sell3_warn": "警",
}


def _time_of(date: str) -> str:
    """'2026-01-01 09:35' -> '0935'（与分时 points.time 一致）。"""
    p = str(date).split(" ")[-1].replace(":", "")
    return p[:4] if len(p) >= 4 else p


def _minute_df(points: list[dict]) -> pd.DataFrame:
    rows = []
    for p in points:
        t = str(p.get("time") or "")
        hhmm = f"{t[:2]}:{t[2:]}" if len(t) == 4 and t.isdigit() else t
        price = float(p.get("price") or 0)
        rows.append(
            {
                "datetime": f"2026-01-01 {hhmm}",
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": float(p.get("volume") or 0),
            }
        )
    df = pd.DataFrame(rows)
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df.sort_values("datetime").reset_index(drop=True)


def _intraday_signals(df: pd.DataFrame) -> list[dict]:
    out: list[dict] = []
    for s in compute_atr(df)["signals"]:
        if s["kind"] == "top":
            out.append({"time": _time_of(s["date"]), "label": "顶", "kind": "atr_top", "price": round(s["price"], 2), "note": s["note"]})
        elif s["kind"] == "bottom":
            out.append({"time": _time_of(s["date"]), "label": "底", "kind": "atr_bottom", "price": round(s["price"], 2), "note": s["note"]})
    for p in analyze_chan_locked(df)["points"]:
        label = _CHAN_LABEL.get(p["kind"])
        if label:
            out.append({"time": _time_of(p["date"]), "label": label, "kind": p["kind"], "price": round(p["price"], 2), "note": p["note"]})
    smc = analyze_smc(df)
    for s in smc.get("sweeps", []) or []:
        out.append({"time": _time_of(s["date"]), "label": "扫", "kind": "sweep", "price": round(s["price"], 2), "note": s["note"]})
    st = smc.get("structure") or {}
    bos = st.get("last_bos")
    if bos:
        out.append(
            {
                "time": _time_of(bos["date"]),
                "label": "突" if bos["kind"] == "bullish" else "破",
                "kind": "bos",
                "price": round(bos["price"], 2),
                "note": bos["note"],
            }
        )
    choch = st.get("last_choch")
    if choch:
        out.append({"time": _time_of(choch["date"]), "label": "变", "kind": "choch", "price": round(choch["price"], 2), "note": choch["note"]})
    for s in (analyze_wyckoff(df).get("signals") or []):
        if s["kind"] == "spring":
            out.append({"time": _time_of(s["date"]), "label": "积", "kind": "spring", "price": round(s["price"], 2), "note": s["note"]})
        elif s["kind"] == "upthrust":
            out.append({"time": _time_of(s["date"]), "label": "派", "kind": "upthrust", "price": round(s["price"], 2), "note": s["note"]})
    # 去重（同时间+同标签），按时间排序
    seen: set[tuple[str, str]] = set()
    dedup = []
    for x in sorted(out, key=lambda v: v["time"]):
        key = (x["time"], x["label"])
        if key in seen:
            continue
        seen.add(key)
        dedup.append(x)
    return dedup


def _recent_daily_signals(astock_mod, code: str) -> list[dict]:
    try:
        rows = astock_mod.kline(code, category=4, offset=120)
    except Exception:  # noqa: BLE001
        return []
    if not rows:
        return []
    df = pd.DataFrame(rows)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)
    try:
        prev = float(astock_mod.minute_line(code).get("prev_close") or 0)
    except Exception:  # noqa: BLE001
        prev = 0.0
    ref_idx = None
    if prev > 0:
        for i in range(len(df) - 1, -1, -1):
            if abs(float(df["close"].iloc[i]) - prev) < 1e-6 and i < len(df) - 1:
                ref_idx = i
                break
    if ref_idx is None:
        ref_idx = max(0, len(df) - 2)
    seg = df.iloc[: ref_idx + 1]
    ref_date = str(df["datetime"].iloc[ref_idx].date())

    out: list[dict] = []
    for s in (analyze_wyckoff(seg).get("signals") or []):
        if str(s["date"]) <= ref_date:
            out.append({"date": str(s["date"]), "price": round(s["price"], 2), "label": "积" if s["kind"] == "spring" else "派", "kind": s["kind"], "note": s["note"]})
    smc = analyze_smc(seg)
    for s in (smc.get("sweeps") or []):
        if str(s["date"]) <= ref_date:
            out.append({"date": str(s["date"]), "price": round(s["price"], 2), "label": "扫", "kind": "sweep", "note": s["note"]})
    st = smc.get("structure") or {}
    for key, label in (("last_bos", None), ("last_choch", "变")):
        item = st.get(key)
        if not item or str(item["date"]) > ref_date:
            continue
        if key == "last_bos":
            label = "突" if item["kind"] == "bullish" else "破"
        out.append({"date": str(item["date"]), "price": round(item["price"], 2), "label": label, "kind": key, "note": item["note"]})
    out.sort(key=lambda x: x["date"])
    return out[-8:]


@router.get("")
def minute_signals(code: str = Query(...)):
    import astock as astock_mod

    try:
        minute = astock_mod.minute_line(code)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"分时数据获取失败：{e}") from e
    points = minute.get("points") or []
    if len(points) < 30:
        return {"intraday": [], "recent": []}
    df = _minute_df(points)
    return {
        "intraday": _intraday_signals(df),
        "recent": _recent_daily_signals(astock_mod, code),
    }
