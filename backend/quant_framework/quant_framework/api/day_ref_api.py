"""分时图“昨日参考位”API：给日内做T提供昨日关键价位。

返回内容（全部截至“分时对应的前一交易日”收盘，无未来函数）：
- ref_bar：昨日开高低收；
- chan_points：截至昨日的最近缠论买卖点（B1/B2/B3/S1/S2/S3/SELL3_WARN）；
- atr：昨日 ATR 通道（MA20 ± 2.5×ATR）；
- zhongshu：最近 1~2 个中枢 [ZD, ZG]。

“昨日”判定：用分时接口的 prev_close 在日K序列中反查，
盘中/盘后都能正确定位到分时对应的前一交易日。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

import pandas as pd

from quant_framework.atr import compute_atr
from quant_framework.chan import analyze_chan

router = APIRouter(prefix="/api/quant/day-ref", tags=["quant-day-ref"])


@router.get("")
def day_ref(code: str = Query(...), offset: int = Query(120, ge=60, le=400)):
    import astock as astock_mod

    try:
        rows = astock_mod.kline(code, category=4, offset=offset)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"日K获取失败：{e}") from e
    if not rows:
        raise HTTPException(status_code=404, detail="K线数据为空")
    df = pd.DataFrame(rows)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)

    try:
        minute = astock_mod.minute_line(code)
        prev = float(minute.get("prev_close") or 0)
    except Exception:  # noqa: BLE001
        prev = 0.0

    # 用分时昨收反查日K：第一个（从后往前）收盘≈昨收且不是最后一根的即为“昨日”
    ref_idx = None
    if prev > 0:
        for i in range(len(df) - 1, -1, -1):
            if abs(float(df["close"].iloc[i]) - prev) < 1e-6 and i < len(df) - 1:
                ref_idx = i
                break
    if ref_idx is None:
        ref_idx = max(0, len(df) - 2)

    ref_date = str(df["datetime"].iloc[ref_idx].date())
    seg = df.iloc[: ref_idx + 1]
    chan = analyze_chan(seg)
    points = [
        {"kind": p["kind"], "date": p["date"], "price": round(p["price"], 2), "note": p["note"]}
        for p in chan["points"]
        if str(p["date"]) <= ref_date
    ][-12:]
    zhongshu = [z for z in chan["zhongshu"] if str(z["end_date"]) <= ref_date][-2:]
    atr = compute_atr(seg)
    abar = atr["bars"][-1] if atr["bars"] else {}
    rb = df.iloc[ref_idx]
    return {
        "ref_date": ref_date,
        "ref_bar": {
            "open": round(float(rb["open"]), 2),
            "high": round(float(rb["high"]), 2),
            "low": round(float(rb["low"]), 2),
            "close": round(float(rb["close"]), 2),
            "volume": float(rb.get("volume") or 0),
        },
        "prev_close": prev,
        "chan_points": points,
        "atr": {
            "mid": abar.get("mid"),
            "upper": abar.get("upper"),
            "lower": abar.get("lower"),
        },
        "zhongshu": zhongshu,
    }
