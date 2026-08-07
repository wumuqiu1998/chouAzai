"""FastAPI 入口：python -m quant_framework.api.server（默认 127.0.0.1:8920）。"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from quant_framework.api import audit_api, backtest_api, config_api, experiments_api

app = FastAPI(title="quant_framework", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(config_api.router)
app.include_router(backtest_api.router)
app.include_router(experiments_api.router)
app.include_router(audit_api.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "quant_framework"}


# 前端构建产物存在时由本服务托管
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=str(DIST), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("quant_framework.api.server:app", host="127.0.0.1", port=8920, reload=False)
