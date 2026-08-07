"""实验日志 API。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from quant_framework import config as cfgmod
from quant_framework.experiments import ExperimentLog
from quant_framework.models import ExperimentRecord

router = APIRouter(prefix="/api/quant/experiments", tags=["quant-experiments"])


class ExperimentCreate(BaseModel):
    hypothesis: str = ""
    unique_change: str = ""
    expected: str = ""
    dev_result: str = ""
    val_result: str = ""
    cost_result: str = ""
    passed: bool = False
    failure_reason: str = ""
    code_version: str = ""


def _log() -> ExperimentLog:
    return ExperimentLog(cfgmod.PROJECT_ROOT / "data" / "experiments.csv")


@router.get("")
def list_experiments(limit: int = 200):
    log = _log()
    rows = [r.to_row() for r in log.all_rows()]
    return {
        "total": log.total_attempts(),
        "success_rate": round(log.success_rate(), 3),
        "rows": rows[-limit:],
    }


@router.post("")
def create_experiment(req: ExperimentCreate):
    log = _log()
    rec = ExperimentRecord(
        experiment_id=f"EXP-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        hypothesis=req.hypothesis,
        unique_change=req.unique_change,
        expected=req.expected,
        dev_result=req.dev_result,
        val_result=req.val_result,
        cost_result=req.cost_result,
        passed=req.passed,
        failure_reason=req.failure_reason,
        code_version=req.code_version,
    )
    log.append(rec)
    return {"experiment_id": rec.experiment_id}
