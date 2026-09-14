# 验证说明

本仓库可自动验证 Skill 结构、版本一致性和 Markdown 空白；不同 Agent Harness 的发现与自动触发行为需要在目标环境中人工确认。

## 本地与 CI 校验

```bash
release=$(tr -d '\r\n' < VERSION)
test -n "$release"

for skill in skills/*; do
  test "$(sed -n 's/^  version: //p' "$skill/SKILL.md")" = "$release"
  uvx --from 'skills-ref==0.1.1' agentskills validate "$skill"
done

git diff --check
```

GitHub Actions 运行同一版本一致性检查和 `agentskills validate`。这只能验证文件结构，不代表某个 Harness 已实际发现、加载或执行了 Skill。

## 单元测试

```bash
python3 -m unittest discover -s tests -v
```

测试在临时 Git 项目中验证首次安装、重复运行、dry-run、冲突拒绝、`.aitasks` 跟踪选项、Custom Instructions 输出，以及 Gemini 链接的创建、幂等、相同副本保留、冲突拒绝和失败指引；质量契约测试还会确认可维护性规则仍由对应 Skill 承担。GitHub Actions 运行完整测试发现命令。

## `.aitasks` CLI smoke test

在临时项目中运行，不要对真实项目直接使用 `cleanup --apply`：

```bash
python3 skills/aitasks-maintenance/scripts/maintain_aitasks.py --project-root /tmp/example-project status
python3 skills/aitasks-maintenance/scripts/maintain_aitasks.py --project-root /tmp/example-project find-lessons --query "关键词"
python3 skills/aitasks-maintenance/scripts/maintain_aitasks.py --project-root /tmp/example-project cleanup
```

确认 `cleanup` 默认只预览。需要验证写入时，在临时 fixture 中使用 `--force --apply`，检查活动记录被移入 `archive/`，且重复执行不会重复追加。

## Harness 人工验证

安装到目标 Harness 后，重启会话并确认：

1. Skill 可被列出或显式调用。
2. `ai-engineering-collaboration` 能发现同一安装范围内的专项 Skill。
3. `agents/openai.yaml` 只影响 Codex UI，不影响其他 Harness 读取标准 `SKILL.md`。

未在具体 Harness 中实际执行时，应报告“未验证”，不要将目录或静态检查写成运行时验证。

## 可维护性行为评测

[可维护性行为评测场景](../evals/maintainability-scenarios.md)覆盖复用已有实现、影响分析、错误处理、量化证据、避免过度拆分、沿用后端主流风格、无设计稿时沿用现有 UI 和无关修改保护。它们用于验证 Skill 对 Agent 实际行为的影响，不由静态单元测试替代。

在每个目标 Harness 中分别执行：

1. 安装当前版本的全部 Skill，并为每个场景建立新的临时 Git fixture。
2. 使用场景中的用户请求启动新会话，不额外泄露评分项。
3. 保存提示、工具调用、最终 diff、验证输出和最终回复，逐项核对“必须观察到”与“不得出现”。
4. 记录 Harness、模型、Skill 版本、fixture commit 和日期；存在禁止项或缺少工具证据时判定失败。

仓库目前不绑定任一 Harness 的自动运行接口，因此场景定义与质量契约可自动验证，跨 Harness 行为结果仍须实际执行后报告。
