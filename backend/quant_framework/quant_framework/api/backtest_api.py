"""回测 API：运行固定底座回测、消融实验与信号诊断（合成数据）。"""

from __future__ import annotations

import math
from dataclasses import replace

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import numpy as np

from quant_framework import config as cfgmod
from quant_framework.backtest_core import AblationRunner, FixedBacktestEngine
from quant_framework.data_source import SyntheticDataSource
from quant_framework.diagnostics import factor_decay, grouped_returns, ic_series, monotonicity_check

router = APIRouter(prefix="/api/quant/backtest", tags=["quant-backtest"])


def _clean(value):
    """递归清洗响应：NaN/Inf -> None，numpy 标量 -> 原生 Python 类型。"""
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, float):
        return None if not math.isfinite(value) else value
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


class BacktestRequest(BaseModel):
    n_symbols: int = Field(60, ge=5, le=200)
    n_days: int = Field(400, ge=50, le=2000)
    seed: int = 42
    window: int = Field(20, ge=2, le=120)
    top_n: int | None = Field(None, ge=1, le=50)


@router.post("/run")
def run_backtest(req: BacktestRequest):
    try:
        base = cfgmod.load_backtest_config()
        if req.top_n:
            base = replace(base, top_n=req.top_n)
        engine = FixedBacktestEngine(base)

        ds = SyntheticDataSource(n_symbols=req.n_symbols, n_days=req.n_days, seed=req.seed)
        panel = ds.load_panel()
        factor = ds.momentum_factor(panel, window=req.window)

        run = engine.run(factor, panel["open"], panel["close"])
        vol = panel["volume"].rolling(5).mean()
        liquidity_scalar = float(vol.mean(axis=1).mean())  # pandas mean 默认跳过 NaN
        liquidity_mod = factor * (vol / liquidity_scalar) if liquidity_scalar else factor
        ablation = AblationRunner(engine).run(
            baseline=factor,
            modules={"liquidity": liquidity_mod},
            open_price=panel["open"],
            close_price=panel["close"],
        )

        # 信号诊断
        fwd5 = (panel["close"].shift(-5) / panel["close"] - 1.0).stack().dropna()
        fstack = factor.stack().dropna()
        groups = grouped_returns(fstack, fwd5, n_groups=10)
        mono = monotonicity_check(groups)
        decay = factor_decay(fstack, panel["close"])

        payload = {
            "request": req.model_dump(),
            "metrics": run.metrics.to_dict(),
            "equity_curve": [[str(d.date()), round(float(v), 2)] for d, v in run.equity_curve.items()],
            "ablation": [
                {"name": s.name, **s.metrics.to_dict()} for s in ablation
            ],
            "diagnostics": {
                "monotonicity": mono,
                "decay": {str(k): round(float(v), 4) for k, v in decay.items()},
                "rank_ic_mean": round(float(ic_series(fstack, fwd5).mean()), 4),
            },
            "trades": run.trades.head(50).to_dict(orient="records"),
        }
        return _clean(payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"回测失败: {e}")
