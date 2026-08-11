---
name: quant-strategy-kit
description: Vibe-Research 私有量化策略与理论库（缠论/ATR/威科夫/SMC/做T回测/筹码分布）。当需要设计、审查、回测 A 股量化信号，把指标改造成 K 线通俗标定（积/派/扫/突/破/变、B/S 点、顶/底），或排查无未来函数/过拟合问题时使用。
---

# 量化策略知识库

## 核心原则

1. K 线只展示成果性标定：通俗单字信号（积/派/扫/突/破/变）、缠论 B/S 点、ATR 顶/底、分时昨日参考位。底层理论/指标继续参与计算，不在图上显示复杂参数与英文术语。
2. 无未来函数：信号只用截至当前 K 线收盘的数据，T 日收盘后确认、最早 T+1 开盘成交；盘中 `exclude_last` 排除未收盘末根。
3. 回测只改策略因子，不改回测底座（`backend/quant_framework/quant_framework/t_backtest.py`）。
4. 小样本回测（20 个交易日、3~5 只股票）只能筛选方向，不能当验证；避免“投入研究式”调参过拟合。

## 路由（按需读取 references）

- 缠论（分型/笔/中枢/三类买卖点/三卖预警）：`references/chan-theory.md`
- ATR 通道与顶底过滤：`references/atr-channel.md`
- 威科夫/SMC 理论与通俗信号映射：`references/wyckoff-smc.md`
- 做T回测口径与策略对比结论：`references/t-trading.md`
- 筹码分布/主力成本/90%区间：`references/chip-analysis.md`
- 研究方法论（时间审计/假设卡/验证流程）：`references/methodology.md`

## 代码位置

- 后端模块：`F:\Code\Vibe-Research\backend\quant_framework\quant_framework\{chan,atr,wyckoff,smc,regime,market_regime,t_backtest}.py`
- API：`F:\Code\Vibe-Research\backend\quant_framework\quant_framework\api\{chan_api,atr_api,smc_api,day_ref_api}.py`
- 回测/研究脚本：`F:\Code\Vibe-Research\backend\quant_framework\run_*.py`
- 前端 K 线：`F:\Code\Vibe-Research\frontend\src\pages\LiveTrading.tsx`
- 测试：`F:\Code\Vibe-Research\backend\quant_framework\tests\`

## 新增/修改信号的工作流

> ⚠️ 2026-08-11 教训：全量点位会重标（未来函数），缠论一律用
> `analyze_chan_locked`，SMC 用逐 bar 因果扫荡；所有“优势”结论在
> 完成两轮辩驳 + 五道关前一律视为“未验证”。详见项目 `AGENTS.md`。

1. 读对应 references 确认现有口径与参数；
2. 实现时保证信号只用截至 T 收盘的数据，缠论默认 `analyze_chan_locked`；
3. 写单元测试 + 截断一致性测试（`tests/test_no_lookahead.py` 模式）；
4. 用 `run_*` 脚本做小样本回测（20 个交易日、半仓 50%、佣金+印花税+滑点）；
5. 前端只输出成果性标定，复杂参数留在 tooltip/说明里；
6. **强制两轮正反辩驳**：第一轮正方假设+证据 → 反方唱反调 → 正方答辩；
   第二轮反方复辩 → 终辩行动项；文档存入 `docs/`，实验写入 `experiments.csv`；
7. **信号准入五道关**（假设卡 → 单测 → 截断一致性 → 随机+同板块异股基准 →
   参数固定样本外），全部通过才允许标记“通过/已验证”。
