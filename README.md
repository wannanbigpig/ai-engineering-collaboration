# AI Engineering Collaboration Skills

一组面向真实工程任务的可组合 Agent Skills。单一明确任务直接处理或使用对应专项；需要跨多个专项阶段时，再使用 `ai-engineering-collaboration` 统筹。

当前源码版本：[1.7.15](VERSION)，共 11 个 Skill。源码版本、已安装副本和当前会话实际加载的版本分别核对。

## 从任务开始

| 你要做什么 | 可使用的 Skill |
| --- | --- |
| 审查代码、核实审查反馈 | `code-review` |
| 排查根因未明的本地问题 / 远程 CI 失败 | `systematic-debugging` / `ci-triage` |
| 按已有方案实施 | `plan-execution` |
| 收敛关键需求 / 分析共享影响 | `requirements-framing` / `change-impact-analysis` |
| 选择回归测试策略 / 补足交付证据 | `test-driven-change` / `verification-gate` |
| 设计或改善界面视觉、布局与交互 | `frontend-ui-ux` |
| 维护任务、经验及归档 | `aitasks-maintenance` |
| 协调多个必要阶段 | `ai-engineering-collaboration` |

安装后，在新会话中显式调用，例如：

```text
请使用 code-review 只读审查当前改动，给出有证据的问题与建议。
```

```text
请使用 frontend-ui-ux 改善这个后台列表的视觉层级和操作体验，保留现有功能。
```

前端 Skill 会把页面骨架、视觉规格和交互落实到可运行页面，再检查实际渲染与主流程；开源参考和取舍见[研究说明](docs/frontend-skill-research.md)，实际运行与验证边界见[落地评测](evals/reports/1.7.15-frontend-implementation.md)。

明确局部改字或解释代码不必加载专项。只读评估不会自动转为修复；实施授权在范围内跨阶段继承。技能选择与执行是否正确需要真实场景验证，不能仅凭安装成功判断。

## 安装范围

通常选择一种方式，避免不同安装器管理同一路径：

