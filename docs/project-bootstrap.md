# 项目初始化与 Custom Instructions

本仓库有两类配置：项目内可版本管理的 Skill 与 `AGENTS.md`，以及 Codex 客户端账户级的 Custom Instructions。前者可由脚本安全生成；后者属于客户端设置，脚本只能输出待粘贴文本，不能直接修改。脚本仅依赖 Python 3.9+ 标准库。

Skill 只在 `.agents/skills/` 保留一份内容。Codex、OpenCode 和 Cursor 本地版可直接发现该目录；脚本另外为 Claude Code、Gemini 和 ZCode 创建兼容软链接。各工具是否自动触发 Skill 仍由自身版本、设置和会话状态决定。

## 一键安装到所有项目

    python3 scripts/bootstrap_project.py --scope user

该命令将完整 10 个 Skill 安装到当前用户的 `~/.agents/skills/`，并在 `~/.claude/skills/`、`~/.gemini/skills/`、`~/.zcode/skills/` 为每个 Skill 建立指向该目录的相对软链接；内容仍只有 `~/.agents/skills/` 一份副本。它绝不创建或修改 `~/AGENTS.md`、`.gitignore` 或任何项目文件。已有内容相同的 Skill 会跳过；内容不同则终止且不覆盖。

可先预览：

    python3 scripts/bootstrap_project.py --scope user --dry-run

## 一键初始化项目

在本仓库根目录执行：

```bash
python3 scripts/bootstrap_project.py --target /absolute/path/to/your-project
```

脚本会执行以下操作：

1. 将全部 10 个 Skill 复制到目标项目的 `.agents/skills/`，确保主入口可以加载全部专项 Skill。
2. 在目标项目的 `.claude/skills/`、`.gemini/skills/`、`.zcode/skills/` 为每个 Skill 创建指向 `.agents/skills/` 的相对软链接。
3. 创建或更新目标项目根目录的 `AGENTS.md`，仅管理 `ai-engineering-collaboration` 标记包围的区块，保留其余项目规则。
4. 默认向 `.gitignore` 添加 `.aitasks/`；若该目录已被 Git 跟踪，或 Git 历史显示该规则曾被移除，则不改动并输出原因。

脚本先检查所有同名 Skill 与各工具的同名兼容链接。目标已有内容相同的 Skill 会跳过；受管链接或内容相同的普通副本视为最新并保留原样；内容不同、指向其他位置的链接或其他同名内容则以退出码 `2` 终止，且不会写入任何其他配置。它不会覆盖用户修改。

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
  "contextFileName": "AGENTS.md"
}
```

注意该设置会替换 Gemini 在上下文层级中查找的文件名，项目内原有的 `GEMINI.md` 将不再被读取；两者都保留时，应把项目规则收敛到被指向的那一个文件。较旧的 Gemini CLI 版本还需要在其设置中开启 skills 开关。

## 常用选项

```bash
# 仅预览将要写入的内容
python3 scripts/bootstrap_project.py --target /absolute/path/to/your-project --dry-run

# 需要将 .aitasks/ 纳入版本控制时使用
python3 scripts/bootstrap_project.py --target /absolute/path/to/your-project --track-aitasks

# 输出账户级 Custom Instructions，复制到 Codex 设置中
python3 scripts/bootstrap_project.py --print-custom-instructions
```

`--track-aitasks` 只阻止脚本添加忽略规则，不会修改已存在的 `.gitignore`。如果需要更新已安装但内容不同的 Skill，应先审查差异并手动处理；脚本故意不提供默认覆盖选项。

## Codex Custom Instructions

在 Codex 的设置中找到 Custom Instructions，将下面内容粘贴进去。它是每轮对话都应生效的短规则，不应再放入 `.aitasks`、CodeGraph 或子 Agent 的详细流程。

```md
# Engineering defaults

- 使用中文回复；代码、命令、文件名、错误日志和 API 名称保持原文。
- 对会实质改变结论的错误前提、逻辑跳跃和信息缺口先核对；可由现有证据确认的自行查证，只有无法推导且会改变交付时才询问。
- 保持独立判断，明确区分已验证事实、证据支持的推断、趋势预测和主观建议；不因用户预设而改变结论。
- 对时效性、争议性、高风险，或依赖精确数字和人物信息的关键结论，优先核实可靠来源；无法核实时说明证据边界，不编造。
- 与用户判断存在实质分歧，或发现会改变决策的遗漏变量、隐藏成本或判断偏差时，直接说明依据、风险和替代解释；不为低影响事项堆叠免责声明。
- 修改前读取并遵守适用的 `AGENTS.md`、`CLAUDE.md`；项目规则和更近路径规则优先。
- 修改前核对与任务直接相关的实现和约束；Bug 在根因明确后做最小修复，不得改动或覆盖无关内容。
- 行为或交付物发生变化后，运行覆盖风险的最小验证；输入未变的新鲜结果可复用，纯文档或注释修改不默认运行无关测试，未验证不得宣称完成。
- 代码变更任务完成时，仅说明：做了什么、关键修改、根因、验证方式、遗留风险或未验证项。
- 仅当任务需要跨多个专项阶段统筹，或用户明确指定时，使用 `ai-engineering-collaboration`；单一明确任务直接处理或使用对应专项 Skill。
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
