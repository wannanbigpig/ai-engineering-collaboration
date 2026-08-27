---
name: test-driven-change
description: "Bug/功能变更的测试先行策略，含明确例外和修复前后验证。Test-first change strategy with explicit exceptions and pre/post-fix verification."
license: MIT
compatibility: universal
metadata:
  version: 1.0.0
---

# 测试先行的变更

为代码变更选择测试策略。测试先行是默认倾向，但不强制所有修改都套用 TDD。

## 策略

- **Bug 修复**：先写能复现且应失败的测试；修复后确认通过并复验原场景。无法自动化时记录手动步骤。
- **新功能**：先明确输入、输出和边界，用行为测试定义契约，再实现。

## 明确例外

配置、脚本、文档、CI、生成文件、探索性原型、一次性实验，以及无法稳定自动化的 UI/视觉/外部系统场景，可以不先写测试，但必须说明原因和验证方式。

## 验证与禁止

- 验证修复前失败、修复后通过（或记录无法运行的证据），并运行相关测试、构建和 Lint。
- 不为覆盖率写无回归捕获力的测试，不删除或弱化已有测试，不把“所有修改强制 TDD”写成绝对规则。
- 证据按 `verification-gate`，影响按 `change-impact-analysis`。
