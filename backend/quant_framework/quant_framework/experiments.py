"""实验管理：记录所有实验（含失败的），检查参数表面。"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from quant_framework.models import ExperimentRecord


class ExperimentLog:
    """追加式实验日志（CSV）。只增不删。"""

    FIELDS = [
        "experiment_id",
        "hypothesis",
        "unique_change",
        "expected",
        "dev_result",
        "val_result",
        "cost_result",
        "passed",
        "failure_reason",
        "code_version",
        "created_at",
    ]

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self._rows: list[ExperimentRecord] = []
        if self.path and self.path.exists():
            self._load()

    def _load(self) -> None:
        with self.path.open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                self._rows.append(ExperimentRecord.from_row(row))

    def append(self, record: ExperimentRecord) -> None:
        self._rows.append(record)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self.FIELDS)
                if self.path.stat().st_size == 0:
                    writer.writeheader()
                writer.writerow(record.to_row())

    def extend(self, records: Iterable[ExperimentRecord]) -> None:
        for r in records:
            self.append(r)

    def __len__(self) -> int:
        return len(self._rows)

    def total_attempts(self) -> int:
        """测试总次数是结果可信度的一部分。"""
        return len(self._rows)

    def success_rate(self) -> float:
        if not self._rows:
            return 0.0
        return sum(1 for r in self._rows if r.passed) / len(self._rows)

    def all_rows(self) -> list[ExperimentRecord]:
        return list(self._rows)


def parameter_surface(
    results: dict[str, float],
    metric: str = "annual_return",
) -> dict:
    """检查参数表面：针尖型最优参数比平滑区域更可疑。

    results: {参数值: 指标值}，例如 {"19": 0.01, "20": 0.25, "21": 0.02}
    返回是否"针尖型"及判断依据。
    """
    if len(results) < 3:
        return {"needle": False, "best": None, "neighbor_delta": None, "reason": "参数点不足3个"}
    items = sorted(results.items(), key=lambda kv: kv[0])
    best_key, best_val = max(items, key=lambda kv: kv[1])
    best_pos = [i for i, (k, _) in enumerate(items) if k == best_key][0]
    neighbors = []
    if best_pos > 0:
        neighbors.append(items[best_pos - 1][1])
    if best_pos < len(items) - 1:
        neighbors.append(items[best_pos + 1][1])
    neighbor_mean = sum(neighbors) / len(neighbors) if neighbors else 0.0
    delta = best_val - neighbor_mean
    needle = delta > 0 and (neighbor_mean <= 0 or delta / abs(neighbor_mean) > 3.0)
    return {
        "needle": bool(needle),
        "best": best_key,
        "neighbor_delta": float(delta),
        "reason": (
            f"{metric} 最优参数 {best_key} 明显高于相邻参数（delta={delta:.4f}），"
            "疑似针尖型最优参数，需要怀疑过拟合"
            if needle
            else f"参数表面较平滑，{metric} 最优参数 {best_key} 可信度更高"
        ),
    }
