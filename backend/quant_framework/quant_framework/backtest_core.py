"""固定回测底座：只读，AI 不可修改。

设计：信号在 T 日收盘计算，默认 T+1 开盘成交（避免未来函数），
含佣金/印花税/整手/涨跌停限制；跑法：每日按因子排名取 top_n。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from quant_framework.models import BacktestBaseConfig


@dataclass
class BacktestMetrics:
    annual_return: float = float("nan")
    max_drawdown: float = float("nan")
    sharpe: float = float("nan")
    turnover: float = float("nan")
    total_cost: float = 0.0
    yearly: dict = field(default_factory=dict)
    selection_count: int = 0
    return_concentration: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "annual_return": round(self.annual_return, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "sharpe": round(self.sharpe, 3),
            "turnover": round(self.turnover, 4),
            "total_cost": round(self.total_cost, 2),
            "yearly": {k: round(v, 4) for k, v in self.yearly.items()},
            "selection_count": self.selection_count,
            "return_concentration": {
                k: (round(v, 4) if isinstance(v, float) else v) for k, v in self.return_concentration.items()
            },
        }


@dataclass
class BacktestRun:
    metrics: BacktestMetrics
    equity_curve: pd.Series
    daily_returns: pd.Series
    trades: pd.DataFrame = field(default_factory=pd.DataFrame)
    error: str = ""


class FixedBacktestEngine:
    """固定底座执行器。只接受因子 DataFrame（date × symbol）。"""

    def __init__(self, config: BacktestBaseConfig | None = None):
        self.config = config or BacktestBaseConfig()
        problems = self.config.validate()
        if problems:
            raise ValueError("回测底座配置不合法：" + "；".join(problems))

    def run(
        self,
        factor: pd.DataFrame,
        open_price: pd.DataFrame,
        close_price: pd.DataFrame,
    ) -> BacktestRun:
        cfg = self.config
        dates = pd.DatetimeIndex(factor.index)
        factor = factor.loc[dates]
        open_price = open_price.loc[dates]
        close_price = close_price.loc[dates]

        cash = cfg.initial_cash
        holdings: dict[str, int] = {}
        equity_curve: list[float] = []
        trades: list[dict] = []

        for i, d in enumerate(dates):
            # 1) 用 T-1 收盘后的信号（今日执行），严格避免用今日收盘
            signal_date = factor.index[max(0, i - 1)]
            signal_row = factor.loc[signal_date].dropna()
            if len(signal_row) == 0:
                equity = cash + sum(sh * close_price.loc[d, s] for s, sh in holdings.items())
                equity_curve.append(equity)
                continue
            target_symbols = signal_row.nlargest(cfg.top_n).index.tolist()

            # 2) 卖出不在目标中的持仓（按今日开盘，含印花税/佣金）
            for s in list(holdings.keys()):
                if s not in target_symbols:
                    px = open_price.loc[d, s]
                    if self._blocked_by_limit(px, close_price, d, s, side="sell"):
                        continue
                    shares = holdings.pop(s)
                    gross = shares * px
                    fee = gross * (cfg.commission_rate + cfg.stamp_duty_rate + cfg.slippage)
                    cash += gross - fee
                    trades.append(
                        {"date": str(d.date()), "symbol": s, "side": "sell", "price": px, "shares": shares, "cost": fee}
                    )

            # 3) 买入目标中不足的股票
            for s in target_symbols:
                if s in holdings:
                    continue
                px = open_price.loc[d, s]
                if self._blocked_by_limit(px, close_price, d, s, side="buy"):
                    continue
                budget = cash / max(1, len(target_symbols) - len([x for x in target_symbols if x in holdings]))
                shares = int(budget / (px * (1 + cfg.slippage)) / cfg.lot_size) * cfg.lot_size
                if shares <= 0:
                    continue
                gross = shares * px
                fee = gross * (cfg.commission_rate + cfg.slippage)
                if gross + fee > cash:
                    shares = int((cash - fee) / px / cfg.lot_size) * cfg.lot_size
                    if shares <= 0:
                        continue
                    gross = shares * px
                    fee = gross * (cfg.commission_rate + cfg.slippage)
                cash -= gross + fee
                holdings[s] = shares
                trades.append(
                    {"date": str(d.date()), "symbol": s, "side": "buy", "price": px, "shares": shares, "cost": fee}
                )

            equity = cash + sum(sh * close_price.loc[d, s] for s, sh in holdings.items())
            equity_curve.append(equity)

        eq = pd.Series(equity_curve, index=dates)
        daily_ret = eq.pct_change().dropna()
        metrics = self._metrics(eq, daily_ret, trades)
        return BacktestRun(
            metrics=metrics,
            equity_curve=eq,
            daily_returns=daily_ret,
            trades=pd.DataFrame(trades),
        )

    def _blocked_by_limit(self, px, close_price, d, s, side: str) -> bool:
        cfg = self.config
        if not cfg.enforce_limit or px != px:
            return False
        prev = close_price.shift(1).loc[d, s] if d in close_price.index else np.nan
        if prev != prev or prev <= 0:
            return False
        chg = px / prev - 1.0
        if side == "buy" and chg >= cfg.limit_up_pct - 1e-6:
            return True
        if side == "sell" and chg <= -cfg.limit_down_pct + 1e-6:
            return True
        return False

    def _metrics(self, eq: pd.Series, daily_ret: pd.Series, trades: list[dict]) -> BacktestMetrics:
        n = len(eq)
        if n < 2:
            return BacktestMetrics()
        total_ret = eq.iloc[-1] / eq.iloc[0] - 1.0
        years = max(n / 244.0, 1e-9)
        annual = (1 + total_ret) ** (1 / years) - 1.0
        peak = eq.cummax()
        mdd = float(((eq - peak) / peak).min())
        sharpe = (
            float(daily_ret.mean() / daily_ret.std() * np.sqrt(244))
            if len(daily_ret) > 1 and daily_ret.std() > 0
            else float("nan")
        )
        total_cost = float(sum(t["cost"] for t in trades))
        buy_amount = sum(t["shares"] * t["price"] for t in trades if t["side"] == "buy")
        turnover = float(buy_amount / eq.iloc[0]) if eq.iloc[0] else 0.0
        yearly = {}
        if len(daily_ret) > 0:
            yearly = daily_ret.groupby(daily_ret.index.year).apply(lambda x: (1 + x).prod() - 1).to_dict()
        selection_count = len(set(t["symbol"] for t in trades))
        stock_amount = {}
        for t in trades:
            if t["side"] == "buy":
                stock_amount[t["symbol"]] = stock_amount.get(t["symbol"], 0.0) + t["shares"] * t["price"]
        if stock_amount:
            from quant_framework.diagnostics import concentration

            conc = concentration(pd.Series(stock_amount), by="stock")
        else:
            conc = {"top_share": float("nan"), "hhi": float("nan"), "n": 0}
        return BacktestMetrics(
            annual_return=float(annual),
            max_drawdown=mdd,
            sharpe=sharpe,
            turnover=turnover,
            total_cost=total_cost,
            yearly=yearly,
            selection_count=selection_count,
            return_concentration=conc,
        )


@dataclass
class AblationStep:
    name: str
    modules: tuple[str, ...]
    metrics: BacktestMetrics


class AblationRunner:
    """消融实验：基线 + 一次只加一个模块。"""

    def __init__(self, engine: FixedBacktestEngine):
        self.engine = engine

    def run(
        self,
        baseline: pd.DataFrame,
        modules: dict[str, pd.DataFrame],
        open_price: pd.DataFrame,
        close_price: pd.DataFrame,
    ) -> list[AblationStep]:
        steps = [AblationStep(name="A", modules=(), metrics=self.engine.run(baseline, open_price, close_price).metrics)]
        for name, factor_df in modules.items():
            r = self.engine.run(factor_df, open_price, close_price)
            steps.append(AblationStep(name=f"A+{name}", modules=(name,), metrics=r.metrics))
        return steps
