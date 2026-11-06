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

`source` 和 `installed` 各有 `diagnostics` 数组；`SKILL.md` 不是有效 UTF-8 时，记录 `code=invalid_utf8`、文件路径和可读错误，版本为 `null`，仍保留原始字节算出的 manifest 摘要、内容状态和其余 Skill 报告。检查返回 `1`，默认文本模式也显示诊断，原文件保持不变。

初装和升级都先将每个 Skill 完整复制到目标目录旁的临时目录，再发布到正式路径。初装复制或发布失败会清理暂存内容，不留下该 Skill 的半成品，可直接重试；升级失败时恢复该 Skill 的旧副本，恢复失败会保留备份并报告路径。跨多个 Skill 的 I/O 失败可能留下已完成的安装或升级；修复故障后可重试，升级仍使用同一基线。检查只证明磁盘副本及入口匹配，不证明 Harness 已加载；实际升级后仍需刷新会话。用户级操作不修改项目规则或客户端全局指令。

## Codex Custom Instructions

完整的[推荐自定义规则](../README.md#推荐自定义规则)和[各工具放置位置](../README.md#不同工具放在哪里)集中在 README 展示，脚本输出与 README 正文由回归检查保持一致。跨项目规则用于个人全局入口；技术栈、业务契约、验证命令和部署边界放到项目规则。使用自动任务记录规则时，需安装可被当前客户端发现的 `aitasks-maintenance`。

在本仓库根目录运行 `python3 -B scripts/bootstrap_project.py --print-custom-instructions` 可输出与 README 相同的完整文本。命令不会自动修改 Codex 设置、全局 `AGENTS.md` 或其他客户端规则；与 `--scope user` 组合时会继续安装 Skills，但指令仍需手工合并。

`--target` 仅管理项目 `AGENTS.md` 的标记区块。Claude Code、Gemini 等客户端的原生文件名和引入方式按 README 表及对应官方文档配置，不因为 Skill 安装成功就假定项目规则已加载。

## 验证安装

```bash
test -f /absolute/path/to/your-project/AGENTS.md
test -f /absolute/path/to/your-project/.agents/skills/ai-engineering-collaboration/SKILL.md
test -L /absolute/path/to/your-project/.gemini/skills/ai-engineering-collaboration
test -L /absolute/path/to/your-project/.claude/skills/ai-engineering-collaboration
test -L /absolute/path/to/your-project/.zcode/skills/ai-engineering-collaboration
```

静态文件存在不代表某个 Harness 已加载 Skill。请在目标环境刷新会话，并通过显式调用确认入口及专项 Skill 可被发现。若未发现 Skill，检查对应工具版本、Skill 开关和权限设置；ZCode 还需在设置的 Skills 页面刷新并确认已启用。
