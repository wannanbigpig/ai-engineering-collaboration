# `.aitasks` 归档流程

执行归档或经验计数时读取本文件；高频记录约定见本 Skill 的 `SKILL.md`。优先调用 `scripts/maintain_aitasks.py`，只把必要的短输出带入上下文；没有 Python 时才回退到 Agent 直接读写 Markdown。

## CLI 调用顺序

工具路径相对于本 Skill 目录，要求 Python 3.10+，不需要第三方包：

```bash
python3 scripts/maintain_aitasks.py --project-root <project-root> status
python3 scripts/maintain_aitasks.py --project-root <project-root> find-lessons --query "关键词"
python3 scripts/maintain_aitasks.py --project-root <project-root> mark-used --lesson "完整经验标题"
python3 scripts/maintain_aitasks.py --project-root <project-root> set-todo-status --todo "完整任务标题" --status completed
python3 scripts/maintain_aitasks.py --project-root <project-root> cleanup
python3 scripts/maintain_aitasks.py --project-root <project-root> cleanup --apply
```

`status` 和不带 `--apply` 的 `cleanup` 是只读操作；`mark-used`、`set-todo-status` 和 `cleanup --apply` 会写入文件。写入操作会取得 `.aitasks/.maintenance.lock`，并使用临时文件原子替换；标题不唯一时拒绝修改。

## 归档步骤

1. 按 `SKILL.md` 的阈值表筛选到期记录：逐条读取元数据注释，比对 `completed_at`/`last_used_at` 与当天日期。
2. 建档归档文件 `.aitasks/archive/todo-YYYY-MM-DD.md` 或 `lessons-YYYY-MM-DD.md`（同日已存在则追加）。
3. 归档文件头部写明来源：`<!-- archived_at=YYYY-MM-DD source=todo.md -->`。
4. 将到期记录原样移入归档文件（保留元数据注释），再从活动文件删除对应段落。
5. 归档后检查活动文件：不留空标题、不留双空行，剩余记录的段落结构完整。

## 幂等与安全

- 同一记录不得重复归档：工具写入稳定的 `id` 并比对所有归档文件；同一记录重复执行不会重复追加。
- 追加经验到已有 `lessons.md` 时只追加或在保留原内容基础上合并，禁止未读取原内容就整体覆盖。
- 归档是删除的前置步骤；不确定是否到期时保留记录并说明原因。

## 复用经验

- 复用某条经验解决问题后，将该条 `use_count` 加 1、`last_used_at` 更新为当天。
- 经验只记录可复用内容（场景、问题、原因、正确做法、适用范围），不记录流水账。

## 模板

路径相对本 Skill 根目录：

- todo 模板：`assets/todo.md`
- 经验模板：`assets/lessons.md`
