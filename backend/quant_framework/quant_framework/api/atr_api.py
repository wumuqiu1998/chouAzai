"""ATR 通道 API：给 K 线图提供超涨/超跌与顶底信号。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

import pandas as pd

from quant_framework.atr import atr_signal_stats, compute_atr

router = APIRouter(prefix="/api/quant/atr", tags=["quant-atr"])


@router.get("/analyze")
def atr_analyze(
    code: str = Query(...),
    category: int = Query(4),
    offset: int = Query(250, ge=60, le=800),
    period: int = Query(14, ge=2, le=60),
    mult: float = Query(2.5, ge=0.5, le=6.0),
    ma_period: int = Query(20, ge=5, le=120),
    exclude_last: bool = Query(False),
):
    """返回 ATR 通道（bars 与 K 线对齐）+ 超涨/超跌/顶底信号。

    exclude_last=True 用于盘中实时：最后一根未收盘 K 线不参与计算，
    bars 末尾补一条空值占位（unclosed=True），保持与 K 线索引对齐。
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
    analyze_df = df.iloc[:-1] if exclude_last else df
    result = compute_atr(analyze_df, period=period, mult=mult, ma_period=ma_period)
    if exclude_last:
        from quant_framework.atr import _bar_key

        last_dt = _bar_key(df["datetime"].iloc[-1])
        result["bars"].append(
            {"date": last_dt, "mid": None, "upper": None, "lower": None, "atr": None, "unclosed": True}
        )
    result["exclude_last"] = exclude_last
    return result


@router.get("/stats")
def atr_stats(
    code: str = Query(...),
    category: int = Query(4),
    offset: int = Query(400, ge=60, le=800),
    period: int = Query(14, ge=2, le=60),
    mult: float = Query(2.5, ge=0.5, le=6.0),
    ma_period: int = Query(20, ge=5, le=120),
    horizon: int = Query(5, ge=1, le=20),
):
    """顶/底信号样本外统计：信号后 horizon 根 K 线涨跌概率与平均收益。"""
    import astock as astock_mod

    try:
        rows = astock_mod.kline(code, category=category, offset=offset)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"K线获取失败：{e}")
    if not rows:
        raise HTTPException(status_code=404, detail="K线数据为空")
    df = pd.DataFrame(rows)
    df["datetime"] = pd.to_datetime(df["datetime"])
    return atr_signal_stats(df, period=period, mult=mult, ma_period=ma_period, horizon=horizon)
