---
name: ci-triage
description: "远程 CI/构建流水线失败的 provider、日志与代码/环境/依赖/外部服务归因；本地构建问题使用 systematic-debugging；未授权不改代码。Triage remote CI/build pipeline failures; use systematic-debugging for local builds; classify causes and do not edit without authorization."
license: MIT
compatibility: universal
metadata:
  version: 1.0.0
---

# CI/构建流水线失败定位

定位 CI 或构建失败的类型、根因和修复计划。未获实施授权时只读分析。

## 流程

1. **识别 provider**：确认 GitHub Actions、GitLab CI 或 Jenkins 等远程 provider；provider 细节见 [references/providers.md](references/providers.md)。本地构建失败转由 `systematic-debugging` 处理。
2. **获取完整日志**：记录 job/stage、命令、commit、环境和退出码，不只看折叠摘要。
3. **分类失败**：区分代码（编译/测试/Lint/类型）、环境（runner/工具链/资源/缓存/超时）、依赖（解析/冲突/registry/锁文件）和外部服务（API/数据库/网络/凭证）。
4. **提取证据**：保留失败命令、错误消息和最小上下文，避免只凭最后一行判断。
5. **给出计划**：说明根因依据、修改点、验证命令和回滚边界；证据不足时标记待确认。

## 授权边界

默认不修改代码；获授权后只做最小修改并重新验证。结论证据按 `verification-gate`，跨文件影响按 `change-impact-analysis`。
