---
name: aitasks-maintenance
description: "代码编辑任务自动记录 todo，重复问题自动沉淀经验，并在记录过量时归档清理 .aitasks；只读任务不写入。"
license: MIT
compatibility: universal
metadata:
  version: 1.7.12
---

# `.aitasks` 维护

代码编辑一任务一条 todo；用户明确要求或同一问题第二次实质出现时维护经验。只读任务不写记录、计数或归档。

## 触发与边界

- 编辑代码前创建或复用一条 todo，完成时写实际结果并标记 `completed`，未完成保持 `active`，取消用 `cancelled`。简单任务只记目标、验证与结果；复杂任务按需补下一步、阻塞与风险。仅维护 `.aitasks` 不递归建 todo。
- 任务开始、范围变化或新根因确认时，用模块/符号/错误码作关键词取相关摘要；不是每轮、每次工具调用都查。普通查询不加载维护流程、不更新计数，也不写观察；只读边界覆盖全部 `.aitasks` 文件。
- 明确要求记录时立即记录；否则只观察原因已确认且做法可复用的问题，二次独立任务出现后才沉淀。复述、重试和预期失败不计；未知原因不自动升格，显式要求的记录可标“未确认”。经验只在当前适用范围内作为线索，不能取代最新要求与事实。

## 最小操作

- 普通查询直接按[只读查询](references/query.md)调用 `context`，按 ID 读必要正文；默认预算可按证据需要扩大，不一次性加载全部记录。`--since` 仅复用本会话已读内容，新会话重新取摘要。工具扩展少量常用中英文别名，活动经验弱匹配时也回查归档。
- 恢复 todo 可用有界 `list-todos --query …`，按 ID 复用。新建用 `add-todo --maintain --json`，直接保存返回的 ID；完成用 `finish-todo --id … --result … --json` 一次更新结果、可选验证、状态并检查阈值。
- 根因确认且允许写入时，先 `find-observations --query "模块 症状 原因"` 取候选。同模块、症状及原因均吻合才复用原 key；没有同因候选才新建稳定 key，不因词命中自动合并。每个独立任务使用自己的 todo ID，同任务重试复用 ID。
- 实际帮助解决问题后才 `mark-used --id … --task-id … --maintain`，同任务重复调用不加次数。查询、读取和未采用的候选不计。`upsert-lesson`、完成命令及带 `--maintain` 的写入已检查阈值，无需再跑 `status`；手工或旧命令写入后补检查，先归档再移出，不删除归档。
- 新证据证明经验失效时，用 `set-lesson-status --id … --status retired --reason …` 停用；被已有新经验替代用 `superseded --superseded-by …`。默认查询排除这两类，按 ID 仍可审计并可恢复 `active`；不因年代久或已归档自动判失效。
- `.aitasks/` 首次创建前按 [维护参考](references/maintenance.md#首次创建与忽略规则) 核对忽略规则。新建命令要求该目录已存在且非软链接，不修改 `.gitignore`。
- 无 Python 3.10+ 或需手工维护时，按 [todo](assets/todo.md)、[经验](assets/lessons.md) 单条模板追加；新记录用唯一 UUID4，复用保留 ID，不批量改旧结构或回填元数据。状态更新不必重读模板。

## 经验动作

| 当前条件或观察结果 | 下一动作 |
|---|---|
| 原因未确认、预期失败或只读任务 | 不调用 `observe`，不自动写经验 |
| 原因已确认、允许写入且做法可复用 | `observe --key … --task-id … --evidence … --verified` |
| `candidate`：首次独立任务 | 保留观察，本次不新增正式经验 |
| `ready`：二次独立任务 | 核对同因、适用范围和做法后 `upsert-lesson --key …` |
| `recorded`：已有经验 | 按返回 ID 读原记录；需要修订才 `upsert-lesson --id …` |
| 用户明确要求记录 | `upsert-lesson --explicit`，无需等待二次 |

更新活动或归档经验均保留原 ID 和额外笔记；同标题不自动合并，字段边界不明时保留原文并核对。JSON 返回的 `changed` 表示持久内容是否改变，`maintenance_checked` 表示本次是否实际检查阈值；重复计数可能两者均为 false，不能据命令成功推定新增记录。

## 按需参考

查询参数、元数据、归档阈值及失败恢复见 [维护参考](references/maintenance.md)。阈值归档属于已授权的维护；固定经验、活动 todo 和无有效元数据的旧记录保留。
