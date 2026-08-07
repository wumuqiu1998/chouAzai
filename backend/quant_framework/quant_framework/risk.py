"""硬性风控与上线阶段管理。AI 无权修改。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from quant_framework.models import Order, RiskLimits


class DeploymentStage(str, Enum):
    BACKTEST = "backtest"
    OOS = "oos"
    PAPER = "paper"
    SHADOW = "shadow"
    SMALL_CAPITAL = "small_capital"
    SCALED = "scaled"

    @property
    def order(self) -> int:
        return list(DeploymentStage).index(self)


@dataclass
class RiskCheckResult:
    allowed: bool
    violations: list[str] = field(default_factory=list)


class RiskManager:
    """硬性风控：下单前逐项检查。"""

    def __init__(self, limits: RiskLimits | None = None):
        self.limits = limits or RiskLimits()
        self._today_orders: list[Order] = []
        self._today_turnover = 0.0
        self._today_pnl = 0.0
        self._data_connected = True

    def set_data_connected(self, ok: bool) -> None:
        self._data_connected = ok

    def record_trade(self, order: Order, realized_pnl: float = 0.0) -> None:
        self._today_orders.append(order)
        self._today_turnover += order.amount
        self._today_pnl += realized_pnl

    def check_order(
        self,
        order: Order,
        equity: float,
        existing_position: float = 0.0,
        prev_close: Optional[float] = None,
    ) -> RiskCheckResult:
        l = self.limits
        violations: list[str] = []
        if l.emergency_stop:
            violations.append("紧急停止交易已触发")
        if self._today_pnl <= -l.max_daily_loss * equity:
            violations.append("单日最大亏损已触发，禁止开新仓")
        if not self._data_connected and l.disconnect_guard:
            violations.append("数据断线保护：禁止交易")
        if order.price <= 0:
            violations.append("价格异常：价格 <= 0")
        if prev_close and l.price_sanity_band:
            change = abs(order.price / prev_close - 1.0)
            if change > l.price_sanity_band:
                violations.append(f"价格异动超过 {l.price_sanity_band:.0%}，疑似数据错误")
        duplicate = sum(1 for o in self._today_orders if o.symbol == order.symbol and o.side == order.side)
        if duplicate >= l.max_duplicate_orders:
            violations.append(f"同一标的同日重复下单超过 {l.max_duplicate_orders} 次")
        if order.amount > l.max_order_amount:
            violations.append(f"单笔金额 {order.amount:.0f} 超过上限 {l.max_order_amount:.0f}")
        if order.side == "buy":
            if existing_position + order.amount > l.max_position_per_stock * equity:
                violations.append(f"单票仓位超过 {l.max_position_per_stock:.0%}")
            if self._today_turnover + order.amount > l.max_daily_turnover * equity:
                violations.append(f"单日换手超过 {l.max_daily_turnover:.0%}")
            if existing_position + order.amount > l.max_total_position * equity:
                violations.append(f"总仓位超过 {l.max_total_position:.0%}")
        return RiskCheckResult(allowed=not violations, violations=violations)

    def can_advance(
        self,
        current: DeploymentStage,
        target: DeploymentStage,
        conditions: dict[str, bool],
    ) -> tuple[bool, list[str]]:
        """上线顺序：backtest -> oos -> paper -> shadow -> small -> scaled。"""
        if target.order <= current.order:
            return True, []
        required = []
        for stage in [DeploymentStage.BACKTEST, DeploymentStage.OOS, DeploymentStage.PAPER, DeploymentStage.SHADOW]:
            if stage.order < target.order and not conditions.get(stage.value, False):
                required.append(f"未完成 {stage.value} 阶段")
        return (not required), required
