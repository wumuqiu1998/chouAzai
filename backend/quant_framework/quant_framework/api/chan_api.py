"""缠论分析 API：给 K 线图注入分型/笔/中枢/三类买卖点。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

import pandas as pd

from quant_framework.chan import analyze_chan

router = APIRouter(prefix="/api/quant/chan", tags=["quant-chan"])


@router.get("/analyze")
def chan_analyze(
    code: str = Query(...),
    category: int = Query(4),
    offset: int = Query(250, ge=60, le=800),
    window: int | None = Query(None, ge=20, le=800),
    warn_gap: int = Query(30, ge=1, le=120),
    exclude_last: bool = Query(False),
):
    """返回缠论结构：bars + points(买卖点) + zhongshu(中枢) + bi(笔)。

    window：只分析最近 N 根 K 线（缩放跟随窗口用，K 线本体不变）；
    exclude_last=True 用于盘中实时：最后一根 K 线尚未收盘，不参与结构确认，
    避免指标引用未完成 K 线（保守口径，只用已收盘数据）。
    """
    import astock as astock_mod

    try:
        rows = astock_mod.kline(code, category=category, offset=offset)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"K线获取失败：{e}")
    if not rows:
        raise HTTPException(status_code=404, detail="K线数据为空")
    df = pd.DataFrame(rows)
    df["datetime"] = pd.to_datetime(df["datetime"])
    if window is not None:
        df = df.tail(window)
    analyze_df = df.iloc[:-1] if exclude_last else df
    result = analyze_chan(analyze_df, warn_gap=warn_gap)
    result["exclude_last"] = exclude_last
    return result
