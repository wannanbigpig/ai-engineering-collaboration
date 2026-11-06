# 项目初始化与 Custom Instructions

本仓库有两类配置：项目内可版本管理的 Skill 与 `AGENTS.md`，以及 Codex 客户端账户级的 Custom Instructions。前者可由脚本安全生成；后者属于客户端设置，脚本只能输出待粘贴文本，不能直接修改。脚本仅依赖 Python 3.9+ 标准库；项目安装会使用 Git 检查 `.aitasks` 跟踪状态及忽略规则历史，Git 不可用或检查失败时保守保留 `.gitignore` 并说明原因。

Skill 只在 `.agents/skills/` 保留一份内容。Codex、OpenCode 和 Cursor 本地版可直接发现该目录；脚本另外为 Claude Code、Gemini 和 ZCode 创建兼容软链接。各工具是否自动触发 Skill 仍由自身版本、设置和会话状态决定。

## 通过 skills CLI 安装

无需克隆仓库。以下命令按 2026-11-06 核对的 `skills@1.7.6` 固定，要求 Node.js ≥22.20.0；升级 CLI 时重新核对其选项和作用域。

```bash
npx skills@1.7.6 add wannanbigpig/ai-engineering-collaboration --list

# 安装全部 Skill 到所选 Agent；默认项目范围，用户级加 --global
npx skills@1.7.6 add wannanbigpig/ai-engineering-collaboration --skill '*' --agent codex claude-code

# 部分安装：工程默认指令要求代码记录时同时安装维护 Skill
npx skills@1.7.6 add wannanbigpig/ai-engineering-collaboration --skill code-review aitasks-maintenance --agent codex

# 临时读取并输出使用提示，不安装到永久技能目录
npx skills@1.7.6 use wannanbigpig/ai-engineering-collaboration --skill code-review

npx skills@1.7.6 list --global
```

