# `.aitasks` 维护参考

批量查询、元数据更新、归档、失败恢复或核对幂等机制时按需读取本文件；普通只读经验查询不需要读取。高频记录约定见本 Skill 的 `SKILL.md`。优先调用 `scripts/maintain_aitasks.py`，只把必要的短输出带入上下文；没有 Python 时才回退到 Agent 直接读写 Markdown。

## 元数据与经验边界

每条记录以 HTML 注释携带元数据，放在标题前一行：

```text
<!-- aitasks:todo created_at=YYYY-MM-DD status=active completed_at=- -->
<!-- aitasks:lesson created_at=YYYY-MM-DD last_used_at=- use_count=0 pinned=false -->
```

经验检索以一条记录为单位：读取命中标题及正文，保留所属子标题，在下一条同级标题或记录元数据前停止。`aitasks:lesson` 注释属于紧随其后的记录；缺少元数据的旧经验，其计数是“未记录”，不能借用相邻值。只查询适用条件时无需附带计数。

## CLI 命令参考

按当前操作选择命令，不要求逐条执行。工具路径相对于本 Skill 目录，要求 Python 3.10+，不需要第三方包：

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

`status` 和不带 `--apply` 的 `cleanup` 是只读操作；`mark-used`、`set-todo-status` 和 `cleanup --apply` 会写入文件。写入操作会取得 `.aitasks/.maintenance.lock`，并使用临时文件原子替换；标题不唯一时拒绝修改。

- `status`：报告触发原因、记录数量和待归档标题。
- `find-lessons`：`--query` 接受单个字面子串，不是正则或关键词列表；按标题或正文检索，包括无元数据旧记录。默认摘要及 `--include-content` 保持文本输出；需要一次取得正文、所属元数据和引用位置时用 `--json`，与 `--include-content` 二选一。
- `mark-used`：递增 `use_count` 并更新 `last_used_at`。
- `set-todo-status`：只修改 `status` 与 `completed_at`；`active` 会将 `completed_at` 重置为 `-`。
- `cleanup`：默认 dry-run；`--apply` 按保留期把到期记录移入 `.aitasks/archive/`，成功写入后才从活动文件删除。

`--json` 返回 `matches` 数组，每项含 `title`、`content`、`metadata`、`use_count`、`use_count_status` 及 `source` 的绝对路径和从 1 开始的行号（含两端）。`use_count_status` 区分 `recorded`、`missing`、`invalid`；缺失或无效计数为 `null`，不能当作 0。无匹配返回空数组，不写文件或计数。

## 维护与归档阈值

任一条件满足时可预览归档：距 `.aitasks/.maintenance.json` 的 `last_cleanup_at` 至少 30 天；带元数据经验达到 100 条；已完成或取消 todo 达到 20 条。`status` 与 dry-run 不更新状态；已授权的 `cleanup --apply` 即使没有到期记录也更新检查日期，但不创建空归档。

| 记录 | 条件 | 保留期 |
|---|---|---|
| 经验 | `use_count=0` / `=1` / `>=2` | 90 天 / 180 天 / 365 天 |
| todo | 已完成或取消 | 30 天 |

`pinned=true`、活动 todo 和无有效元数据的旧记录不归档。工具只清理活动文件，不自动删除旧归档。需要立即检查时给 `status` 或 `cleanup` 加 `--force`。

## 归档步骤

1. 按本文件的阈值表筛选到期记录：逐条读取元数据注释，比对 `completed_at`/`last_used_at` 与当天日期。
2. 建档归档文件 `.aitasks/archive/todo-YYYY-MM-DD.md` 或 `lessons-YYYY-MM-DD.md`（同日已存在则追加）。
3. 归档文件头部写明来源：`<!-- archived_at=YYYY-MM-DD source=todo.md -->`。
4. 将到期记录原样移入归档文件（保留元数据注释），再从活动文件删除对应段落。
5. 核对剩余记录内容和顺序完整；不为整理空白重写无关段落。维护检查成功后更新 `.aitasks/.maintenance.json` 的 `last_cleanup_at`，没有到期记录也记录检查日期，但不创建空归档文件。

## 幂等与安全

- 同一记录不得重复归档：工具写入稳定的 `id` 并比对所有归档文件；同一记录重复执行不会重复追加。
- 追加经验到已有 `lessons.md` 时只追加或在保留原内容基础上合并，禁止未读取原内容就整体覆盖。
- 归档是删除的前置步骤；不确定是否到期时保留记录并说明原因。

## 复用经验

- 允许维护写入且实际复用经验解决问题后，将该条 `use_count` 加 1、`last_used_at` 更新为当天；只读查询不更新计数。
- 经验只记录可复用内容（场景、问题、原因、正确做法、适用范围），不记录流水账。

## 模板

路径相对本 Skill 根目录：

- todo 模板：`assets/todo.md`
- 经验模板：`assets/lessons.md`
