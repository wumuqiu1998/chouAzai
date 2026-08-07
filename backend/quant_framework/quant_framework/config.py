"""YAML 配置加载/保存 + 配置 diff。

设计原则：改配置 = 改验证标准，必须通过 API 保存并记录到实验日志。
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import yaml

from quant_framework.hypothesis import ResearchHypothesisCard
from quant_framework.models import BacktestBaseConfig, ExperimentProtocol, RiskLimits

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
DEFAULT_PATHS = {
    "backtest": CONFIG_DIR / "backtest_base.yaml",
    "protocol": CONFIG_DIR / "experiment_protocol.yaml",
    "risk": CONFIG_DIR / "risk_limits.yaml",
    "hypothesis": PROJECT_ROOT / "examples" / "momentum_hypothesis.yaml",
}


def _read_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


def _as_plain(obj: Any) -> dict:
    """dataclass -> dict，tuple 转 list（YAML 友好）。"""
    if is_dataclass(obj):
        d = asdict(obj)
        if isinstance(d.get("metrics"), tuple):
            d["metrics"] = list(d["metrics"])
        return d
    return dict(obj)


# ---- backtest base ----

def load_backtest_config(path: str | Path | None = None) -> BacktestBaseConfig:
    data = _read_yaml(Path(path) if path else DEFAULT_PATHS["backtest"])
    metrics = tuple(data.pop("metrics", ()))
    return BacktestBaseConfig(**data, metrics=metrics)


def save_backtest_config(cfg: BacktestBaseConfig, path: str | Path | None = None) -> Path:
    target = Path(path) if path else DEFAULT_PATHS["backtest"]
    _write_yaml(target, _as_plain(cfg))
    return target


def backtest_config_from_dict(data: dict) -> BacktestBaseConfig:
    metrics = tuple(data.get("metrics", ()))
    clean = {k: v for k, v in data.items() if k != "metrics"}
    return BacktestBaseConfig(**clean, metrics=metrics)


# ---- risk limits ----

def load_risk_limits(path: str | Path | None = None) -> RiskLimits:
    data = _read_yaml(Path(path) if path else DEFAULT_PATHS["risk"])
    return RiskLimits(**data)


def save_risk_limits(limits: RiskLimits, path: str | Path | None = None) -> Path:
    target = Path(path) if path else DEFAULT_PATHS["risk"]
    _write_yaml(target, _as_plain(limits))
    return target


# ---- experiment protocol ----

def load_experiment_protocol(path: str | Path | None = None) -> ExperimentProtocol:
    data = _read_yaml(Path(path) if path else DEFAULT_PATHS["protocol"])
    return ExperimentProtocol(**data)


def save_experiment_protocol(protocol: ExperimentProtocol, path: str | Path | None = None) -> Path:
    target = Path(path) if path else DEFAULT_PATHS["protocol"]
    _write_yaml(target, _as_plain(protocol))
    return target


# ---- hypothesis card ----

def load_hypothesis_card(path: str | Path | None = None) -> ResearchHypothesisCard:
    data = _read_yaml(Path(path) if path else DEFAULT_PATHS["hypothesis"])
    return ResearchHypothesisCard.from_dict(data)


def save_hypothesis_card(card: ResearchHypothesisCard, path: str | Path | None = None) -> Path:
    target = Path(path) if path else DEFAULT_PATHS["hypothesis"]
    _write_yaml(target, card.to_dict())
    return target


# ---- diff ----

def _flatten(data: dict, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in data.items():
        key = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


def config_diff(old: Any, new: Any) -> list[str]:
    """返回扁平化后的差异行，例如 'commission_rate: 0.0003 -> 0.0005'。"""
    o = _flatten(_as_plain(old))
    n = _flatten(_as_plain(new))
    lines = []
    for k in sorted(set(o) | set(n)):
        if o.get(k) != n.get(k):
            lines.append(f"{k}: {o.get(k)} -> {n.get(k)}")
    return lines
