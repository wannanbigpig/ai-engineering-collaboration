---
name: aitasks-maintenance
description: "写入或维护 .aitasks 计划、经验、计数与归档元数据；普通只读查询不加载。"
license: MIT
compatibility: universal
metadata:
  version: 1.7.0
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

用户或项目已有持续记录经验的要求，或本任务已获经验维护授权时，才在新增可复用知识后检索并追加或更新记录，无需每轮再次确认；当前只读限制仍优先。已有相同结论不重复写入，预期失败测试和常规执行过程不形成经验。

## 操作路由

- **创建记录**：todo 使用 [assets/todo.md](assets/todo.md)，经验使用 [assets/lessons.md](assets/lessons.md)；只读取所需模板。保留标题层级和字段名称并替换占位符。
- **只读查询**：普通经验查询直接检索目标记录，不加载本 Skill、不更新计数，也不触发归档检查。
- **批量查询或元数据更新**：优先使用 `scripts/maintain_aitasks.py`，避免搬运整份 Markdown；仅需更新状态或计数时不读取模板。
- **归档与恢复**：准备归档、手工归档、失败恢复或需要命令参数、元数据、阈值与幂等细节时，读取 [references/maintenance.md](references/maintenance.md)。

脚本只使用 Python 3.10+ 标准库；没有 Python 时按模板和 [references/maintenance.md](references/maintenance.md) 的相同边界手动处理。没有归档授权时只保留预览，不删除或压缩旧归档。
