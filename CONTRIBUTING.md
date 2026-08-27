# 贡献指南

本仓库以标准 `SKILL.md` 为核心。修改应保持每个 `skills/<name>/` 目录可独立分发：相对引用只指向本 Skill 内的 `references/`、`assets/` 或 `scripts/`。

## 修改原则

- `description` 说明“做什么”和“何时使用”，避免与相邻 Skill 争夺同一触发场景。
- 正文只保留真正会改变 Agent 决策的边界、步骤和完成条件；详细材料放入按需读取的资源。
- 不复制第三方 Skill 的文字、目录结构或品牌；外部项目只可作为可验证的设计参考。
- `.aitasks` 的模板与维护逻辑只由 `aitasks-maintenance` 管理。

## 提交前

运行：

```bash
release=$(tr -d '\r\n' < VERSION)
test -n "$release"

for skill in skills/*; do
  test "$(sed -n 's/^  version: //p' "$skill/SKILL.md")" = "$release"
  uvx --from 'skills-ref==0.1.1' agentskills validate "$skill"
done

git diff --check
```

功能或指令语义有实质变化时，递增仓库级 `VERSION`，同步更新全部 10 个 Skill 的 `metadata.version`，并在 [CHANGELOG.md](CHANGELOG.md) 添加发布说明。使用 `feat:`、`fix:`、`docs:` 或 `refactor:` 前缀提交；提交说明应描述动机和范围。

## 可选元数据

`agents/openai.yaml` 是 Codex 的可选 UI 元数据。修改 Skill 名称、面向用户的用途或默认调用提示时，同步检查其 `display_name`、`short_description` 和 `default_prompt`；不要将 Codex 专属配置写入标准 `SKILL.md`。

## 语言

文档以中文为主；命令、文件名、错误日志和 API 名保持原文。
