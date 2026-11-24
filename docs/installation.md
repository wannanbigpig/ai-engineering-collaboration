# 安装与更新

安装与更新统一使用 `npx skills@1.9.0`。需要 Node.js ≥22.20.0，从远程仓库安装另需 Git。CLI 版本与本仓库版本独立，Skill 内容取自所选的远程仓库或本地工作树。[CLI 命令参考](https://github.com/vercel-labs/skills/blob/v1.9.0/docs/commands.md)

## 安装和更新前检查

在目标项目根目录用 `npx skills@1.9.0 list --json` 检查已有同名 Skill，并查看实际目录与客户端符号链接。项目副本状态为 `modified`、`untracked`、来源不符，或发现未列出的同名项时，先备份到安装目录之外，或把定制合并进自己的 Skill 来源。若为 `missing`，先确认锁记录与实际路径。用户级安装先用 `npx skills@1.9.0 list --global` 核对名称、来源和实际目录。

`add` 可以替换同名目录，`update` 在上游内容变化时也可能重装。建议在普通终端交互安装，看到 `overwrites` 时先处理同名副本，再继续确认。CLI 检测到 Agent 环境时可能自动跳过确认，因此 Agent 也应先完成上述检查。

## 安装到当前项目

在目标项目根目录运行。以下示例给 Codex 安装方案实施和任务记录两个 Skill。

```bash
npx skills@1.9.0 add wannanbigpig/ai-engineering-collaboration --skill plan-execution --skill aitasks-maintenance --agent codex
npx skills@1.9.0 list --json
```

本地开发时，在目标项目用本仓库的绝对路径作为来源。

```bash
npx skills@1.9.0 add /absolute/path/to/ai-engineering-collaboration --skill plan-execution --skill aitasks-maintenance --agent codex
```

项目安装后核对 `list --json` 中的路径、`source` 和 `status: tracked`，并确认 `skills-lock.json` 中有对应来源和内容哈希。锁文件写入失败时，已复制的文件可能仍在，重试前先核对实际状态。打开项目新会话可点名调用 Skill，核对实际加载路径。

可用 `add <来源> --list` 查看源仓库提供的名称，用 `--skill '*'` 选择全部 Skill。需要跨项目共享时，在安装命令中加入 `--global` 并核对该客户端的用户级目录。

## 更新或移除

从远程仓库安装后，可先用 `npx skills@1.9.0 check` 查看上游更新和项目本地修改。两者都可能使 `check` 返回 1，按实际输出处理。完成[安装和更新前检查](#安装和更新前检查)后，仅更新已确认可替换的项。

```bash
npx skills@1.9.0 update --project plan-execution aitasks-maintenance
```

本地来源有改动时，完成同样的检查后重新运行本地安装命令。用户级更新使用 `update --global` 并点名。卸载前核对路径和来源，项目卸载示例为 `npx skills@1.9.0 remove plan-execution aitasks-maintenance`，用户级卸载加 `--global`。

## 客户端与项目规则

安装多个客户端时可指定 `--agent codex claude-code`。Codex、Cursor、Gemini CLI 和 OpenCode 的项目安装目录为 `.agents/skills/`，Claude Code 为 `.claude/skills/`，ZCode 为 `.zcode/skills/`。ZCode 可在设置的 Skills 页面刷新并启用。项目目录、用户级目录及实际加载分别核对。[固定版本的客户端路径表](https://github.com/vercel-labs/skills/blob/v1.9.0/docs/agents.md#supported-agents)

CLI 安装 Skill 时不替项目编写 `AGENTS.md` 或配置 `.gitignore`。是否跟踪 `.aitasks/` 由项目决定。需要常驻工程规则时，直接复制并合并 [README 中的规则正文](../README.md#推荐自定义规则)。

Gemini CLI 默认读取 `GEMINI.md`。如需同时读取项目现有的 `AGENTS.md`，可在 `.gemini/settings.json` 配置两个文件名。[Gemini CLI 项目上下文配置](https://geminicli.com/docs/cli/gemini-md/#customize-the-context-file-name)

```json
{
  "context": {
    "fileName": ["AGENTS.md", "GEMINI.md"]
  }
}
```

## 已有旧副本

改用 `npx` 前，按[安装和更新前检查](#安装和更新前检查)核对旧目录和链接，保留已定制内容。项目规则与忽略规则按项目需要手工合并。若仍有用户级旧副本，在项目新会话检查实际加载路径后再决定是否移除。
