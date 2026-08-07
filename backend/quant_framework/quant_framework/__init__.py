"""quant_framework —— 依据《普通人做AI量化（上下集）》方法论搭建的量化交易研究框架。

核心设计原则（与 ai-quant-research 技能一致）：
1. AI 只改因子，不改回测底座。
2. 一次只改变一个变量，所有失败的实验都要保留。
3. 一条漂亮的净值曲线不是研究的终点，而是审计的起点。
"""

from quant_framework.models import (
    BacktestBaseConfig,
    DataFieldTiming,
    ExperimentRecord,
    RiskLimits,
    SignalDefinition,
)
from quant_framework.hypothesis import ResearchHypothesisCard, momentum_example
from quant_framework.timing_audit import audit_field_timing, check_lookahead
from quant_framework.diagnostics import (
    concentration,
    factor_decay,
    grouped_returns,
    ic_series,
    rank_ic,
)
from quant_framework.splits import (
    embargo,
    purge_labels,
    split_dev_val_blind,
    walk_forward_split,
)
from quant_framework.experiments import ExperimentLog, parameter_surface
from quant_framework.risk import DeploymentStage, RiskManager

__all__ = [
    "BacktestBaseConfig",
    "DataFieldTiming",
    "ExperimentRecord",
    "RiskLimits",
    "SignalDefinition",
    "ResearchHypothesisCard",
    "momentum_example",
    "audit_field_timing",
    "check_lookahead",
    "concentration",
    "factor_decay",
    "grouped_returns",
    "ic_series",
    "rank_ic",
    "embargo",
    "purge_labels",
    "split_dev_val_blind",
    "walk_forward_split",
    "ExperimentLog",
    "parameter_surface",
    "DeploymentStage",
    "RiskManager",
]

__version__ = "0.1.0"
