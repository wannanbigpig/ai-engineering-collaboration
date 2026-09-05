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

## 项目初始化脚本测试

```bash
python3 -m unittest -v tests/test_bootstrap_project.py
```

测试在临时 Git 项目中验证首次安装、重复运行、dry-run、冲突拒绝、`.aitasks` 跟踪选项、Custom Instructions 输出，以及 Gemini 链接的创建、幂等、相同副本保留、冲突拒绝和失败指引。GitHub Actions 也运行该测试。

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