来源、路径及链接策略以 [固定版本 CLI 文档](https://github.com/vercel-labs/skills/blob/7a5e920bead4b1039a6d6df5d7e1163b7b09423a/docs/commands.md)为准。`--all` 安装还会选择全部检测到的 Agent 并跳过交互，通常优先明确 `--agent`。

卸载前先用 `list --global` 核对来源。锁文件中的 source 确为本仓库时，可定向删除：

```bash
npx skills@1.7.6 remove --global wannanbigpig/ai-engineering-collaboration
```

来源不同或不在 CLI 锁文件中时，交互选择明确技能，不用 `remove --global --all`：该发布版会选中扫描到的全局技能及锁文件技能，并跳过确认，可能影响其他来源。CLI 不接管 bootstrap 安装的所有权；不要用两种安装器交替覆盖同一路径。安装不会自动写入 Custom Instructions。

## 一键安装到所有项目

    python3 scripts/bootstrap_project.py --scope user

该命令将完整 11 个 Skill 安装到当前用户的 `~/.agents/skills/`，并在 `~/.claude/skills/`、`~/.gemini/skills/`、`~/.zcode/skills/` 为每个 Skill 建立指向该目录的相对软链接；内容仍只有 `~/.agents/skills/` 一份副本。它绝不创建或修改 `~/AGENTS.md`、`.gitignore` 或任何项目文件。已有内容相同的 Skill 会跳过；内容不同则终止且不覆盖。

可先预览：

    python3 scripts/bootstrap_project.py --scope user --dry-run

## 一键初始化项目

在本仓库根目录执行：

```bash
python3 scripts/bootstrap_project.py --target /absolute/path/to/your-project
```

脚本会执行以下操作：

1. 将全部 11 个 Skill 复制到目标项目的 `.agents/skills/`，确保主入口可以加载全部专项 Skill。
2. 在目标项目的 `.claude/skills/`、`.gemini/skills/`、`.zcode/skills/` 为每个 Skill 创建指向 `.agents/skills/` 的相对软链接。
3. 创建或更新目标项目根目录的 `AGENTS.md`，仅管理 `ai-engineering-collaboration` 标记包围的区块，保留其余项目规则；有可用 `.codegraph/` 索引时优先使用 CodeGraph，不自动初始化索引。
4. 默认向 `.gitignore` 添加 `.aitasks/`；若该目录已被 Git 跟踪、Git 历史显示该规则曾被移除，或无法核实 Git 状态，则不改动并输出原因。保留已有文件的内容、换行样式和权限。

脚本先检查所有同名 Skill、兼容链接及其目录路径。目标已有内容相同的 Skill 会跳过；受管链接或内容相同的普通副本视为最新并保留原样；内容不同、指向其他位置的链接或其他同名内容则以退出码 `2` 终止，且不会写入任何其他配置。目录路径不是目录或存在悬空目录链接时会在写入前报错；已存在的兼容目录如果通过符号链接重定向，新链接会按实际路径指向规范副本。它不会覆盖用户修改。

首次安装完成后，重启或刷新 Agent 会话。需要跨多个专项阶段统筹的任务可直接点名入口：

```text
请使用 ai-engineering-collaboration 处理：<任务描述>
```

## 各 Agent 工具的发现方式

- **Codex、OpenCode、Cursor 本地版**：直接使用 `.agents/skills/`，不创建重复副本。Cursor Cloud Agent 需要其单独的同步设置，不属于本地安装范围。
- **Claude Code**：通过 `.claude/skills/` 软链接发现。
- **Gemini CLI**：通过 `.gemini/skills/` 软链接发现。
- **ZCode**：通过 `.zcode/skills/` 软链接发现；安装后在设置的 Skills 页面刷新并确认已启用。

项目规则方面，Gemini CLI 默认读取 `GEMINI.md` 而非 `AGENTS.md`；若希望 Gemini 直接复用脚本管理的 `AGENTS.md`，在项目的 `.gemini/settings.json` 中设置：

```json
{
  "context": {
    "fileName": "AGENTS.md"
  }
}
```

该设置会替换默认查找的文件名；需要同时读取两种规则时，可设置 `"fileName": ["AGENTS.md", "GEMINI.md"]`，并避免两份规则互相冲突。使用当前 [Gemini CLI 官方配置](https://geminicli.com/docs/cli/gemini-md/#customize-the-context-file-name) 的 `context.fileName`，不要在 `settings.json` 顶层写 `contextFileName`。较旧版本需核对对应版本的配置与 skills 开关。

## 常用选项

```bash
# 仅预览将要写入的内容
python3 scripts/bootstrap_project.py --target /absolute/path/to/your-project --dry-run

# 需要将 .aitasks/ 纳入版本控制时使用
python3 scripts/bootstrap_project.py --target /absolute/path/to/your-project --track-aitasks

# 输出账户级 Custom Instructions，复制到 Codex 设置中
python3 scripts/bootstrap_project.py --print-custom-instructions

# 先输出指令，再安装用户级 Skills（指令仍需手动粘贴）
python3 scripts/bootstrap_project.py --scope user --print-custom-instructions
```

`--track-aitasks` 只阻止脚本添加忽略规则，不会读取或修改已存在的 `.gitignore`。默认安装仍拒绝覆盖不同副本；升级必须显式提供旧版本基线。

## 检查与显式升级

```bash
# 只读检查版本、内容、权限和兼容入口；全部匹配返回 0，有缺失或差异返回 1
python3 scripts/bootstrap_project.py --scope user --check
python3 scripts/bootstrap_project.py --target /absolute/path/to/your-project --check

# 同样只读，stdout 为一个 JSON；缺失或差异仍返回 1
python3 -B scripts/bootstrap_project.py --scope user --check --json

# OLD_RELEASE 是可信旧版本的完整目录，包含 skills/
python3 scripts/bootstrap_project.py --scope user --upgrade-from /absolute/path/to/OLD_RELEASE --dry-run
python3 scripts/bootstrap_project.py --scope user --upgrade-from /absolute/path/to/OLD_RELEASE
```

项目升级将 `--scope user` 换成 `--target …`。只有已安装内容和文件权限与旧基线完全一致的副本才允许替换；已匹配新版本的副本保持不动，任何定制冲突都在写入前停止并报告。兼容软链接保持原目标；旧实体副本也须匹配基线才升级。不会自动下载旧版或猜测用户改动。

复制、比较和升级统一排除 `__pycache__`、`*.pyc`、`.DS_Store`；真实资源和权限仍参与比较，资源软链接在写入前拒绝。`--check --json` 的 `schema_version=1` 报告源码仓库、规范安装目录、每个 Skill 的源码/安装版本、原路径/真实路径、manifest 摘要及各兼容入口状态；`different` 只表示内容不一致，不能单凭它断言存在用户定制。`--json` 仅与 `--check` 使用，不能混入打印全局指令。

每个 Skill 先复制到临时目录再替换，失败时恢复该 Skill 的旧副本；恢复失败会保留备份并报告路径。跨多个 Skill 的 I/O 失败可能留下部分升级，修复后可用同一基线重试。检查只证明磁盘副本及入口匹配，不证明 Harness 已加载；实际升级后仍需刷新会话。用户级操作不修改项目规则或客户端全局指令。

## Codex Custom Instructions

在 Codex 的设置中找到 Custom Instructions，将下面内容粘贴进去。它包含跨项目适用的简短 CodeGraph 条件规则；`--target` 也会将详细规则写入目标项目的 `AGENTS.md`。单独使用 `--print-custom-instructions` 只输出文本；与 `--scope user` 组合时会继续安装 Skills，但不会自动修改 Codex 设置或全局 `AGENTS.md`。

这套指令要求代码编辑使用 `aitasks-maintenance`。若只安装部分 Skill，请确保该专项也安装在当前客户端可发现的位置；不使用这套指令时，各专项仍可单独安装。

```md
# Engineering defaults

- 使用中文回复；代码、命令、文件名、错误日志和 API 名称保持原文。
- 修改前读取并遵守适用的 `AGENTS.md`、`AGENTS.override.md`、`CLAUDE.md`；更具体路径规则优先。
- 工程任务开始、范围变化或新根因确认时，先按任务关键词轻量检索相关经验与 todo。工具支持时用 `context` 取有界摘要，必要时按 ID 读一条；否则定向取少量命中段落，不整篇读取。不默认整篇加载或更新计数；同一会话复用未变结果，新会话重新取相关摘要。
- 只核对会改变结论或交付的关键前提与信息缺口；保持独立判断，区分已验证事实、推断和未验证项。时效性或高风险结论优先查证；实质分歧说明依据和风险。
- 先调查相关实现、约束及工作区已有改动；Bug 确定根因后做当前任务所需的最小修复，保留无关修改。
- 校验、兜底和兼容分支须有具体依据，同一信任边界内复用已验证数据，保留必要保障。沿用已有工具与流程，抽象须有实际收益；生成文件改源后生成。
- 在任务范围内兼顾用户、开发者和 AI Agent 的体验，保持既有功能与契约。面向用户的信息只保留理解、判断或操作所需内容；保留必要解释、状态、指引与无障碍信息，确认布局问题后局部调整。
- 修改后按风险执行最小必要验证；可复用输入未变的近期结果，不为纯文档变更运行无关测试。未经验证不得宣称通过，无法验证时说明边界。
- 单一明确工程任务直接处理或使用对应专项 Skill；确需跨多个专项阶段统筹或用户明确指定时，使用 `ai-engineering-collaboration`。
- 编辑项目代码时，不论是否使用入口 Skill，都用 `aitasks-maintenance` 维护一条 todo 和实际结果，按阈值先归档再移出，不删除归档；已自动检查维护的命令不再单独查状态。仅修改 `.aitasks` 不递归建 todo。
- 用户明确要求记录经验时立即记录；否则在已授权写入时观察已验证且可复用的问题，按独立任务计数，二次出现再沉淀并优先更新原 ID。未证实原因标“未确认”；只读不写观察、经验、todo、计数、忽略规则或归档，查询不算复用。
- 项目根目录有 `.codegraph/` 且索引可用时，理解未知代码结构、调用链或改动影响优先用 CodeGraph MCP；MCP 不可用且 CLI 可用时改用 CLI，首次使用先运行 `codegraph status`。已知路径或简单文本直接检索；图谱不可用或结果不足时回退常规工具，关键结论核对代码与测试，不自动执行 `codegraph init`。
```

项目规则仍应写入目标项目的 `AGENTS.md`。脚本写入的区块只定义工程协作底线；技术栈、测试命令、领域约束和部署规则应由项目维护者在该文件的其他位置补充。

## 验证安装

```bash
test -f /absolute/path/to/your-project/AGENTS.md
test -f /absolute/path/to/your-project/.agents/skills/ai-engineering-collaboration/SKILL.md
test -L /absolute/path/to/your-project/.gemini/skills/ai-engineering-collaboration
test -L /absolute/path/to/your-project/.claude/skills/ai-engineering-collaboration
test -L /absolute/path/to/your-project/.zcode/skills/ai-engineering-collaboration
```

静态文件存在不代表某个 Harness 已加载 Skill。请在目标环境刷新会话，并通过显式调用确认入口及专项 Skill 可被发现。若未发现 Skill，检查对应工具版本、Skill 开关和权限设置；ZCode 还需在设置的 Skills 页面刷新并确认已启用。
