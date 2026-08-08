"""缠论分析 API：给 K 线图注入分型/笔/中枢/三类买卖点。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

import pandas as pd

from quant_framework.chan import analyze_chan

router = APIRouter(prefix="/api/quant/chan", tags=["quant-chan"])


@router.get("/analyze")
def chan_analyze(code: str = Query(...), category: int = Query(4), offset: int = Query(250, ge=60, le=800)):
    """返回缠论结构：bars + points(买卖点) + zhongshu(中枢) + bi(笔)。"""
    import astock as astock_mod

    try:
        rows = astock_mod.kline(code, category=category, offset=offset)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"K线获取失败：{e}")
    if not rows:
        raise HTTPException(status_code=404, detail="K线数据为空")
    df = pd.DataFrame(rows)
    df["datetime"] = pd.to_datetime(df["datetime"])
    return analyze_chan(df)
