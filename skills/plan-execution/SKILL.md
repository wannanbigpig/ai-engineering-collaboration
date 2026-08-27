---
name: plan-execution
description: "按已确认方案实施工程任务：先核对方案与最新工作区，再按可验证切片推进；方案失效时停止并重新路由。Execute an approved engineering plan with fresh-state checks, verifiable slices, and explicit replanning boundaries."
license: MIT
compatibility: universal
metadata:
  version: 1.2.0
---

# 方案实施

将已确认的方案、Spec、任务清单或明确的实施步骤转为可验证的改动。计划是当前判断的依据，不是忽略代码变化或用户边界的授权。

## 触发与边界

当用户要求按已有方案实施，且计划已说明目标、范围和基本验收方式时使用。

- 没有足以实施的方案，或关键需求决策未定时，转 `requirements-framing`。
- 方案涉及跨模块、数据流、权限或契约，且尚未分析影响时，转 `change-impact-analysis`。
- 只需要评审、调研或撰写方案时，不使用本 Skill。

不要求创建工作树、提交、推送或拉取请求。自主启动子 Agent 遵循工程协作入口的授权边界：只读或独立验证可并行；实施任务仅在隔离工作区可用，或文件所有权、输入输出和集成顺序明确时并行，否则由主 Agent 串行实施。

## 实施过程

1. **复核可执行性**：读取方案、相关规则和验收条件；刷新工作区状态，重新核对目标文件、直接依赖和相关测试。方案与当前代码冲突时，不按旧假设直接实施。
2. **确定下一切片**：选择最小且可独立验证的改动；将配置、测试和文档工作纳入其所属交付，而不是拆成无验证价值的步骤。
3. **实施并即时验证**：功能或 Bug 按 `test-driven-change` 的策略执行；每个切片完成后运行其最相关的测试、检查或业务路径验证。
4. **处理偏差**：根因未明转 `systematic-debugging`；发现未分析的影响转 `change-impact-analysis`；出现会改变业务行为、范围或验收的未决决策转 `requirements-framing`。没有可靠方案时停止并说明原因。
5. **完成交付**：全部切片完成后，按风险调用 `verification-gate`；需要独立只读审查时调用 `code-review`。

## 完成标准

已确认每个方案交付都有相应实现和验证证据；未实施项、偏差、假设和未验证内容均已明确。不得仅因计划中的步骤已勾选就宣称完成。
