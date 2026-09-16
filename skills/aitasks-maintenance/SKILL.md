---
name: aitasks-maintenance
description: "创建或更新 .aitasks 计划、经验、计数及归档元数据；普通只读经验查询无需加载。Maintain .aitasks records and archives when writes or metadata operations are needed."
license: MIT
compatibility: universal
metadata:
  version: 1.6.4
---

# `.aitasks` 维护

维护 `.aitasks/` 下的任务记录、经验、归档和元数据。仅在需要创建/更新任务计划、沉淀经验、更新计数、执行归档或修复元数据时加载；普通经验查询直接检索，不自动启动维护。用户要求只读或不修改文件时，不写记录、计数、忽略规则或归档；计划留在会话中。

## 目录约定

- `.aitasks/` 不存在时按需自动创建，不因目录隐藏或被忽略而跳过读写。
- 首次创建 `.aitasks/` 时默认在根 `.gitignore` 添加忽略规则：添加前先查重（已有 `.aitasks` 或等效规则不重复添加），不改无关忽略规则。
- 忽略与否由用户控制，添加前先核实已有选择：检查 `.gitignore` 历史（如 `git log -p -- .gitignore`）发现 `.aitasks` 忽略规则曾被移除、已存在被跟踪的 `.aitasks` 文件，或用户明确要求同步时，不再自动添加或恢复忽略；历史无记录且会话内无表态时按首次默认处理，无需为核实结果再次询问。

## 记录约定

- todo 使用 `status=active`、`completed_at=-`；完成或取消时更新状态和日期。
- 模板只定义单条记录结构，不得覆盖已有 `.aitasks/todo.md`。
- 新 todo/经验记录一律追加到活动文件尾部，保持时间正序（旧在前、新在后），禁止头部插入；归档只移动到期记录，保留其余记录的相对顺序。
- 经验 `use_count` 从 `0` 起；在允许维护写入且确实用于解决问题后递增并更新 `last_used_at`；普通检索不计数。
- 核心约定可设 `pinned=true`；无元数据的旧记录不自动清理，编辑或复用时再补齐。

## 经验沉淀触发

用户纠正、根因定位或隐藏约定中存在新增、可复用知识时，先检索相关记录，再追加或更新经验；已有相同结论不重复写入，预期失败测试和常规执行过程不形成经验。

## 元数据格式

每条记录以 HTML 注释携带元数据，放在标题前一行：

```text
<!-- aitasks:todo created_at=YYYY-MM-DD status=active completed_at=- -->
<!-- aitasks:lesson created_at=YYYY-MM-DD last_used_at=- use_count=0 pinned=false -->
```

## 维护触发条件

维护任务中，任一条件满足时可预览归档：距最近完成的维护检查至少 30 天；带元数据经验达到 100 条；已完成/取消 todo 达到 20 条。最近检查以 `.aitasks/.maintenance.json` 的 `last_cleanup_at` 为准，缺失或无效视为从未检查，不以归档文件日期推断。`status` 与 dry-run 不更新状态；已授权的 `cleanup --apply` 即使没有到期记录也更新检查日期，但不创建空归档。同一任务内状态与记录未变时复用检查结果；数量阈值仍可独立触发后续检查。普通经验查询不进行归档检查。

## 归档阈值

| 记录 | 条件 | 保留期 |
|---|---|---|
| 经验 | `use_count=0` / `=1` / `>=2` | 90 天 / 180 天 / 365 天 |
| todo | 已完成或取消 | 30 天 |

`pinned=true`、活动 todo 和无有效元数据的旧记录不归档。仅在手工归档、失败恢复或需要理解幂等机制时读取 [references/maintenance.md](references/maintenance.md)。

## CLI 工具

需要批量读取或修改时，优先调用 `scripts/maintain_aitasks.py`，避免让 Agent 直接搬运整份 Markdown。工具只使用 Python 3.10+ 标准库，不安装第三方依赖；没有 Python 时仍可按本文件的 Markdown 流程手动处理。

需要了解状态时用 `status`；准备归档时直接用 `cleanup` 预览，无需连续执行两个相同预览。Agent 核对范围和到期记录后，在已有归档授权内执行 `--apply`，没有授权时仅保留预览。写入命令使用项目锁和原子替换，标题必须唯一。以下是按需选择的命令，不是必须逐条执行的流水线：

```bash
AITASKS_TOOL="<skill-dir>/scripts/maintain_aitasks.py"
AITASKS_PROJECT="<project-root>"
python3 "$AITASKS_TOOL" --project-root "$AITASKS_PROJECT" status
python3 "$AITASKS_TOOL" --project-root "$AITASKS_PROJECT" find-lessons --query "关键词"
python3 "$AITASKS_TOOL" --project-root "$AITASKS_PROJECT" find-lessons --query "关键词" --include-content
python3 "$AITASKS_TOOL" --project-root "$AITASKS_PROJECT" mark-used --lesson "完整经验标题"
python3 "$AITASKS_TOOL" --project-root "$AITASKS_PROJECT" set-todo-status --todo "完整任务标题" --status completed
python3 "$AITASKS_TOOL" --project-root "$AITASKS_PROJECT" cleanup
python3 "$AITASKS_TOOL" --project-root "$AITASKS_PROJECT" cleanup --apply
```

- `status`：报告触发原因、记录数量和待归档标题。
- `find-lessons`：`--query` 接受单个字面子串，不是正则或关键词列表；按标题或正文检索，包括以 `#` 标题分段的无元数据旧记录（唯一开头 H1 且有子标题时视为文档标题；无标题段落或 Setext 标题用文本检索回退）。默认摘要及 `--include-content` 保持文本输出；需要一次取得正文、所属元数据和引用位置时用 `--json`，与 `--include-content` 二选一。
- `mark-used`：递增 `use_count` 并更新 `last_used_at`。
- `set-todo-status`：只修改 `status` 与 `completed_at`；`active` 会将 `completed_at` 重置为 `-`。
- `cleanup`：默认 dry-run；`--apply` 按保留期把到期记录原样移入 `.aitasks/archive/`，成功写入后才从活动文件删除。

`--json` 返回 `matches` 数组，每项含 `title`、`content`、`metadata`、`use_count`、`use_count_status` 及 `source` 的绝对路径和从 1 开始的行号（含两端）。`use_count_status` 区分 `recorded`、`missing`、`invalid`；缺失或无效计数为 `null`，不能当作0，原始字段保留在 `metadata`。无匹配返回空数组，不写文件或计数。

默认参数为：检查间隔 30 天、经验数量触发 100 条、完成 todo 触发 20 条；经验保留 90/180/365 天，完成或取消 todo 保留 30 天。需要手动立即检查时给 `status` 或 `cleanup` 加 `--force`。

工具只清理活动文件：归档记录会保留在 `.aitasks/archive/`，不会被 `cleanup` 自动删除。需要压缩或删除旧归档时，先人工确认备份和保留期限，再单独处理归档目录。

创建 todo 时使用 [assets/todo.md](assets/todo.md)，创建经验时使用 [assets/lessons.md](assets/lessons.md)，只读取所需模板并复用已加载版本。保留标题层级、字段名称并替换占位符；仅更新状态或计数时无需读取模板。
