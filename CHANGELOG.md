# 变更记录

仓库使用 [VERSION](VERSION) 作为唯一发布版本来源；全部 Skill 的 `metadata.version` 必须与它一致。本记录按仓库发布版本倒序维护。

## 1.2.0 - 2026-08-27

- 初始化脚本新增 --scope user，可安全将完整 Skill 组合安装到 ~/.agents/skills/，且不会改动项目文件。

## 1.1.0 - 2026-08-27

- 新增项目初始化脚本，可安全复制完整 Skill 组合、安装受管 `AGENTS.md` 区块并按条件配置 `.aitasks/` 忽略规则。
- 新增项目初始化与 Codex Custom Instructions 文档，以及标准库自动化验证。

## 1.0.0 - 2026-08-27

- 建立 10 个可组合的工程协作 Skill，并以 `ai-engineering-collaboration` 作为任务主入口。
- 提供需求定界、方案实施、影响分析、系统化调试、测试先行、验证、审查、CI 归因与 `.aitasks` 维护能力。
- 为每个 Skill 提供 Codex 可选 UI 元数据，并以 `VERSION`、本地验证和 CI 保持发布版本一致。
- 收敛发布文档为 README、验证说明与贡献指南；移除无法由仓库持续验证的外部 Harness 兼容性矩阵。
