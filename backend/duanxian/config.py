"""LLM 配置 —— 复盘在后端跑，按优先级选后端凭据（不读浏览器 localStorage）。

优先级：
  1. VIBE_LLM_CLI=claude|codex|…  → 本机已登录的 CLI 订阅（免 API key）
  2. OPENAI_API_KEY 或 VR_LLM_API_KEY → 任意 OpenAI 兼容 API
  3. MIMO_API_KEY 或 ~/.config/mimo/mimo.env → MiMo
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values
from langchain_openai import ChatOpenAI

from . import cli_llm
from .llm_errors import LlmConfigError

_MIMO_ENV = Path.home() / ".config" / "mimo" / "mimo.env"

_CREDS: dict[str, str] | None = None

QUICK_MODEL = "mimo-v2.5"

# (api_key_env, base_url_env, model_env, model_deep_env)
_API_PROFILES: tuple[tuple[str, str, str, str], ...] = (
    ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL", "OPENAI_MODEL_DEEP"),
    ("VR_LLM_API_KEY", "VR_LLM_BASE_URL", "VR_LLM_MODEL", "VR_LLM_MODEL_DEEP"),
    ("MIMO_API_KEY", "MIMO_BASE_URL", "MIMO_MODEL", "MIMO_MODEL_DEEP"),
)

_SETUP_HINT = (
    "短线复盘需要 LLM 凭据。请在「接入 AI」页保存一次（会同步到本机 ~/.vibe-research/），"
    "或在 backend/.env 配置 VIBE_LLM_CLI / OPENAI_API_KEY 后重启后端。"
)


def _api_profile() -> dict[str, str] | None:
    """从环境变量解析一组 OpenAI 兼容凭据。"""
    for key_k, url_k, model_k, deep_k in _API_PROFILES:
        api_key = os.environ.get(key_k, "").strip()
        if not api_key:
            continue
        base = os.environ.get(url_k, "").strip()
        if key_k == "MIMO_API_KEY":
            base = base or "https://token-plan-cn.xiaomimimo.com/v1"
        else:
            base = base or "https://api.openai.com/v1"
        quick = os.environ.get(model_k, "").strip() or (
            "mimo-v2.5" if key_k == "MIMO_API_KEY" else "gpt-4o-mini"
        )
        deep = os.environ.get(deep_k, "").strip() or os.environ.get(model_k, "").strip() or (
            "mimo-v2.5-pro" if key_k == "MIMO_API_KEY" else quick
        )
        return {"api_key": api_key, "base_url": base, "quick": quick, "deep": deep}
    return None


def _load_mimo_file() -> dict[str, str]:
    if not _MIMO_ENV.exists():
        return {}
    return {k: v for k, v in dotenv_values(_MIMO_ENV).items() if v}


def _apply_vr_saved() -> bool:
    """读 ~/.vibe-research/llm_config.json（网页「接入 AI」同步写入）。"""
    try:
        import llm_settings
    except ImportError:
        return False
    cfg = llm_settings.load_config()
    if not cfg:
        return False
    provider = str(cfg.get("provider") or "")
    if provider.startswith("cli-"):
        os.environ.setdefault("VIBE_LLM_CLI", provider[4:])
        return True
    api_key = str(cfg.get("apiKey") or "").strip()
    if api_key:
        global _CREDS
        base = str(cfg.get("baseURL") or "").strip() or "https://api.openai.com/v1"
        model = str(cfg.get("model") or "").strip() or "gpt-4o-mini"
        _CREDS = {"api_key": api_key, "base_url": base, "quick": model, "deep": model}
        return True
    return False


def _ensure_api_loaded() -> None:
    """解析 API 凭据（MiMo 文件作 MIMO_* 的补充来源）。"""
    global _CREDS
    if _CREDS is not None:
        return

    if _apply_vr_saved():
        return

    prof = _api_profile()
    if prof:
        _CREDS = prof
        return

    # MiMo 文件：只在环境变量里还没有 MIMO_API_KEY 时读
    if not os.environ.get("MIMO_API_KEY", "").strip():
        file_creds = _load_mimo_file()
        if file_creds.get("MIMO_API_KEY"):
            for k, v in file_creds.items():
                os.environ.setdefault(k, v)
            prof = _api_profile()
            if prof:
                _CREDS = prof
                return

    raise LlmConfigError(_SETUP_HINT)


def make_llm(deep: bool = False, temperature: float = 0.6):
    """构造复盘用的 LLM"""
    if not cli_llm.wanted_kind():
        _apply_vr_saved()
    kind = cli_llm.wanted_kind()
    if kind:
        return cli_llm.make_cli_llm(deep=deep)

    _ensure_api_loaded()
    assert _CREDS is not None
    model = _CREDS["deep"] if deep else _CREDS["quick"]
    return ChatOpenAI(
        model=model,
        base_url=_CREDS["base_url"],
        api_key=_CREDS["api_key"],
        temperature=temperature,
        timeout=180,
        max_retries=2,
    )
