---
name: systematic-debugging
description: "本地 Bug、测试、构建、性能和集成问题的证据化根因排查；远程 CI 用 ci-triage。Evidence-driven root-cause debugging for local bugs, tests, builds, performance, and integrations; use ci-triage for remote CI."
license: MIT
compatibility: universal
metadata:
  version: 1.3.0
---

# 系统化调试

针对本地 Bug、测试/构建失败、性能异常、集成问题和非预期行为排查根因；证据不足时不跳步。

## 流程

1. **读完整错误**：收集错误、调用栈、日志、版本、输入和环境，不只看首尾几行。
2. **稳定复现**：用现有测试或最小脚本构造可重复场景；不能稳定复现时记录条件、频率和已尝试方式。
3. **比较差异**：检查近期提交、配置、依赖、系统、资源和外部服务，优先核对与问题时间吻合的变化。
4. **跟踪数据流**：从入口沿调用链核对实际实现——已接入 CodeGraph 时优先用于查定义和调用方，不可用或结果不足时改用自身可用的检索工具并打开实际文件确认——记录关键输入输出，定位第一个偏离预期的环节。
5. **提出假设**：只保留一个可证伪根因，并写出假设成立时应观察到的现象；证据不足先补证据。
6. **最小实验**：只改一个变量，运行一次最小验证；假设不成立则回到证据收集。
7. **回归保护**：为已确认根因添加修复前失败、修复后通过的测试；无法自动化时记录手动步骤。
8. **最小修复与复验**：只改根因范围，复现原问题并运行相关测试、构建或 Lint，保持既有输入输出边界。

## 边界

完成声明与未验证标记按 `verification-gate`；测试策略按 `test-driven-change`；跨文件影响按 `change-impact-analysis`。
