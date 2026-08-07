"""配置 API：GET/PUT 三份 YAML 配置与假设卡，保存时记录 diff 到实验日志。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from quant_framework import config as cfgmod
from quant_framework.experiments import ExperimentLog
from quant_framework.models import ExperimentRecord

router = APIRouter(prefix="/api/quant/config", tags=["quant-config"])


class SaveRequest(BaseModel):
    data: dict


def _registry():
    return {
        "backtest": {
            "load": cfgmod.load_backtest_config,
            "save": cfgmod.save_backtest_config,
            "from_dict": cfgmod.backtest_config_from_dict,
            "validate": lambda o: o.validate(),
        },
        "risk": {
            "load": cfgmod.load_risk_limits,
            "save": cfgmod.save_risk_limits,
            "from_dict": lambda d: cfgmod.RiskLimits(**d),
            "validate": lambda o: [],
        },
        "protocol": {
            "load": cfgmod.load_experiment_protocol,
            "save": cfgmod.save_experiment_protocol,
            "from_dict": lambda d: cfgmod.ExperimentProtocol(**d),
            "validate": lambda o: o.validate(),
        },
        "hypothesis": {
            "load": cfgmod.load_hypothesis_card,
            "save": cfgmod.save_hypothesis_card,
            "from_dict": lambda d: cfgmod.ResearchHypothesisCard.from_dict(d),
            "validate": lambda o: o.validate(),
        },
    }


def _default_log_path():
    return cfgmod.PROJECT_ROOT / "data" / "experiments.csv"


@router.get("/{name}")
def get_config(name: str):
    entry = _registry().get(name)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"未知配置: {name}")
    obj = entry["load"]()
    return {"name": name, "config": cfgmod._as_plain(obj)}


@router.put("/{name}")
def put_config(name: str, req: SaveRequest):
    entry = _registry().get(name)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"未知配置: {name}")
    old = entry["load"]()
    try:
        new = entry["from_dict"](req.data)
    except Exception as e:  # 字段缺失/类型错误
        raise HTTPException(status_code=422, detail=f"配置不合法: {e}")
    problems = entry["validate"](new)
    if problems:
        raise HTTPException(status_code=422, detail={"problems": problems})
    entry["save"](new)
    diff = cfgmod.config_diff(old, new)
    log = ExperimentLog(_default_log_path())
    rec = ExperimentRecord(
        experiment_id=f"CFG-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        hypothesis=f"配置变更:{name}",
        unique_change="; ".join(diff) if diff else "无参数变化",
        expected="配置保存",
        passed=True,
        code_version="config-api",
    )
    log.append(rec)
    return {"name": name, "config": cfgmod._as_plain(new), "diff": diff, "log_id": rec.experiment_id}
