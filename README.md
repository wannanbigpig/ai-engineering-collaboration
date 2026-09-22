# AI Engineering Collaboration Skills

一组面向真实工程任务的可组合 Agent Skills。单一明确工作流可直接使用对应专项；`ai-engineering-collaboration` 只统筹确需跨多个专项阶段的任务。

当前仓库版本：[1.7.3](VERSION)。仓库内全部 10 个 Skill 使用同一版本号；本地版本号不代表已发布或已更新用户级安装。

## 适合解决什么

- 已有方案需要在最新代码上分步实施。
- 本地 Bug、测试、构建、性能或集成问题需要定位根因。
- 跨模块、数据流、权限或契约改动需要先评估影响。
- 需要需求定界、测试先行、CI 归因、代码审查或发布前验证。

它不是代码生成框架、MCP Server 或项目规则的替代品。项目中的 `AGENTS.md`、`AGENTS.override.md`、`CLAUDE.md` 仍优先于 Skill 指令。

## 安装

三种方式按**安装范围**选择，通常选一种即可：

| 目标 | 方式 | 前置条件 | 写入范围 |
| --- | --- | --- | --- |
| 不克隆仓库，快速安装 | [`npx skills`](#方式一npx-安装不克隆) | Node.js | 由 `skills` CLI 与当前 Harness 的交互/参数决定 |
| 当前用户全量安装 | [`bootstrap --scope user`](#方式二用户级脚本安装) | 克隆本仓库、Python 3.9+ | `~/.agents/skills/`，以及 Claude Code、Gemini、ZCode 的兼容软链接 |
| 初始化单个项目 | [`bootstrap --target …`](#方式三项目级脚本安装) | 克隆本仓库、Python 3.9+ | 项目的 `.agents/skills/`、兼容软链接、`AGENTS.md` 受管区块，并按条件更新 `.gitignore` |

- **`npx skills`**：走开源 [skills](https://github.com/vercel-labs/skills) CLI，不克隆本仓库也能装；适合只要 Skill、或已习惯该生态的用户。安装目录、是否建 symlink、覆盖哪些 Agent 由 CLI 决定。
- **`bootstrap_project.py`**：本仓库自带脚本，写入位置固定、可 `--dry-run` 预览，适合需要 `.agents/skills/` 单副本 + 多工具软链接、或同时改 `AGENTS.md` 的场景。

### 方式一：npx 安装（不克隆）

```bash
# 列出本仓库可安装的 Skill（不写入）
npx skills@latest add wannanbigpig/ai-engineering-collaboration --list

# 全部 10 个 Skill → 当前项目（CLI 默认项目作用域，会提示确认 Agent）
npx skills@latest add wannanbigpig/ai-engineering-collaboration --all

# 全部 10 个 Skill → 用户级全局，跳过交互
npx skills@latest add wannanbigpig/ai-engineering-collaboration --all --global --yes

# 只装入口 + 部分专项，并指定 Agent（可多个）
npx skills@latest add wannanbigpig/ai-engineering-collaboration \
  --skill ai-engineering-collaboration code-review verification-gate \
  --agent claude-code codex --yes

# 不安装，先看某个 Skill 的用途（生成提示词）
npx skills@latest use wannanbigpig/ai-engineering-collaboration --skill code-review
```

常用后续命令：

```bash
npx skills@latest list --global          # 查看已安装
npx skills@latest update --global --yes  # 升级已装 Skill
npx skills@latest remove --global --all  # 卸载由 skills CLI 装入的内容
```

说明：

- `--all` 等价于 `--skill '*' --agent '*' --yes`：全部 Skill 装到 CLI 检测到的全部 Agent。
- **项目作用域**写入各 Agent 的项目目录（如 `.claude/skills/`、`.agents/skills/` 等）；**`--global`** 写入对应 `~/…/skills/`。具体路径见 [skills CLI 文档](https://github.com/vercel-labs/skills)。
- 默认多用 symlink 指向一份规范副本；不支持 symlink 时可加 `--copy`。
- 安装不等于授予额外权限：装完后请打开 `SKILL.md` 及其 `references/`、脚本做必要审查。
- 该 CLI 的升级/卸载与本仓库 `bootstrap_project.py` 互不感知；若两边装到同一路径且内容不同，可能需先手动清理再装。

### 方式二：用户级脚本安装

将完整 10 个 Skill 装到当前用户，并为常见工具建兼容软链接；**不修改任何项目文件**：

```bash
# 预览
python3 scripts/bootstrap_project.py --scope user --dry-run

# 安装
python3 scripts/bootstrap_project.py --scope user

# 可选：先打印 Custom Instructions，再装 Skills（指令仍需手动粘贴到 Codex）
python3 scripts/bootstrap_project.py --scope user --print-custom-instructions
```

写入范围：`~/.agents/skills/`，以及 `~/.claude/skills/`、`~/.gemini/skills/`、`~/.zcode/skills/` 的相对软链接。Codex、OpenCode、Cursor 本地版直接发现 `~/.agents/skills/`。

### 方式三：项目级脚本安装

在仓库根目录，把 Skills 初始化进另一个项目：

```bash
# 预览
python3 scripts/bootstrap_project.py --target /absolute/path/to/project --dry-run

# 安装
python3 scripts/bootstrap_project.py --target /absolute/path/to/project

# 需要将 .aitasks/ 纳入版本控制时
python3 scripts/bootstrap_project.py --target /absolute/path/to/project --track-aitasks
```

除复制 Skills 与兼容链接外，还会：只维护 `AGENTS.md` 中受管标记区块；默认向 `.gitignore` 添加 `.aitasks/`（已跟踪或历史上曾删除该规则时跳过并说明原因）。

脚本**不会**覆盖内容不同的同名 Skill（不是自动升级器）；冲突会在写入前以非零退出停止。完整写入边界、Gemini `context.fileName`、安装验证命令见 [项目初始化与 Custom Instructions](docs/project-bootstrap.md)。

### 安装后

1. **重启或刷新** Agent 会话，使 Skill 生效。
2. **可选但推荐**：配合 Custom Instructions（见下节），把跨项目工程底线粘贴到客户端设置。
3. **确认可发现**：在会话中显式点名入口或某个专项（见下方「使用」）；文件存在不等于 Harness 已加载。

## 使用

任务确需跨多个专项阶段时，明确调用入口：

```text
请使用 ai-engineering-collaboration 处理这个任务：
<任务描述>
```

入口会按剩余缺口选择必要专项；单一明确任务直接处理或使用对应专项 Skill。只安装入口也可以使用，但缺少的专项 Skill 无法被加载，入口只能采用通用最小流程。

仓库提供标准 `SKILL.md`，并为 Codex 提供可选的 `agents/openai.yaml` UI 元数据；其他 Harness 可忽略该文件。

### 配合 Custom Instructions

Skill 与客户端 **Custom Instructions**、项目 **`AGENTS.md`** 是三层互补，不是三选一：

| 层级 | 作用域 | 内容侧重 | 典型载体 |
| --- | --- | --- | --- |
| Custom Instructions | 当前客户端账户 / 全局会话 | 跨项目都要生效的短底线：中文回复、规则优先级、何时用入口、何时记 todo/经验 | Codex 等设置里的 Custom Instructions |
| 项目规则 | 单个仓库 | 技术栈、测试命令、领域与部署约束；更具体路径规则优先 | `AGENTS.md` / `AGENTS.override.md` / `CLAUDE.md` |
| Skill | 按任务触发或显式点名 | 完整工作流与边界（审查格式、调试步骤、维护 CLI 等） | 已安装的 `skills/*/SKILL.md` |

**分工要点**：

- **Custom Instructions** 负责「默认怎么干活、什么时候想起用哪个 Skill」；不要把某个 Skill 的长流程整段贴进去，细节留给 `SKILL.md`。
- **项目 `AGENTS.md`** 负责仓库私有约束。入口与 Custom Instructions 都要求：适用的项目规则优先于 Skill 指令；更具体路径规则优先。
- **Skill** 在任务命中或用户点名时加载；只装 Custom Instructions、不装 Skill，只会得到底线，没有专项流程。

**怎么拿到并粘贴指令**：

```bash
# 仅打印文本（需能运行本仓库脚本；可先克隆仓库）
python3 scripts/bootstrap_project.py --print-custom-instructions

# 打印指令，并同时做用户级 Skill 安装（粘贴仍须你手动完成）
python3 scripts/bootstrap_project.py --scope user --print-custom-instructions
```

1. 将输出整段粘贴到 Codex：**Settings → Custom Instructions**（或其他客户端对应的全局指令入口）。
2. 保存后**开新会话或刷新**，确认指令已生效。
3. 再按上文任一方式安装 Skill，并点名验证入口可加载。

未克隆仓库、只用 `npx skills` 的用户：Custom Instructions **不会**随 `npx` 写入客户端设置。可先临时克隆本仓库执行上述 `--print-custom-instructions`，或从 [docs/project-bootstrap.md](docs/project-bootstrap.md) 中的 `# Engineering defaults` 全文复制后粘贴；Skill 仍用 `npx` 安装即可。

脚本**不会**自动改写 Codex 设置或全局 `AGENTS.md`，只负责打印。项目级 `--target` 额外把受管工程区块写进目标项目的 `AGENTS.md`，与账户级 Custom Instructions 叠加使用：全局底线进指令，仓库细节进 `AGENTS.md`。完整说明见 [项目初始化与 Custom Instructions](docs/project-bootstrap.md)。

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
