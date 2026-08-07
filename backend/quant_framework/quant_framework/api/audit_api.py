"""对抗审计 API：检查清单 + 审计 prompt 生成。"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from quant_framework.audit import AUDIT_CHECKLIST, AdversarialAudit

router = APIRouter(prefix="/api/quant/audit", tags=["quant-audit"])


class AuditPromptRequest(BaseModel):
    strategy_code: str = ""
    data_spec: str = ""
    backtest_result: str = ""


@router.get("/checklist")
def get_checklist():
    return {"items": AUDIT_CHECKLIST}


@router.post("/prompt")
def build_prompt(req: AuditPromptRequest):
    audit = AdversarialAudit(
        strategy_code=req.strategy_code,
        data_spec=req.data_spec,
        backtest_result=req.backtest_result,
    )
    return {"prompt": audit.build_prompt()}
