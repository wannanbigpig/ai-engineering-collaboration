# AI Engineering Collaboration Skills

一组面向真实工程任务的可组合 Agent Skills。单一明确任务直接处理或使用对应专项；需要跨多个专项阶段时，再使用 `ai-engineering-collaboration` 统筹。

当前源码版本：[1.7.12](VERSION)，共 11 个 Skill。源码版本、已安装副本和当前会话实际加载的版本分别核对。

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

明确局部改字或解释代码不必加载专项。只读评估不会自动转为修复；实施授权在范围内跨阶段继承。技能选择与执行是否正确需要真实场景验证，不能仅凭安装成功判断。

## 安装范围

通常选择一种方式，避免不同安装器管理同一路径：

| 目标 | 方式 | 前置条件与写入范围 |
| --- | --- | --- |
| 安装选定技能和客户端 | [skills CLI](docs/project-bootstrap.md#通过-skills-cli-安装) | 示例固定 `skills@1.7.6`，要求 Node.js ≥22.20.0；目录由作用域及 Agent 参数决定 |
| 当前用户安装全部技能 | `bootstrap --scope user` | Python 3.9+；写入 `~/.agents/skills/` 和兼容软链接 |
| 初始化单个项目 | `bootstrap --target …` | Python 3.9+；管理项目技能、兼容入口、`AGENTS.md` 受管区块，并按条件更新 `.gitignore` |

```bash
# 不克隆仓库：先查看，再安装指定技能到当前项目的 Codex
npx skills@1.7.6 add wannanbigpig/ai-engineering-collaboration --list
npx skills@1.7.6 add wannanbigpig/ai-engineering-collaboration --skill code-review --agent codex

# 已克隆本仓库：预览用户级完整安装；核对输出后去掉 --dry-run
python3 -B scripts/bootstrap_project.py --scope user --dry-run

# 或预览单个项目初始化
python3 -B scripts/bootstrap_project.py --target /absolute/path/to/project --dry-run
```

脚本默认拒绝覆盖不同的同名 Skill，已有定制须先核对；检查及基线升级见[安装说明](docs/project-bootstrap.md#检查与显式升级)。`skills` CLI 与 bootstrap 不互相接管安装所有权。卸载应限定本仓库来源或明确的 Skill 名，不使用全局 `remove --all`。

每个 Skill 的本地资源随自身目录分发。只读经验查询可发现已安装的 `aitasks-maintenance` 并读取其短参考；未安装时定向读取少量有效记录，不要求兄弟目录存在。使用本仓库工程入口编辑代码或配置下述工程默认指令时，需要让 `aitasks-maintenance` 可被当前客户端发现；其他专项可按需安装。

安装后刷新或重启会话，点名核对技能是否可发现。`agents/openai.yaml` 是可选 Codex UI 元数据，其他 Harness 可忽略；兼容状态见[验证说明](docs/verification.md#兼容与生效矩阵)。

## 配合项目规则与 Custom Instructions

| 层级 | 负责内容 |
| --- | --- |
| 客户端 Custom Instructions | 中文回复、授权边界、何时记录任务等跨项目底线 |
| 项目 `AGENTS.md`、`AGENTS.override.md`、`CLAUDE.md` | 技术栈、契约、验证命令及部署约束；更具体路径规则优先 |
| 按需 Skill | 审查、调试、实施或维护的具体工作流 |

```bash
# 只打印待粘贴文本，不修改客户端配置
python3 -B scripts/bootstrap_project.py --print-custom-instructions
```

将输出放入客户端对应的全局指令设置，再开新会话验证。`npx skills` 不会替你写入 Custom Instructions；无需克隆的用户也可从[完整工程默认指令](docs/project-bootstrap.md#codex-custom-instructions)复制。项目初始化只更新 `AGENTS.md` 的受管区块，保留其他项目约定。

## 工作原则

- 从相关规则、实现和当前工作区开始，保护已有改动；经验只是线索，关键事实核对当前代码与契约。
- 只询问无法推导且会改变结果的决策，按剩余证据缺口选择专项，复用已有授权与有效验证。
- 代码编辑一任务一条 todo；只读查询不写记录、观察或计数。已确认且可复用的问题按独立任务观察，二次出现再沉淀；用户明确要求记录时立即执行。
- 复用相邻实现与共享设施；校验、兼容分支、抽象和测试均以实际行为或风险为依据。前端设计围绕产品任务，验证实际受影响页面与交互。
- 按风险做必要验证，区分工具测试、真实 Agent 行为与人工复核；不把命令数量或字符预算直接换算成质量或 token 收益。

职责与可选依赖约定见[Skill 契约](docs/skill-contracts.md)。

## 验证与分发

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

本地脚本、CI 矩阵和真实行为验收的边界见[验证说明](docs/verification.md)。最新优化、测试方法对照与实际失败见 [1.7.12 报告](evals/reports/1.7.12.md)，历史记忆结果见 [1.7.10 报告](evals/reports/1.7.10-memory-workflow.md)；运行方法见[行为评测](evals/behavior-evaluation.md)。报告中的失败和未验证项保留，不能将静态通过当作自然触发或视觉效果通过。

```text
skills/       # 可独立安装的技能、资源与可选脚本
scripts/      # 安装、仓库校验与分发工具
evals/        # 行为场景、运行器与验收报告
tests/        # 工具和契约回归测试
docs/         # 安装、职责、兼容与验证说明
VERSION       # 统一源码版本
```

贡献与版本规则见 [CONTRIBUTING.md](CONTRIBUTING.md)，发布变化见 [CHANGELOG.md](CHANGELOG.md)。采用 [MIT](LICENSE) 许可证。
