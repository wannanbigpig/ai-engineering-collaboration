---
name: ci-triage
description: "定位远程 CI 流水线失败；仅在根因未明时转本地调试。"
license: MIT
compatibility: universal
metadata:
  version: 1.7.2
---

# CI/构建流水线失败定位

定位 CI 或构建失败的类型、根因和修复计划。未获实施授权时只读分析。

## 流程

1. **识别 provider**：核对 GitHub Actions、GitLab CI 或 Jenkins 等远程 provider；仅不熟悉该 provider 的日志获取方式时读取 [references/providers.md](references/providers.md)。本地构建失败且根因未明时才需要 `systematic-debugging`，根因已明时在已有授权内直接处理。
2. **获取失败证据**：先读取失败步骤、完整异常链及必要前后文，记录 job/stage、命令、commit、环境和退出码；证据不足再扩大日志范围，不只看折叠摘要。
3. **分类失败**：区分代码（编译/测试/Lint/类型）、环境（runner/工具链/资源/缓存/超时）、依赖（解析/冲突/registry/锁文件）和外部服务（API/数据库/网络/凭证）。
4. **提取证据**：保留失败命令、错误消息和最小上下文，避免只凭最后一行判断。
5. **给出计划**：说明根因依据、修改点、验证命令和回滚边界；证据不足时标记待确认。

## 授权边界

纯归因请求只读；用户已要求修复时在原范围内继续最小修复，不重复询问实施授权。证据不足的结论标记未验证；只有仍需本地复现或根因实验时需要 `systematic-debugging`，未知共享行为或契约影响才需要影响分析。由入口统一安排下一阶段；独立使用时以当前能力推进，不因规则引用自动加载专项。不得为诊断擅自重跑部署或其他有外部副作用的 job。
