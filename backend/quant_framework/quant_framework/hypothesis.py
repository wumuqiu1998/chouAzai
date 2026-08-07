"""研究假设卡：把模糊市场观察转化为可证伪的研究假设。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ResearchHypothesisCard:
    """研究假设卡（八项，缺一不可）。

    作用：不是先证明策略一定有效，而是提前规定出现什么证据后承认它可能无效。
    """

    market_observation: str = ""          # 一、市场观察
    possible_mechanism: str = ""          # 二、可能机制（待验证解释，不是事实）
    signal_definition: str = ""           # 三、信号定义（公式 + 计算时点）
    data_timing: str = ""                 # 四、数据时间（何时可用、何时可交易）
    prediction_target: str = ""           # 五、预测目标（未来哪段收益）
    benchmarks: list[str] = field(default_factory=list)   # 六、基准
    confounders: list[str] = field(default_factory=list)  # 七、混杂变量
    failure_criteria: list[str] = field(default_factory=list)  # 八、失败标准

    def validate(self) -> list[str]:
        """返回缺失/不完整项。空列表表示通过。"""
        problems: list[str] = []
        required_text = {
            "market_observation": "市场观察",
            "possible_mechanism": "可能机制",
            "signal_definition": "信号定义",
            "data_timing": "数据时间",
            "prediction_target": "预测目标",
        }
        for attr, label in required_text.items():
            if not getattr(self, attr).strip():
                problems.append(f"缺少：{label}")
        for attr, label in (("benchmarks", "基准"), ("confounders", "混杂变量"), ("failure_criteria", "失败标准")):
            if not getattr(self, attr):
                problems.append(f"缺少：{label}")
        return problems

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResearchHypothesisCard":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    def summary(self) -> str:
        lines = [
            f"1. 市场观察：{self.market_observation}",
            f"2. 可能机制：{self.possible_mechanism}",
            f"3. 信号定义：{self.signal_definition}",
            f"4. 数据时间：{self.data_timing}",
            f"5. 预测目标：{self.prediction_target}",
            "6. 基准：" + "；".join(self.benchmarks) if self.benchmarks else "6. 基准：缺失",
            "7. 混杂变量：" + "；".join(self.confounders) if self.confounders else "7. 混杂变量：缺失",
            "8. 失败标准：" + "；".join(self.failure_criteria) if self.failure_criteria else "8. 失败标准：缺失",
        ]
        return "\n".join(lines)


def momentum_example() -> ResearchHypothesisCard:
    """方法论中的 20 日相对动量示例。"""
    return ResearchHypothesisCard(
        market_observation="过去 20 个交易日相对行业表现更强的股票，未来 5 个交易日可能仍有收益延续。",
        possible_mechanism="信息反应不足、机构资金持续建仓、投资者注意力逐步扩散（待验证，不是事实）。",
        signal_definition="T 日收盘后计算：20 日相对动量 = 股票过去20日收益 − 所属行业过去20日中位数收益。",
        data_timing="信号在 T 日收盘后才完成，最早 T+1 交易日交易；不能边用 T 日收盘价边假设按 T 日收盘价成交。",
        prediction_target="T+1 日开盘到 T+6 日开盘的收益（约 5 个交易日持有期）。",
        benchmarks=["市场等权组合", "普通 20 日绝对动量", "行业中性的随机组合", "相同市值和流动性组合"],
        confounders=["小市值", "行业", "高 beta", "高波动", "流动性差", "某段牛市"],
        failure_criteria=[
            "分组收益没有单调性",
            "样本外 RankIC 接近零",
            "收益集中在某一年",
            "加入交易成本后收益消失",
            "只有极端参数有效",
            "去掉少数股票后收益大幅下降",
        ],
    )
