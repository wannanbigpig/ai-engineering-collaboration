# AI Engineering Collaboration Skills

一组面向真实工程任务的可组合 Agent Skills。单一明确工作流可直接使用对应专项；`ai-engineering-collaboration` 只统筹确需跨多个专项阶段的任务。

当前仓库版本：[1.7.1](VERSION)。仓库内全部 10 个 Skill 使用同一版本号；本地版本号不代表已发布或已更新用户级安装。

## 适合解决什么

- 已有方案需要在最新代码上分步实施。
- 本地 Bug、测试、构建、性能或集成问题需要定位根因。
- 跨模块、数据流、权限或契约改动需要先评估影响。
- 需要需求定界、测试先行、CI 归因、代码审查或发布前验证。

它不是代码生成框架、MCP Server 或项目规则的替代品。项目中的 `AGENTS.md`、`AGENTS.override.md`、`CLAUDE.md` 仍优先于 Skill 指令。

## 安装

以下三种方式是不同安装范围的选择，通常选一种即可：

| 目标 | 使用方式 | 写入范围 |
| --- | --- | --- |
| 不克隆仓库，快速安装 Skills | `npx skills@latest add wannanbigpig/ai-engineering-collaboration --all` | 由 `skills` CLI 和当前 Harness 的选择决定 |
| 从当前仓库安装给当前用户 | `python3 scripts/bootstrap_project.py --scope user` | `~/.agents/skills/`，以及 Claude Code、Gemini、ZCode 的兼容软链接 |
| 从当前仓库初始化一个项目 | `python3 scripts/bootstrap_project.py --target /absolute/path/to/project` | 项目的 `.agents/skills/`、各工具兼容软链接、`AGENTS.md` 受管区块，并按条件更新 `.gitignore` |

`npx skills` 适合只安装 Skill；具体安装目录和自动触发行为由 CLI 与 Harness 决定。本仓库的 `bootstrap_project.py` 适合需要确定写入位置，或需要同时配置多个本地 Agent 工具的场景。脚本以 `.agents/skills/` 为唯一副本：Codex、OpenCode 和 Cursor 本地版可直接发现它，Claude Code、Gemini 和 ZCode 通过各自目录下的软链接使用同一份内容。使用脚本前需要先克隆本仓库，并在仓库根目录执行。

建议先预览脚本将要进行的修改：

```bash
# 用户级安装预览
python3 scripts/bootstrap_project.py --scope user --dry-run

# 项目级初始化预览
python3 scripts/bootstrap_project.py --target /absolute/path/to/project --dry-run
```

用户级安装不会修改任何项目文件。项目级初始化会保留 `AGENTS.md` 中不属于受管区块的内容；默认将 `.aitasks/` 加入 `.gitignore`，可用 `--track-aitasks` 禁止新增该规则。

脚本不会覆盖内容不同的同名 Skill，因此它不是自动升级器。遇到冲突时会在写入前停止，需要先审查并手动处理已安装版本。完整的写入边界、Custom Instructions、Gemini CLI 配置和安装验证见 [项目初始化与 Custom Instructions](docs/project-bootstrap.md)。

## 使用

安装后重启或刷新 Agent 会话。任务确需跨多个专项阶段时，可以明确调用入口：

```text
请使用 ai-engineering-collaboration 处理这个任务：
<任务描述>
```

入口会按剩余缺口选择必要专项；单一明确任务直接处理或使用对应专项 Skill。只安装入口也可以使用，但缺少的专项 Skill 无法被加载，入口只能采用通用最小流程。

仓库提供标准 `SKILL.md`，并为 Codex 提供可选的 `agents/openai.yaml` UI 元数据；其他 Harness 可忽略该文件。

## 工作方式

1. **先确认约束**：读取与目标路径相关的项目规则和经验；初次实现目标模块时建立局部风格基线并复用已有证据。已知文件和简单字面关系直接检索；项目有可用 `.codegraph/` 索引时，结构和跨模块关系优先用 CodeGraph MCP，MCP 不可用再用 CLI，均不可用则回退常规检索。
2. **再推进任务**：只有无法从事实推导的关键需求才询问，可合并独立问题；明确的修复授权跨阶段继承。入口按协作需要选择，非平凡实施按风险形成最小计划，已有会话或文件计划可复用。编辑项目代码时自动记录一条任务 todo；用户明确要求记录经验时立即记录，否则同一问题第二次实质出现时自动沉淀；记录达到阈值时自动归档清理。只读任务不写记录、计数或忽略规则。
3. **以证据收尾**：核对相关状态，只重读变化或缺失的内容；非预期失败才重估，预期失败测试属于正常验证。未变化的代码、依赖、配置和环境对应的通过结果可复用；验证默认使用检查模式，按风险补缺口。
4. **复核结构质量**：修改前建立一次风格基线，修改后核对一次结构，专项复用证据。函数长度只作为信号，拆分需权衡内聚性与人工导航成本；质量指标只报告实际测量。交付格式遵循用户要求，审查先列问题，简短结果可合并栏目。

## Skill 目录

| 类别 | Skill | 作用 |
| --- | --- | --- |
| 跨阶段入口 | `ai-engineering-collaboration` | 只统筹需要多个专项协同的工程任务 |
| 定界与实施 | `requirements-framing`、`plan-execution`、`test-driven-change` | 收敛关键决策、按方案实施、建立测试闭环 |
| 分析与诊断 | `change-impact-analysis`、`systematic-debugging`、`ci-triage` | 评估影响、定位本地根因、归因远程 CI |
| 质量 | `code-review`、`verification-gate` | 代码审查、收到反馈后的事实核验和交付证据检查 |
| 任务治理 | `aitasks-maintenance` | 维护 todo、经验和归档；带可选 Python 标准库 CLI |

每个 Skill 都可独立安装，相关 `references/`、`assets/` 和可选脚本随其目录分发。跨阶段入口的完整协作能力需要所有专项 Skill 同时可被当前 Harness 发现。

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
