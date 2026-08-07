"""可复用提示词模板（与 ai-quant-research 技能一致）。"""


def hypothesis_card_prompt(observation: str) -> str:
    return (
        f"请把这个市场观察转化为一张可证伪的研究假设卡：{observation}。"
        "包含八项：市场观察、可能机制、信号定义（含计算公式与计算时点）、"
        "数据时间、预测目标、基准、混杂变量、失败标准。暂时不要优化收益，也不要写代码。"
    )


def time_audit_prompt(fields: list[str]) -> str:
    return (
        "请为以下字段生成时间审计表，每个字段给出事件发生时间、数据可用时间、"
        "信号计算时间、实际交易时间，并指出哪些字段的可用时间晚于回测下单时间"
        f"（存在数据泄漏或未来函数风险）。字段：{'、'.join(fields)}。"
    )


def factor_unit_test_prompt(module_path: str) -> str:
    return (
        f"请为 {module_path} 编写单元测试，覆盖：输入数据打乱后结果一致、"
        "不同股票之间无串扰、数据不足返回空值、符号方向正确、分母为0处理、"
        "缺失值处理、相同输入相同输出。"
    )


def ablation_prompt(base_signal: str, modules: list[str]) -> str:
    mods = "、".join(modules)
    return (
        f"请为以下模块设计消融实验：A {base_signal}，B {mods}。"
        "分别测试 A、A+B、A+C、A+D、A+E，每步报告年化收益、最大回撤、夏普率、换手率、"
        "交易成本、分年度表现、选股数量、收益集中度、参数稳定性、策略容量，"
        "并判断每个模块是否有独立贡献。"
    )


def adversarial_audit_prompt(code: str, data_spec: str, result: str) -> str:
    return (
        "单独开一个新对话，不提供'策略很优秀'的上下文，也不强调历史收益。\n"
        f"策略代码：{code}\n数据口径：{data_spec}\n回测结果：{result}\n\n"
        "任务：你的任务不是提高收益，而是证明这个策略可能是假的。"
        "重点检查：未来函数、数据时间点、财务数据发布日期、幸存者偏差、历史股票池、复权方式、"
        "不保证成交、手续费和滑点、涨跌停和停牌、参数敏感度、收益年份集中度、股票集中度、"
        "行业和市值暴露、多重验证、样本外污染、策略容量。"
        "对每个问题输出四项：风险等级、具体证据、需要追加的实验、可能的修复方式。"
    )


def shadow_trading_prompt() -> str:
    return (
        "请分析影子交易日志，对比模拟成交与真实市场：信号实际生成延迟、真实可成交价格、"
        "成交率、滑点、涨跌停限制、订单对价格的影响、数据断线情况、实盘与回测持仓偏差，"
        "并给出改进建议。"
    )
