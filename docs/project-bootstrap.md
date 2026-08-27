# 项目初始化与 Custom Instructions

本仓库有两类配置：项目内可版本管理的 Skill 与 `AGENTS.md`，以及 Codex 客户端账户级的 Custom Instructions。前者可由脚本安全生成；后者属于客户端设置，脚本只能输出待粘贴文本，不能直接修改。

## 一键安装到所有项目

    python3 scripts/bootstrap_project.py --scope user

该命令将完整 10 个 Skill 安装到当前用户的 ~/.agents/skills/，供所有项目使用。它只写入该 Skill 目录，绝不创建或修改 ~/AGENTS.md、.gitignore 或任何项目文件。已有内容相同的 Skill 会跳过；内容不同则终止且不覆盖。

可先预览：

    python3 scripts/bootstrap_project.py --scope user --dry-run

## 一键初始化项目

在本仓库根目录执行：

```bash
python3 scripts/bootstrap_project.py --target /absolute/path/to/your-project
```

脚本会执行以下操作：

1. 将全部 10 个 Skill 复制到目标项目的 `.agents/skills/`，确保主入口可以加载全部专项 Skill。
2. 创建或更新目标项目根目录的 `AGENTS.md`，仅管理 `ai-engineering-collaboration` 标记包围的区块，保留其余项目规则。
3. 默认向 `.gitignore` 添加 `.aitasks/`；若该目录已被 Git 跟踪，或 Git 历史显示该规则曾被移除，则不改动并输出原因。

脚本先检查所有同名 Skill。目标已有内容相同的 Skill 会跳过；内容不同则以退出码 `2` 终止，且不会写入任何其他配置。它不会覆盖用户修改。

首次安装完成后，重启或刷新 Agent 会话。复杂工程任务可直接点名入口：

```text
请使用 ai-engineering-collaboration 处理：<任务描述>
```

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
- 修改前读取并遵守适用的 `AGENTS.md`、`CLAUDE.md`；项目规则和更近路径规则优先。
- 先调查，再做最小范围的根因修复；不得改动或覆盖无关内容。
- 修改后执行适当验证；未验证不得宣称完成。
- 代码变更任务完成时，仅说明：做了什么、关键修改、根因、验证方式、遗留风险或未验证项。
- 对非平凡工程任务，使用 `ai-engineering-collaboration` Skill。
```

项目规则仍应写入目标项目的 `AGENTS.md`。脚本写入的区块只定义工程协作底线；技术栈、测试命令、领域约束和部署规则应由项目维护者在该文件的其他位置补充。

## 验证安装

```bash
test -f /absolute/path/to/your-project/AGENTS.md
test -f /absolute/path/to/your-project/.agents/skills/ai-engineering-collaboration/SKILL.md
```

静态文件存在不代表某个 Harness 已加载 Skill。请在目标环境刷新会话，并通过显式调用确认入口及专项 Skill 可被发现。
