# AI Engineering Collaboration Skills

一组面向真实工程任务的可组合 Agent Skills。它以 `ai-engineering-collaboration` 为主入口：入口负责发现项目规则、复用必要计划、按证据缺口选择专项阶段，并用当前有效证据完成交付。

当前仓库版本：[1.6.4](VERSION)。仓库内全部 10 个 Skill 使用同一版本号；本地版本号不代表已发布或已更新用户级安装。

## 适合解决什么

- 已有方案需要在最新代码上分步实施。
- 本地 Bug、测试、构建、性能或集成问题需要定位根因。
- 跨模块、数据流、权限或契约改动需要先评估影响。
- 需要需求定界、测试先行、CI 归因、代码审查或发布前验证。

它不是代码生成框架、MCP Server 或项目规则的替代品。项目中的 `AGENTS.md`、`AGENTS.override.md`、`CLAUDE.md` 仍优先于 Skill 指令。

## 快速开始

完整安装会让主入口能够使用全部专项阶段：

```bash
npx skills@latest add wannanbigpig/ai-engineering-collaboration --all
```

安装后重启或刷新你的 Agent 会话，并直接描述任务：

```text
请使用 ai-engineering-collaboration 处理这个任务：
<任务描述>
```

入口会自行决定是否需要需求定界、影响分析、方案实施、调试、测试先行、验证或审查；不需要手动选择下游 Skill。只安装入口也可以使用，但缺少的专项 Skill 无法被加载，入口只能采用通用最小流程。

`skills` CLI 的具体发现目录和自动触发行为由所用 Harness 决定。仓库提供标准 `SKILL.md`，并为 Codex 提供可选的 `agents/openai.yaml` UI 元数据；其他 Harness 可忽略该文件。

如果希望将完整 Skill 组合与最小项目级规则一次安装到某个项目，使用本仓库的初始化脚本：

```bash
python3 scripts/bootstrap_project.py --target /absolute/path/to/your-project
```

脚本不会覆盖内容不同的同名 Skill，并会保留已有 `AGENTS.md` 内容。它还会在项目 `.gemini/skills/` 为每个 Skill 建立指向 `.agents/skills/` 的相对软链接，供 Gemini CLI 发现。账户级 Custom Instructions 需要手动在 Codex 设置中粘贴；完整说明见 [项目初始化与 Custom Instructions](docs/project-bootstrap.md)。

需要让完整 Skill 组合对当前用户的所有项目生效时，运行：

    python3 scripts/bootstrap_project.py --scope user

该模式只写入 ~/.agents/skills/，并在 ~/.gemini/skills/ 建立相对软链接供 Gemini CLI 发现，不修改任何项目文件。

## 工作方式

1. **先确认约束**：读取与目标路径相关的项目规则和经验；初次实现目标模块时建立局部风格基线并复用已有证据。已知文件和局部关系直接检索，尚不明确的结构或跨模块关系在 CodeGraph MCP 可用时优先使用它。
2. **再推进任务**：只有无法从事实推导的关键需求才询问，可合并独立问题；明确的修复授权跨阶段继承。非平凡实施必须先有最小计划，已有会话或文件计划可复用；按项目要求或持久化需要维护 `.aitasks/todo.md`，只读任务不写记录、计数或忽略规则。
3. **以证据收尾**：核对相关状态，只重读变化或缺失的内容；非预期失败才重估，预期失败测试属于正常验证。未变化的代码、依赖、配置和环境对应的通过结果可复用；验证默认使用检查模式，按风险补缺口。
4. **复核结构质量**：修改前建立一次风格基线，修改后核对一次结构，专项复用证据。函数长度只作为信号，拆分需权衡内聚性与人工导航成本；质量指标只报告实际测量。交付格式遵循用户要求，审查先列问题，简短结果可合并栏目。

## Skill 目录

| 类别 | Skill | 作用 |
| --- | --- | --- |
| 主入口 | `ai-engineering-collaboration` | 统筹规则、任务治理、专项阶段和验证 |
| 定界与实施 | `requirements-framing`、`plan-execution`、`test-driven-change` | 收敛关键决策、按方案实施、建立测试闭环 |
| 分析与诊断 | `change-impact-analysis`、`systematic-debugging`、`ci-triage` | 评估影响、定位本地根因、归因远程 CI |
| 质量 | `code-review`、`verification-gate` | 代码审查、收到反馈后的事实核验和交付证据检查 |
| 任务治理 | `aitasks-maintenance` | 维护 todo、经验和归档；带可选 Python 标准库 CLI |

每个 Skill 都可独立安装，相关 `references/`、`assets/` 和可选脚本随其目录分发。主入口的完整协作能力需要所有专项 Skill 同时可被当前 Harness 发现。

## 仓库结构

```text
skills/       # 10 个可独立分发的 Skill
evals/        # 跨 Harness 的行为评测场景与评分规则
docs/         # 可重复验证说明
VERSION       # 唯一发布版本来源
CHANGELOG.md  # 发布记录
```

## 本地验证

```bash
release=$(tr -d '\r\n' < VERSION)
test -n "$release"

for skill in skills/*; do
  test "$(sed -n 's/^  version: //p' "$skill/SKILL.md")" = "$release"
  uvx --from 'skills-ref==0.1.1' agentskills validate "$skill"
done

python3 -m unittest discover -s tests -v

git diff --check
```

`.aitasks` CLI 的 smoke test、[可维护性行为评测](evals/maintainability-scenarios.md)、[工作流边界评测](evals/workflow-boundaries.md)和[成对行为运行器](evals/behavior-evaluation.md)的验证边界见 [docs/verification.md](docs/verification.md)。安装任何第三方 Skill 前，应审查其 `SKILL.md`、脚本、引用资源和配置文件；安装不等于授予额外权限。

本次审查风险与检索范围收敛见 [1.6.4 验收结果](evals/reports/1.6.4.md)；查询和取证改进见 [1.6.3](evals/reports/1.6.3.md)，更早记录见 [1.6.2](evals/reports/1.6.2.md)、[1.6.1](evals/reports/1.6.1.md) 和 [1.6.0](evals/reports/1.6.0.md)。

## 发布与贡献

发布时递增 `VERSION`，同步更新全部 Skill 的 `metadata.version`，并更新 [CHANGELOG.md](CHANGELOG.md)。贡献约定见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可证

[MIT](LICENSE)
