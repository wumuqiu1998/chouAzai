"""市场趋势 / 威科夫 / ICT-SMC API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

import pandas as pd

router = APIRouter(prefix="/api/quant/smc", tags=["quant-smc"])


def _load_df(code: str, category: int, offset: int) -> pd.DataFrame:
    import astock as astock_mod

    try:
        rows = astock_mod.kline(code, category=category, offset=offset)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"K线获取失败：{e}")
    if not rows:
        raise HTTPException(status_code=404, detail="K线数据为空")
    df = pd.DataFrame(rows)
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df


@router.get("/market-regime")
def market_regime(
    trend_period: int = Query(20, ge=5, le=60),
    slow_period: int = Query(60, ge=20, le=120),
    offset: int = Query(320, ge=120, le=800),
):
    """市场趋势分析：主要宽基指数状态聚合（道士理论 + 趋势跟踪）。"""
    from quant_framework.market_regime import analyze_market

    try:
        return analyze_market(
            trend_period=trend_period,
            slow_period=slow_period,
            offset=offset,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"市场趋势分析失败：{e}")


@router.get("/wyckoff")
def wyckoff(
    code: str = Query(...),
    category: int = Query(4),
    offset: int = Query(250, ge=60, le=800),
    exclude_last: bool = Query(False),
):
    """威科夫主力筹码阶段判断（吸筹/拉升/派发/下跌 + 主力成本区）。"""
    from quant_framework.wyckoff import analyze_wyckoff

    df = _load_df(code, category, offset)
    if exclude_last:
        df = df.iloc[:-1]
    try:
        return analyze_wyckoff(df)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"威科夫分析失败：{e}")


@router.get("/analyze")
def smc_analyze(
    code: str = Query(...),
    category: int = Query(4),
    offset: int = Query(250, ge=60, le=800),
    exclude_last: bool = Query(False),
):
    """ICT/SMC 结构标注：FVG / 订单块 / 流动性扫荡 / 结构突破。"""
    from quant_framework.smc import analyze_smc

    df = _load_df(code, category, offset)
    if exclude_last:
        df = df.iloc[:-1]
    try:
        return analyze_smc(df)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"ICT/SMC 分析失败：{e}")
