"""回测 API：运行固定底座回测、消融实验与信号诊断（合成 / 真实 A 股数据）。"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import numpy as np
import pandas as pd

from quant_framework import config as cfgmod
from quant_framework.backtest_core import AblationRunner, FixedBacktestEngine
from quant_framework.data_source import SyntheticDataSource
from quant_framework.diagnostics import factor_decay, grouped_returns, ic_series, monotonicity_check
from quant_framework.experiments import ExperimentLog
from quant_framework.factor_lib import FACTORS, compute as compute_factor
from quant_framework.models import ExperimentRecord

router = APIRouter(prefix="/api/quant/backtest", tags=["quant-backtest"])

DEFAULT_REAL_CODES = "600519,000858,300750,601318,600036,000333,002594,688981,600887,000001"


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
    source: str = "synthetic"          # synthetic / real
    codes: str = ""                    # real 用：逗号分隔 6 位 A 股代码
    factor: str = "momentum"
    hypothesis: str = ""               # 实验假设（用于实验日志）
    window: int = Field(20, ge=2, le=120)
    n_symbols: int = Field(60, ge=5, le=200)
    n_days: int = Field(400, ge=50, le=2000)
    seed: int = 42
    top_n: int | None = Field(None, ge=1, le=50)


def _load_real_panel(codes: list[str], offset: int) -> dict:
    """用 Vibe 后端的 /api/kline 数据源（腾讯优先）拉取真实 A 股日线面板。"""
    import astock as astock_mod

    frames: dict[str, pd.DataFrame] = {}
    for c in codes:
        try:
            rows = astock_mod.kline(c, category=4, offset=offset)
        except Exception:  # noqa: BLE001 - 单只失败跳过
            continue
        if not rows:
            continue
        df = pd.DataFrame(rows)
        if "datetime" not in df or "close" not in df:
            continue
        df["date"] = pd.to_datetime(df["datetime"])
        df = df.set_index("date").sort_index()
        frames[c] = df
    if not frames:
        raise ValueError("真实行情拉取失败：请检查代码是否正确或行情源是否可用")

    common = None
    for df in frames.values():
        idx = df.index
        common = idx if common is None else common.intersection(idx)
    common = common.sort_values()
    close = pd.DataFrame({c: df.loc[common, "close"] for c, df in frames.items()}).dropna(how="all")
    open_ = pd.DataFrame({c: df.loc[common, "open"] for c, df in frames.items()}).reindex(close.index)
    vol = pd.DataFrame({c: df.loc[common, "volume"] for c, df in frames.items()}).reindex(close.index)
    close = close.dropna(axis=1, how="any")
    if close.shape[1] < 5:
        raise ValueError(f"有效股票不足 5 只（当前 {close.shape[1]}），请调整代码列表")
    open_ = open_[close.columns].reindex(close.index)
    vol = vol[close.columns].reindex(close.index).fillna(0)
    return {"open": open_, "close": close, "volume": vol}


@router.post("/run")
def run_backtest(req: BacktestRequest):
    try:
        base = cfgmod.load_backtest_config()
        if req.top_n:
            base = replace(base, top_n=req.top_n)
        engine = FixedBacktestEngine(base)

        if req.source == "real":
            codes = [c.strip() for c in req.codes.split(",") if c.strip()] or DEFAULT_REAL_CODES.split(",")
            panel = _load_real_panel(codes, offset=req.n_days + req.window + 20)
        else:
            ds = SyntheticDataSource(n_symbols=req.n_symbols, n_days=req.n_days, seed=req.seed)
            panel = ds.load_panel()
        factor_names = [f.strip() for f in req.factor.split(",") if f.strip()]
        unknown = [n for n in factor_names if n not in FACTORS]
        if unknown:
            raise HTTPException(status_code=422, detail=f"未知因子：{unknown}，可用：{sorted(FACTORS)}")
        if len(factor_names) == 1:
            factor = compute_factor(factor_names[0], panel["close"], volume=panel.get("volume"), window=req.window)
            factor_label = factor_names[0]
        else:
            # 多因子组合：各因子做截面百分位排名后等权平均
            vals = [
                compute_factor(n, panel["close"], volume=panel.get("volume"), window=req.window)
                for n in factor_names
            ]
            factor = sum(v.rank(axis=1, pct=True) for v in vals) / len(vals)
            factor_label = "composite(" + ",".join(factor_names) + ")"

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
        groups_list = (
            [
                {"group": int(i), "mean_ret": round(float(r["mean_ret"]), 4), "count": int(r["count"])}
                for i, r in groups.iterrows()
            ]
            if not groups.empty
            else []
        )
        decay = factor_decay(fstack, panel["close"])
        ics = ic_series(fstack, fwd5)
        ic_by_date = [[str(d.date()), round(float(v), 4)] for d, v in ics.items() if v == v]
        dates = pd.DatetimeIndex(panel["close"].index)

        payload = {
            "request": req.model_dump(),
            "factor": {
                "name": factor_label,
                "window": req.window,
                "available": sorted(FACTORS),
                "factors": factor_names if len(factor_names) > 1 else None,
            },
            "universe": {
                "source": req.source,
                "n_symbols": int(panel["close"].shape[1]),
                "start": str(dates[0].date()),
                "end": str(dates[-1].date()),
            },
            "metrics": run.metrics.to_dict(),
            "equity_curve": [[str(d.date()), round(float(v), 2)] for d, v in run.equity_curve.items()],
            "ablation": [
                {"name": s.name, **s.metrics.to_dict()} for s in ablation
            ],
            "diagnostics": {
                "monotonicity": mono,
                "decay": {str(k): round(float(v), 4) for k, v in decay.items()},
                "rank_ic_mean": round(float(ic_series(fstack, fwd5).mean()), 4),
                "ic_by_date": ic_by_date,
                "groups": groups_list,
            },
            "trades": run.trades.head(50).to_dict(orient="records"),
        }
        # 实验协议自动判定：通过/失败写进实验日志
        protocol = cfgmod.load_experiment_protocol()
        criteria = protocol.pass_criteria or {}
        unmet: list[str] = []
        m = run.metrics
        ric = payload["diagnostics"]["rank_ic_mean"]
        if criteria.get("oos_rank_ic_positive") and not (ric is not None and ric > 0):
            unmet.append("样本外 RankIC 未保持为正")
        if criteria.get("cost_after_return_positive") and not (m.annual_return is not None and m.annual_return > 0):
            unmet.append("成本后年化收益非正")
        yearly = m.yearly or {}
        pos_ratio = criteria.get("yearly_positive_ratio", 0)
        if pos_ratio and yearly:
            ratio = sum(1 for v in yearly.values() if v and v > 0) / len(yearly)
            if ratio < pos_ratio:
                unmet.append(f"年度正收益占比 {ratio:.2f} < {pos_ratio}")
        mdd_upper = criteria.get("max_drawdown_upper")
        if mdd_upper is not None and (m.max_drawdown is None or m.max_drawdown < mdd_upper):
            unmet.append(f"最大回撤 {m.max_drawdown:.2%} 超过上限 {mdd_upper:.2%}")
        passed = not unmet
        log = ExperimentLog(cfgmod.PROJECT_ROOT / "data" / "experiments.csv")
        rec = ExperimentRecord(
            experiment_id=f"EXP-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            hypothesis=req.hypothesis or "未命名实验",
            unique_change=f"source={req.source},factor={req.factor},window={req.window},top_n={req.top_n}",
            expected="按实验协议自动判定",
            dev_result=f"年化 {m.annual_return:.2%} / 回撤 {m.max_drawdown:.2%}",
            val_result=f"RankIC {ric}",
            cost_result=f"成本后年化 {m.annual_return:.2%}",
            passed=passed,
            failure_reason="；".join(unmet) if unmet else "",
            code_version="quant-api",
        )
        log.append(rec)
        payload["experiment"] = {"log_id": rec.experiment_id, "passed": passed, "unmet": unmet}
        return _clean(payload)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"回测失败: {e}")
