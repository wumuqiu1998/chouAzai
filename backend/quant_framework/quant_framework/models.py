"""框架核心数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class DataFieldTiming:
    """数据时间审计：每个字段的四个时间。

    规则：available_time 晚于回测中的 order_time 即存在数据泄漏/未来函数风险。
    """

    field_name: str
    event_time: str          # 事件发生时间
    available_time: str      # 投资者真正能拿到数据的时间
    signal_time: str         # 程序能完整计算信号的时间
    trade_time: str          # 信号完成后最早可成交的时间
    note: str = ""

    def has_lookahead(self, order_time: str) -> bool:
        return self.available_time > order_time


@dataclass(frozen=True)
class SignalDefinition:
    """信号定义：可计算、可回测的最小单元。"""

    name: str
    expression: str                 # 计算公式/伪代码
    calculation_time: str           # 例如 "T日收盘后"
    earliest_trade_time: str        # 例如 "T+1交易日"
    holding_period_days: int        # 持有期（交易日）
    universe: str = "all_a_share"   # 股票池


@dataclass(frozen=True)
class BacktestBaseConfig:
    """固定回测底座：AI 只改因子，不改这里。"""

    initial_cash: float = 1_000_000.0
    commission_rate: float = 0.0003          # 佣金
    stamp_duty_rate: float = 0.0005          # 印花税（卖出）
    slippage: float = 0.0                    # 滑点（比例）
    lot_size: int = 100                      # A股整手
    fill_price: str = "next_open"            # next_open / next_close / signal_close
    rebalance_freq_days: int = 5             # 调仓周期
    holding_period_days: int = 5             # 持有周期
    top_n: int = 20                          # 持仓只数
    limit_up_pct: float = 0.098              # 涨跌停限制
    limit_down_pct: float = 0.098
    enforce_limit: bool = True               # 涨跌停不可成交
    t_plus_one: bool = True                  # T+1 交易规则
    metrics: tuple[str, ...] = (
        "annual_return",
        "max_drawdown",
        "sharpe",
        "turnover",
        "cost",
        "yearly",
        "selection_count",
        "return_concentration",
    )

    def validate(self) -> list[str]:
        problems: list[str] = []
        if self.holding_period_days <= 0:
            problems.append("holding_period_days 必须 > 0")
        if self.top_n <= 0:
            problems.append("top_n 必须 > 0")
        if self.fill_price == "signal_close" and self.t_plus_one:
            problems.append("T+1 规则下不允许 signal_close 成交（未来函数风险）")
        return problems


@dataclass(frozen=True)
class RiskLimits:
    """硬性风控：AI 无权修改。"""

    max_position_per_stock: float = 0.10     # 单票最大仓位（占总资产比例）
    max_total_position: float = 0.95         # 总仓位上限
    max_daily_turnover: float = 0.30         # 单日最大换手（占总资产比例）
    max_daily_loss: float = 0.03             # 单日最大亏损（触发后禁止开新仓）
    max_order_amount: float = 500_000.0      # 单笔最大金额
    price_sanity_band: float = 0.15          # 价格异动检查（相对昨收）
    max_duplicate_orders: int = 1            # 同一标的同日重复下单次数上限
    disconnect_guard: bool = True            # 数据断线保护
    emergency_stop: bool = False             # 紧急停止交易


@dataclass(frozen=True)
class ExperimentProtocol:
    """实验协议：回测之前提前制定，进入盲测前冻结。"""

    dev_ratio: float = 0.6
    val_ratio: float = 0.2
    blind_ratio: float = 0.2
    walk_forward: dict = field(
        default_factory=lambda: {
            "train_days": 250,
            "test_days": 21,
            "label_horizon_days": 5,
            "embargo_days": 5,
        }
    )
    max_changes_per_experiment: int = 1
    keep_failed_experiments: bool = True
    pass_criteria: dict = field(
        default_factory=lambda: {
            "oos_rank_ic_positive": True,
            "cost_after_return_positive": True,
            "yearly_positive_ratio": 0.6,
            "max_drawdown_upper": -0.25,
        }
    )
    failure_criteria: list = field(default_factory=list)

    def validate(self) -> list[str]:
        problems: list[str] = []
        total = self.dev_ratio + self.val_ratio + self.blind_ratio
        if abs(total - 1.0) > 1e-6:
            problems.append(f"开发/验证/盲测比例之和应为 1，当前为 {total}")
        if self.max_changes_per_experiment < 1:
            problems.append("max_changes_per_experiment 必须 >= 1")
        return problems


@dataclass
class ExperimentRecord:
    """实验日志：所有实验（包括失败的）都必须记录。"""

    experiment_id: str
    hypothesis: str
    unique_change: str
    expected: str
    dev_result: str = ""
    val_result: str = ""
    cost_result: str = ""
    passed: bool = False
    failure_reason: str = ""
    code_version: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_row(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "hypothesis": self.hypothesis,
            "unique_change": self.unique_change,
            "expected": self.expected,
            "dev_result": self.dev_result,
            "val_result": self.val_result,
            "cost_result": self.cost_result,
            "passed": self.passed,
            "failure_reason": self.failure_reason,
            "code_version": self.code_version,
            "created_at": self.created_at,
        }

    @classmethod
    def from_row(cls, row: dict) -> "ExperimentRecord":
        def _parse_bool(value) -> bool:
            return str(value).strip().lower() in ("1", "true", "yes")

        return cls(
            experiment_id=str(row["experiment_id"]),
            hypothesis=str(row.get("hypothesis", "")),
            unique_change=str(row.get("unique_change", "")),
            expected=str(row.get("expected", "")),
            dev_result=str(row.get("dev_result", "")),
            val_result=str(row.get("val_result", "")),
            cost_result=str(row.get("cost_result", "")),
            passed=_parse_bool(row.get("passed", False)),
            failure_reason=str(row.get("failure_reason", "")),
            code_version=str(row.get("code_version", "")),
            created_at=str(row.get("created_at", "")),
        )


@dataclass
class Order:
    """待检查的交易指令。"""

    date: str
    symbol: str
    side: str          # buy / sell
    amount: float      # 金额
    price: float
    prev_close: Optional[float] = None
