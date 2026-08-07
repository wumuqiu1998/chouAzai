"""对抗审计：让另一个 AI 证明策略可能是假的。"""

from __future__ import annotations

from dataclasses import dataclass, field


AUDIT_CHECKLIST: list[str] = [
    "未来函数",
    "数据时间点",
    "财务数据发布日期",
    "幸存者偏差",
    "历史股票池",
    "复权方式",
    "不保证成交",
    "手续费和滑点",
    "涨跌停和停牌",
    "参数敏感度",
    "收益年份集中度",
    "股票集中度",
    "行业和市值暴露",
    "多重验证",
    "样本外污染",
    "策略容量",
]


@dataclass
class AuditIssue:
    """对抗审计对每个问题的输出格式。"""

    item: str
    risk_level: str          # 高 / 中 / 低
    evidence: str
    experiments_needed: str
    possible_fix: str

    def to_dict(self) -> dict:
        return {
            "item": self.item,
            "risk_level": self.risk_level,
            "evidence": self.evidence,
            "experiments_needed": self.experiments_needed,
            "possible_fix": self.possible_fix,
        }


@dataclass
class AdversarialAudit:
    """一次对抗审计会话的产物。"""

    strategy_code: str = ""
    data_spec: str = ""
    backtest_result: str = ""
    issues: list[AuditIssue] = field(default_factory=list)

    def build_prompt(self) -> str:
        return (
            "你的任务不是提高收益，而是证明这个策略可能是假的。\n"
            f"策略代码：\n{self.strategy_code or '（待提供）'}\n"
            f"数据口径：\n{self.data_spec or '（待提供）'}\n"
            f"回测结果：\n{self.backtest_result or '（待提供）'}\n\n"
            "重点检查：\n- " + "\n- ".join(AUDIT_CHECKLIST) + "\n\n"
            "对每个问题输出四项：风险等级、具体证据、需要追加的实验、可能的修复方式。"
        )

    def issues_by_risk(self) -> list[AuditIssue]:
        order = {"高": 0, "中": 1, "低": 2}
        return sorted(self.issues, key=lambda i: order.get(i.risk_level, 9))
