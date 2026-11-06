# 贡献指南

本仓库以标准 `SKILL.md` 为核心。修改应保持每个 `skills/<name>/` 目录可独立分发：相对引用只指向本 Skill 内的 `references/`、`assets/` 或 `scripts/`。

跨 Skill 能力按名称从当前环境发现，存在时才读取其所属资源；不得用跨目录相对链接假定两者一起安装。缺失时的最小回退与代码记录依赖见 [Skill 契约](docs/skill-contracts.md)。

## 修改原则

- `description` 说明“做什么”和“何时使用”，避免与相邻 Skill 争夺同一触发场景。
- 正文只保留真正会改变 Agent 决策的边界、步骤和完成条件；详细材料放入按需读取的资源。
- 调整触发、授权或阶段规则时，同步核对专项与入口是否一致，并更新相关行为场景；不要新增只断言措辞存在的测试来证明行为正确。脚本变更使用输入输出和副作用回归测试。
- 不复制第三方 Skill 的文字、目录结构或品牌；外部项目只可作为可验证的设计参考。
- `.aitasks` 的模板与维护逻辑只由 `aitasks-maintenance` 管理。
- 只读解析与查询的权威源码是 `skills/aitasks-maintenance/scripts/query_aitasks.py`；维护 CLI 直接复用，四个独立消费者中的查询脚本及别名资产是生成副本。修改权威源码或别名后运行 `python3 -B scripts/sync_query_tools.py --write`，不要分别编辑副本；统一校验会检查内容及权限一致。

## 提交前

运行：

```bash
python3 -B scripts/validate_repository.py --tests
```

功能或指令语义有实质变化时，递增仓库级 `VERSION`，同步更新全部 11 个 Skill 的 `metadata.version`，并在 [CHANGELOG.md](CHANGELOG.md) 添加发布说明。使用 `feat:`、`fix:`、`docs:` 或 `refactor:` 前缀提交；提交说明应描述动机和范围。

校验入口按失败退出；离线可用 `--offline`，但官方结构校验仍为未运行。行为变化优先使用受影响场景的新旧版对照，触发调整另看自然请求与负例；未参与调优的保留集在候选冻结后运行。规则所有者与开源设计参考见 [Skill 契约](docs/skill-contracts.md)，不把新增措辞本身当作优化完成。

## 可选元数据

`agents/openai.yaml` 是 Codex 的可选 UI 元数据。修改 Skill 名称、面向用户的用途或默认调用提示时，同步检查其 `display_name`、`short_description` 和 `default_prompt`；不要将 Codex 专属配置写入标准 `SKILL.md`。

## 语言

文档以中文为主；命令、文件名、错误日志和 API 名保持原文。
