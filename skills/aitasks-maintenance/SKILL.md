---
name: aitasks-maintenance
description: ".aitasks 任务规划、经验、归档和元数据维护。Use for task plans, reusable lessons, archives, and metadata repair."
license: MIT
compatibility: universal
metadata:
  version: 1.2.0
---

# `.aitasks` 维护

维护 `.aitasks/` 下的任务记录、经验、归档和元数据。仅在创建/更新非平凡任务计划、沉淀经验、查询经验、执行归档或修复元数据时加载；普通代码分析和简单修改不加载。

## 目录约定

- `.aitasks/` 不存在时按需自动创建，不因目录隐藏或被忽略而跳过读写。
- 首次创建 `.aitasks/` 时默认在根 `.gitignore` 添加忽略规则：添加前先查重（已有 `.aitasks` 或等效规则不重复添加），不改无关忽略规则。
- 忽略与否由用户控制，添加前先确认用户选择：检查 `.gitignore` 历史（如 `git log -p -- .gitignore`）发现 `.aitasks` 忽略规则曾被移除、已存在被跟踪的 `.aitasks` 文件，或用户明确要求同步时，不再自动添加或恢复忽略；历史无记录且会话内无表态时按首次默认处理。

## 记录约定

- todo 使用 `status=active`、`completed_at=-`；完成或取消时更新状态和日期。
- 模板只定义单条记录结构，不得覆盖已有 `.aitasks/todo.md`。
- 新 todo/经验记录一律追加到活动文件尾部，保持时间正序（旧在前、新在后），禁止头部插入；归档时从头部移走最旧记录。
- 经验 `use_count` 从 `0` 起；实际复用时手动递增并更新 `last_used_at`。
- 核心约定可设 `pinned=true`；无元数据的旧记录不自动清理，编辑或复用时再补齐。

## 经验沉淀触发

出现以下情况时向 `.aitasks/lessons.md` 追加经验：用户纠正了错误判断；修复了 Bug 或线上问题；定位到测试、构建或 CI 失败根因；发现隐藏业务规则、项目约定或历史坑点；排查、修复或验证方法可复用。只记录可复用经验，不记录流水账。

## 元数据格式

每条记录以 HTML 注释携带元数据，放在标题前一行：

```text
<!-- aitasks:todo created_at=YYYY-MM-DD status=active completed_at=- -->
<!-- aitasks:lesson created_at=YYYY-MM-DD last_used_at=- use_count=0 pinned=false -->
```

## 维护触发条件

任一条件满足时执行归档检查：距上次归档至少 30 天（归档日期以 `.aitasks/archive/` 内文件名中的 `YYYY-MM-DD` 为准，目录不存在或为空视为从未归档）；带元数据经验达到 100 条；已完成/取消 todo 达到 20 条。检查后无到期记录时不写归档文件，后续会话按相同条件重新判断。

## 归档阈值

| 记录 | 条件 | 保留期 |
|---|---|---|
| 经验 | `use_count=0` / `=1` / `>=2` | 90 天 / 180 天 / 365 天 |
| todo | 已完成或取消 | 30 天 |

`pinned=true`、活动 todo 和无有效元数据的旧记录不归档。归档操作流程见 [references/maintenance.md](references/maintenance.md)。

## CLI 工具

需要批量读取或修改时，优先调用 `scripts/maintain_aitasks.py`，避免让 Agent 直接搬运整份 Markdown。工具只使用 Python 3.10+ 标准库，不安装第三方依赖；没有 Python 时仍可按本文件的 Markdown 流程手动处理。

先用 `status` 查看是否到期，再用 `cleanup` 预览；只有确认输出后才追加 `--apply`。写入命令使用项目锁和原子替换，标题必须唯一：

```bash
TOOL="python3 <skill-dir>/scripts/maintain_aitasks.py --project-root <project-root>"
$TOOL status
$TOOL find-lessons --query "关键词"
$TOOL find-lessons --query "关键词" --include-content
$TOOL mark-used --lesson "完整经验标题"
$TOOL set-todo-status --todo "完整任务标题" --status completed
$TOOL cleanup
$TOOL cleanup --apply
```

- `status`：报告触发原因、记录数量和待归档标题。
- `find-lessons`：按标题或正文检索；默认不输出正文，需判断细节时再加 `--include-content`。
- `mark-used`：递增 `use_count` 并更新 `last_used_at`。
- `set-todo-status`：只修改 `status` 与 `completed_at`；`active` 会将 `completed_at` 重置为 `-`。
- `cleanup`：默认 dry-run；`--apply` 按保留期把到期记录原样移入 `.aitasks/archive/`，成功写入后才从活动文件删除。

默认参数为：检查间隔 30 天、经验数量触发 100 条、完成 todo 触发 20 条；经验保留 90/180/365 天，完成或取消 todo 保留 30 天。需要手动立即检查时给 `status` 或 `cleanup` 加 `--force`。

工具只清理活动文件：归档记录会保留在 `.aitasks/archive/`，不会被 `cleanup` 自动删除。需要压缩或删除旧归档时，先人工确认备份和保留期限，再单独处理归档目录。

模板见 [assets/todo.md](assets/todo.md) 和 [assets/lessons.md](assets/lessons.md)。这两份文件是 todo 和经验记录的唯一模板来源；创建记录时必须保留模板中的标题层级和字段名称、替换全部占位符，不新增同级自定义字段。
