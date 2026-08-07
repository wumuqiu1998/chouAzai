"""因子层：AI 唯一被允许修改的部分。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import pandas as pd


FactorFunc = Callable[[pd.DataFrame], pd.Series]


@dataclass
class Factor:
    """因子 = 名称 + 可调用实现 + 数据时间说明。"""

    name: str
    func: Optional[FactorFunc] = None
    description: str = ""
    calculation_time: str = "T日收盘后"
    earliest_trade_time: str = "T+1交易日"

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if self.func is None:
            raise NotImplementedError(f"因子 {self.name} 未实现 func")
        return self.func(df)


def momentum_20d(df: pd.DataFrame) -> pd.Series:
    """20 日绝对动量（用于示例/基线）。df 需含 close，按日期排序。"""
    return df["close"] / df["close"].shift(20) - 1.0


def relative_momentum_20d(df: pd.DataFrame) -> pd.Series:
    """20 日相对动量 = 个股 20 日收益 − 行业中位 20 日收益。"""
    ret20 = df["close"] / df["close"].shift(20) - 1.0
    if "industry" not in df.columns:
        return ret20
    med = ret20.groupby(df["industry"]).transform("median")
    return ret20 - med


def _make_micro_sample() -> pd.DataFrame:
    """微型样本：2 只股票 × 6 个交易日，用于手工核对因子定义。"""
    dates = pd.date_range("2025-01-06", periods=6, freq="B")
    rows = []
    for i, code in enumerate(["A", "B"]):
        base = 10.0 + i
        for j, d in enumerate(dates):
            rows.append(
                {
                    "symbol": code,
                    "date": d,
                    "close": base * (1 + 0.01 * (j + 1)),
                }
            )
    df = pd.DataFrame(rows).sort_values(["symbol", "date"]).reset_index(drop=True)
    return df


def manual_3day_return(df: pd.DataFrame) -> pd.Series:
    """手工参考实现：按股票分组计算 3 日收益（正确写法）。"""
    return df.groupby("symbol")["close"].pct_change(3)


def buggy_cross_stock_rolling(df: pd.DataFrame) -> pd.Series:
    """错误实现：滚动窗口跨越不同股票（未按股票分组）。"""
    return df["close"].pct_change(3)


@dataclass
class MicroSampleValidator:
    """微型样本校验：证明代码实现的是你描述的策略，然后才有资格谈收益。"""

    sample: pd.DataFrame = field(default_factory=_make_micro_sample)

    def compare(
        self,
        candidate: FactorFunc,
        reference: FactorFunc,
        period: int = 3,
    ) -> dict[str, object]:
        df = self.sample
        cand = candidate(df).fillna(np.nan)
        ref = reference(df).fillna(np.nan)
        mismatch = ~np.isclose(cand, ref, equal_nan=True)
        return {
            "candidate": cand,
            "reference": ref,
            "mismatch_count": int(mismatch.sum()),
            "mismatch_positions": list(np.where(mismatch)[0]),
            "passed": bool((~mismatch).all()),
        }

    @staticmethod
    def unit_test_checklist() -> list[str]:
        """方法论要求的单元测试覆盖项。"""
        return [
            "输入数据被打乱后结果一致",
            "不同股票之间无串扰",
            "数据不足时返回空值（不填零）",
            "符号方向正确",
            "分母为 0 的处理",
            "缺失值不被错误填充",
            "相同输入得到相同输出",
        ]
