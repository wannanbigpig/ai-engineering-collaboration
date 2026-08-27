---
name: change-impact-analysis
description: "跨文件、模块或仓库变更前的调用链、数据流、权限、契约和部署影响分析。Impact analysis before risky changes: trace call chains, data flow, permissions, contracts, and deployment."
license: MIT
compatibility: universal
metadata:
  version: 1.0.0
---

# 变更影响分析

修改前追踪受影响路径、数据流和风险，先分析后实施。

## 追踪清单

按变更类型检查：

- **入口与调用链**：页面/CLI/交互入口、API/命令/事件、Controller/Service/Model 定义及调用方。
- **数据与异步**：读写、校验、转换、Job/事件/队列/定时任务、重试和幂等。
- **边界与契约**：权限、数据范围、租户隔离、输入输出、序列化、错误码、缓存一致性。
- **基础设施与协作**：迁移、索引、跨仓库 reader/writer、测试、部署和回滚。

## 方法与输出

- 从入口沿调用链追踪定义、调用方和数据流；优先使用 CodeGraph，不可用或结果不足时改用自身可用的检索工具。
- 打开并核对实际实现，不根据符号名或单一调用点猜测。
- 输出受影响文件/模块、风险等级、证据和需要额外验证的路径。

## 边界

分析用于规划最小修改，不直接实施；影响不明时说明原因，结论与验证按 `verification-gate` 执行。
