"""用户 LLM 配置 —— 存 ~/.vibe-research/llm_config.json（与持仓同级，不随端口/浏览器变）。

网页「接入 AI」保存时同步写这里；短线复盘后端也读这里。
不上传、不进仓库。API key 明文存本机，与浏览器 localStorage 同级风险。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

_CACHE_DIR = os.environ.get("VR_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".vibe-research")
_CONFIG_FILE = os.path.join(_CACHE_DIR, "llm_config.json")


def _ensure_dir() -> None:
    os.makedirs(_CACHE_DIR, exist_ok=True)


def load_config() -> dict | None:
    try:
        with open(_CONFIG_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) and data.get("model") else None
    except (OSError, json.JSONDecodeError):
        return None


def save_config(cfg: dict) -> dict:
    _ensure_dir()
    payload = {
        "provider": str(cfg.get("provider") or ""),
        "baseURL": str(cfg.get("baseURL") or ""),
        "apiKey": str(cfg.get("apiKey") or ""),
        "model": str(cfg.get("model") or ""),
    }
    if not payload["model"]:
        raise ValueError("model 不能为空")
    tmp = f"{_CONFIG_FILE}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, _CONFIG_FILE)
    return payload


def clear_config() -> None:
    try:
        os.remove(_CONFIG_FILE)
    except FileNotFoundError:
        pass
