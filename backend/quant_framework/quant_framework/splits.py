"""数据分层与滚动样本外验证（Purging / Embargo）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import pandas as pd


@dataclass(frozen=True)
class DataSplits:
    dev: tuple[str, str]
    val: tuple[str, str]
    blind: tuple[str, str]

    def validate(self) -> list[str]:
        problems = []
        ranges = [("dev", self.dev), ("val", self.val), ("blind", self.blind)]
        for name, (a, b) in ranges:
            if a > b:
                problems.append(f"{name} 区间起点晚于终点")
        if self.dev[1] >= self.val[0]:
            problems.append("dev 与 val 区间重叠")
        if self.val[1] >= self.blind[0]:
            problems.append("val 与 blind 区间重叠")
        return problems


def split_dev_val_blind(
    dates: list[str] | pd.DatetimeIndex,
    dev_ratio: float = 0.6,
    val_ratio: float = 0.2,
) -> DataSplits:
    """按时间顺序切分开发集 / 验证集 / 盲测集（不允许随机切分）。"""
    if dev_ratio + val_ratio >= 1.0:
        raise ValueError("dev_ratio + val_ratio 必须 < 1")
    dates = list(dates)
    n = len(dates)
    dev_end = dates[int(n * dev_ratio) - 1]
    val_end = dates[int(n * (dev_ratio + val_ratio)) - 1]
    return DataSplits(
        dev=(dates[0], dev_end),
        val=(dates[int(n * dev_ratio)], val_end),
        blind=(dates[int(n * (dev_ratio + val_ratio))], dates[-1]),
    )


def walk_forward_split(
    dates: list[str] | pd.DatetimeIndex,
    train_days: int = 250,
    test_days: int = 21,
) -> Iterator[tuple[pd.DatetimeIndex, pd.DatetimeIndex]]:
    """滚动验证：过去训练、未来测试、向前滚动。"""
    dates = pd.DatetimeIndex(dates)
    i = train_days
    while i + test_days <= len(dates):
        yield dates[i - train_days : i], dates[i : i + test_days]
        i += test_days


def purge_labels(
    train_dates: pd.DatetimeIndex,
    test_dates: pd.DatetimeIndex,
    label_horizon_days: int,
) -> pd.DatetimeIndex:
    """Purging：删除标签区间与测试期重叠的训练样本。

    训练样本 t 的标签覆盖 [t, t+horizon)，若与测试期 [test_start, test_end) 重叠则删除。
    """
    test_start = test_dates[0]
    test_end = test_dates[-1]
    keep = []
    for d in train_dates:
        label_end = d + pd.Timedelta(days=label_horizon_days)
        overlap = label_end > test_start and d < test_end
        if not overlap:
            keep.append(d)
    return pd.DatetimeIndex(keep)


def embargo(
    train_dates: pd.DatetimeIndex,
    test_dates: pd.DatetimeIndex,
    embargo_days: int,
) -> pd.DatetimeIndex:
    """Embargo：训练/测试边界留隔离区。"""
    test_start = test_dates[0]
    cutoff = test_start - pd.Timedelta(days=embargo_days)
    return train_dates[train_dates < cutoff]