| 目标 | 方式 | 前置条件与写入范围 |
| --- | --- | --- |
| 为选定客户端安装技能 | [skills CLI](docs/project-bootstrap.md#通过-skills-cli-安装) | 安装 CLI 固定为 `skills@1.7.6`，与本仓库版本分别管理；要求 Node.js ≥22.20.0 |
| 当前用户安装全部技能 | `bootstrap --scope user` | Python 3.9+；写入 `~/.agents/skills/` 和兼容软链接 |
| 初始化单个项目 | `bootstrap --target …` | Python 3.9+；管理项目技能、兼容入口、`AGENTS.md` 受管区块，并按条件更新 `.gitignore` |

```bash
# 不克隆仓库：先查看，再安装指定技能到当前项目的 Codex
npx skills@1.7.6 add wannanbigpig/ai-engineering-collaboration --list
npx skills@1.7.6 add wannanbigpig/ai-engineering-collaboration --skill code-review --agent codex

# 以下 Python 命令均在克隆后的本仓库根目录执行
# 预览用户级完整安装；核对输出后去掉 --dry-run
python3 -B scripts/bootstrap_project.py --scope user --dry-run

# 或预览单个项目初始化
python3 -B scripts/bootstrap_project.py --target /absolute/path/to/project --dry-run
```

脚本默认拒绝覆盖不同的同名 Skill，已有定制须先核对；检查及基线升级见[安装说明](docs/project-bootstrap.md#检查与显式升级)。`skills` CLI 与 bootstrap 不互相接管安装所有权。卸载应限定本仓库来源或明确的 Skill 名，不使用全局 `remove --all`。

安装器需要 Python 3.9+；随包的查询与维护工具需要 Python 3.10+。Skill 正文本身不依赖 Python，工具不可用时按对应 Skill 的手工或降级说明执行。

每个 Skill 的本地资源随自身目录分发。工程入口、审查、调试及影响分析包自带同源只读查询脚本，缺少维护 Skill 时可独立查询，不要求兄弟目录存在；无 Python 时仅取标题与元数据线索，未核实正文保持未验证。使用本仓库工程入口编辑代码或配置下述工程默认指令时，需要让 `aitasks-maintenance` 可被当前客户端发现；只读工具不包含任务和经验写入能力，其他专项可按需安装。

安装后刷新或重启会话，点名核对技能是否可发现。`agents/openai.yaml` 是可选 Codex UI 元数据，其他 Harness 可忽略；兼容状态见[验证说明](docs/verification.md#兼容与生效矩阵)。

## 配合项目规则与 Custom Instructions

Custom Instructions 用来固定跨项目协作底线：减少重复提醒、重复确认、无关流程和无依据的验证声明，并统一任务记录与只读边界。它定义“如何协作”；项目规则定义“这个项目如何工作”，Skill 再提供按需执行的方法。

| 层级 | 负责内容 |
| --- | --- |
| 个人全局规则 / 客户端 Custom Instructions | 回复语言、授权延续、调查与验证原则、任务和经验的记录边界 |
| 项目 `AGENTS.md`、`CLAUDE.md`、`GEMINI.md` 等 | 技术栈、业务契约、测试命令、部署约束及目录差异 |
| 按需 Skill | 审查、调试、实施或维护的具体工作流 |

### 不同工具放在哪里

以下是 **2026-11-06 按官方文档核对的默认入口**；`~` 表示用户主目录，`<project>` 表示当前项目或 Workspace。只需要单个项目生效时，合并到项目规则文件；跨项目复用时，选择该工具支持的个人全局入口。保留已有规则，不整份覆盖。

| 工具 | 个人全局规则 | 项目规则 | 官方说明 |
| --- | --- | --- | --- |
| Codex（本地） | `~/.codex/AGENTS.md`；自定义 `CODEX_HOME` 时用 `$CODEX_HOME/AGENTS.md` | `<project>/AGENTS.md`，适用子目录可用 `AGENTS.override.md` | [AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md) |
| Claude Code | `~/.claude/CLAUDE.md` | `<project>/CLAUDE.md` 或 `<project>/.claude/CLAUDE.md` | [Memory](https://code.claude.com/docs/en/memory) |
| Gemini CLI | `~/.gemini/GEMINI.md` | `<project>/GEMINI.md`；文件名可配置 | [Context files](https://geminicli.com/docs/cli/gemini-md/) |
| OpenCode | `~/.config/opencode/AGENTS.md` | `<project>/AGENTS.md` 及适用目录规则 | [V1](https://opencode.ai/docs/rules/)、[V2](https://opencode.ai/v2/docs/instructions/) |
| Cursor 编辑器 | 设置中的 **User Rules** | `<project>/AGENTS.md` 或 `<project>/.cursor/rules/*.mdc` | [Rules](https://cursor.com/docs/rules) |
| ZCode | `~/.zcode/AGENTS.md` | 当前 Workspace 根目录的 `AGENTS.md` | [项目指令](https://zcode.z.ai/cn/docs/agents) |

`~/.agents/skills/` 是 Skill 目录，不能据此推断 `~/.agents/AGENTS.md` 会被这些工具自动读取。若把后者作为个人共享源，需要显式引用，或连接到各工具支持的原生规则入口；仅把文件放在那里不会建立通用的全局规则。

- **复用项目规则**：Claude Code 可在根 `CLAUDE.md` 中写 `@AGENTS.md`；Gemini 可在根 `GEMINI.md` 中写 `@./AGENTS.md`，或按[安装说明](docs/project-bootstrap.md#各-agent-工具的发现方式)配置 `context.fileName`。选择一种引入方式，避免重复加载。
- **Codex 覆盖优先级**：同目录存在非空 `AGENTS.override.md` 时，优先于 `AGENTS.md`；全局目录取自 `CODEX_HOME`，未设置时才是 `~/.codex`。
- **发现规则有版本差异**：Claude Code v2.1.277+ 已有条件原生读取项目 `AGENTS.md`；OpenCode V1/V2 的 `CLAUDE.md` 兼容规则不同。ZCode 只拼接全局与当前 Workspace 两份，不自动遍历多层目录。以表中对应版本文档为准。
- **核对生效**：合并规则后刷新或新开会话，核对实际加载来源。安装 Skill 不会自动写入这些全局文件或客户端设置；规则存在也不等于所有客户端已加载。

### 推荐自定义规则

下面只保留常驻底线，专项细节交给 Skill；项目规则补充本项目差异。使用任务/经验记录规则时，需要让 `aitasks-maintenance` 可被当前客户端发现。

```md
# Engineering defaults

- 使用中文回复；代码、命令、文件名、错误日志和 API 名称保持原文。
- 修改前读取并遵守当前工具及任务路径适用的规则，如 `AGENTS.md`、`AGENTS.override.md`、`CLAUDE.md`、`GEMINI.md`；更具体路径规则优先。
- 在已授权范围内持续推进，切换阶段或 Skill 不重复请求授权。只询问无法从现有证据推导、且会改变交付的关键决策；只暂停依赖答案的部分，超出已有授权的动作先确认。
- 项目有 `.aitasks/` 时，在任务开始、范围变化或新根因确认后，按模块、符号或错误码查询相关经验与 todo。优先用只读工具取有界摘要，必要时按 ID 读单条；工具不可用时只定位少量标题与元数据，无法核实的正文及适用性标为未验证，不临时编写经验解析器。不默认整篇加载或更新计数；本会话复用未变结果，新会话重新查询。
- 只核对会改变结论或交付的关键前提；保持独立判断，区分已验证事实、推断与未验证项。时效性或高风险结论优先查证，实质分歧说明依据和风险。
- 先调查相关实现、约束及工作区已有改动；Bug 确定根因后做当前任务所需的最小修复，保留无关修改。沿用既有工具、设施和风格；校验、兜底、兼容分支与抽象须有具体依据，保留必要的权限、事务、并发与幂等保障；生成物修改源定义后再生成。
- 修改后按风险执行最小必要验证；复用相关输入和环境未变的有效结果，不为纯文档变更运行无关测试。未经验证不得宣称通过，无法验证时说明边界。
- 单一明确工程任务直接处理或使用对应专项 Skill；确需跨多个专项阶段统筹，或用户明确指定时，使用 `ai-engineering-collaboration`，不机械串联全部流程。
- 编辑项目代码时，不论是否使用入口 Skill，都用 `aitasks-maintenance` 创建或复用本任务的一条 todo，完成后写入实际结果并更新状态；仅维护 `.aitasks` 不递归创建 todo。
- 用户明确要求记录经验时立即记录，未证实原因标为“未确认”；否则只观察已验证且可复用的问题，二次独立任务确认同因后再沉淀。先检索同类记录并复用原 ID，实际采用经验解决问题后才计数，查询不算复用。
- 只读或明确不修改文件时，不改项目文件，也不写观察、todo、经验、计数、忽略规则或归档。允许写入 todo 或经验后按维护规则检查阈值；达到时先归档再移出，不自动删除归档，工具已检查则不重复执行。
- 项目根目录有 `.codegraph/` 且索引可用时，理解未知结构、调用链或改动影响优先用 CodeGraph MCP；MCP 不可用且 CLI 可用时改用 CLI，首次使用先运行 `codegraph status`。已知路径或简单文本直接检索，图谱不足时回退常规工具，关键结论核对代码与测试，不自动执行 `codegraph init`。
```

也可在本仓库根目录打印同一份文本，再合并到所选规则文件或客户端设置：

```bash
python3 -B scripts/bootstrap_project.py --print-custom-instructions
```

该命令只输出文本，不修改个人配置。`npx skills` 也不会代写全局指令；`bootstrap --target` 只更新项目 `AGENTS.md` 的受管区块，保留其他约定。

## 工作原则

- 从相关规则、实现和当前工作区开始，保护已有改动；经验只是线索，关键事实核对当前代码与契约。
- 只询问无法推导且会改变结果的决策，按剩余证据缺口选择专项，复用已有授权与有效验证。
- 代码编辑一任务一条 todo；只读查询不写记录、观察或计数。已确认且可复用的问题按独立任务观察，二次出现再沉淀；用户明确要求记录时立即执行。
- 复用相邻实现与共享设施；校验、兼容分支、抽象和测试均以实际行为或风险为依据。前端设计围绕产品任务，验证实际受影响页面与交互。
- 按风险做必要验证，区分工具测试、真实 Agent 行为与人工复核；不把命令数量或字符预算直接换算成质量或 token 收益。

职责与可选依赖约定见[Skill 契约](docs/skill-contracts.md)。

## 验证与分发

完整校验需要 Python 3.10+、Git 和 `uvx`；以下命令也在本仓库根目录执行。

```bash
# 版本、独立包资源、官方结构校验、差异检查和全部单测；必要步骤失败即非零退出
python3 -B scripts/validate_repository.py --tests

# 离线时只跳过官方结构校验，输出会明确标为未运行
python3 -B scripts/validate_repository.py --offline

# 只读检查安装状态；JSON 不代表当前会话已加载
python3 -B scripts/bootstrap_project.py --scope user --check --json

# 生成独立 ZIP 与内容清单；不上传，拒绝覆盖非空目录
python3 -B scripts/package_skills.py --output /absolute/path/to/new-release-directory
```

最新结构修复、真实失败及新前向样本见 [1.7.14 复查报告](evals/reports/1.7.14-team-review.md)。验证边界与 CI 矩阵见[验证说明](docs/verification.md)，真实场景运行方法见[行为评测](evals/behavior-evaluation.md)。报告保留失败和未验证项，不能将静态通过当作自然触发或视觉效果通过。

历史记录：[1.7.13 工具与观察评测](evals/reports/1.7.13.md)、[1.7.13 团队复查](evals/reports/1.7.13-team-review.md)、[1.7.12 测试方法](evals/reports/1.7.12.md)、[1.7.10 记忆流程](evals/reports/1.7.10-memory-workflow.md)。

```text
skills/       # 可独立安装的技能、资源与可选脚本
scripts/      # 安装、仓库校验与分发工具
evals/        # 行为场景、运行器与验收报告
tests/        # 工具和契约回归测试
docs/         # 安装、职责、兼容与验证说明
VERSION       # 统一源码版本
```

贡献与版本规则见 [CONTRIBUTING.md](CONTRIBUTING.md)，发布变化见 [CHANGELOG.md](CHANGELOG.md)。采用 [MIT](LICENSE) 许可证。
