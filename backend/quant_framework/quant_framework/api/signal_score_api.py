"""新手综合信号量 API：K 线图顶部一个大数字，替代看一堆指标。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

import pandas as pd

from quant_framework.signal_score import compute_signal_score

router = APIRouter(prefix="/api/quant/signal-score", tags=["quant-signal-score"])


@router.get("")
def signal_score(
    code: str = Query(...),
    category: int = Query(4),
    offset: int = Query(300, ge=60, le=800),
    window: int | None = Query(None, ge=60, le=800),
    trailing_drawdown: float = Query(0.08, ge=0.03, le=0.2),
    exclude_last: bool = Query(False),
):
    """返回 -100~+100 综合信号量 + 档位 + 分项原因 + 移动止盈线 + 新高缩量事件。"""
    import astock as astock_mod

    try:
        rows = astock_mod.kline(code, category=category, offset=offset)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"K线获取失败：{e}") from e
    if not rows:
        raise HTTPException(status_code=404, detail="K线数据为空")
    df = pd.DataFrame(rows)
    df["datetime"] = pd.to_datetime(df["datetime"])
    if window is not None:
        df = df.tail(window)
    analyze_df = df.iloc[:-1] if exclude_last else df
    result = compute_signal_score(analyze_df, trailing_drawdown=trailing_drawdown)
    result["exclude_last"] = exclude_last
    result["data_date"] = str(analyze_df["datetime"].iloc[-1].date()) if len(analyze_df) else None
    return result
