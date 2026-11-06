# `.aitasks` 维护参考

批量查询、元数据更新、归档、失败恢复或核对幂等机制时按需读取本文件；普通只读经验查询不需要读取。高频记录约定见本 Skill 的 `SKILL.md`。优先调用 `scripts/maintain_aitasks.py`，只把必要的短输出带入上下文；没有 Python 时才回退到 Agent 直接读写 Markdown。

## 首次创建与忽略规则

`.aitasks/` 不存在时按需创建；默认在根 `.gitignore` 添加 `.aitasks/`，但先检查现有规则和 Git 跟踪状态。若 `.aitasks` 已被跟踪、用户明确要求同步，或 `.gitignore` 历史表明忽略规则曾被移除，则保留用户选择，不自动添加或恢复。只改必要的忽略行；历史没有相关记录且用户未表态时按默认处理。

## 元数据与经验边界

每条记录以 HTML 注释携带元数据，放在标题前一行：

```text
<!-- aitasks:todo id=UUID4_HEX created_at=YYYY-MM-DD status=active completed_at=- -->
<!-- aitasks:lesson id=UUID4_HEX created_at=YYYY-MM-DD last_used_at=- use_count=0 pinned=false -->
```

元数据应独占一行，并直接位于记录标题前（可有空行）；代码围栏和缩进代码块中的示例标记不属于真实记录，不能据此更新或归档正文。

经验检索以一条记录为单位：读取命中标题及正文，保留所属子标题，在下一条同级标题或记录元数据前停止。`aitasks:lesson` 注释属于紧随其后的记录；缺少元数据的旧经验，其计数是“未记录”，不能借用相邻值。只查询适用条件时无需附带计数。

## CLI 命令参考

按当前操作选择命令，不要求逐条执行。工具路径相对于本 Skill 目录，要求 Python 3.10+，不需要第三方包。`AITASKS_TASK_ID` 保存创建或查询返回的 todo ID，`AITASKS_LESSON_ID` 保存查询或记录返回的经验 ID；按返回值赋值，不从人类提示中提取：

```bash
AITASKS_TOOL="<skill-dir>/scripts/maintain_aitasks.py"
AITASKS_PROJECT="<project-root>"
# 查询均只读；先从摘要选择必要记录
python3 -B "$AITASKS_TOOL" --project-root "$AITASKS_PROJECT" context --query "模块 符号 错误码"
python3 -B "$AITASKS_TOOL" --project-root "$AITASKS_PROJECT" get-record --kind lesson --id "$AITASKS_LESSON_ID"
python3 -B "$AITASKS_TOOL" --project-root "$AITASKS_PROJECT" list-todos --query "模块" --json

# 创建后保存 JSON 的 id 为 AITASKS_TASK_ID
python3 -B "$AITASKS_TOOL" --project-root "$AITASKS_PROJECT" add-todo --title "任务标题" --goal "目标与范围" --verify "必要验证" --maintain --json

# 仅在用户明确要求记录时使用 --explicit；保存返回的 id 为 AITASKS_LESSON_ID
python3 -B "$AITASKS_TOOL" --project-root "$AITASKS_PROJECT" upsert-lesson --explicit --title "经验标题" --context "场景" --problem "问题" --cause "未确认" --resolution "正确做法" --scope "适用范围"

# 实际采用经验后计数；同任务重复调用不再增加
python3 -B "$AITASKS_TOOL" --project-root "$AITASKS_PROJECT" mark-used --id "$AITASKS_LESSON_ID" --task-id "$AITASKS_TASK_ID" --maintain --json
python3 -B "$AITASKS_TOOL" --project-root "$AITASKS_PROJECT" finish-todo --id "$AITASKS_TASK_ID" --result "实际结果" --verify "实际验证" --json
```

查询、`list-todos`、`status` 和不带 `--apply` 的 `cleanup` 只读。写入操作共享 `.maintenance.lock` 与持久的 `.maintenance.lock.guard`，使用临时文件原子替换，保留已有权限、换行和无关记录；标题选择须唯一，推荐按 ID 完成 todo。

`add-todo`、`finish-todo`、`mark-used`、`add-lesson`、`set-todo-status` 可选 `--json`；默认文本输出保持兼容。JSON 模式成功时 stdout 只有一个对象，维护提示不混入其中；失败返回非零退出码并把诊断写到 stderr，不输出成功对象。`upsert-lesson` 本来就返回 JSON，不需要该选项。

上述写入响应含 `id`、`kind`、`action`（`created` / `updated` / `unchanged`）、记录 `status`、`changed` 和 `maintenance_checked`；计数响应另含 `use_count`。`changed` 表示本次记录、观察关联、归档或维护状态的持久内容是否改变，不包含锁文件；它不代表任务行为已验证。重复完成且内容未变时 `changed=false`，仍检查维护；同任务重复计数直接跳过，`maintenance_checked=false`。`upsert-lesson` 保留原有 `created` / `updated` 动作枚举，同内容更新由 `changed=false` 表达。工具不会为了产生更新结果改写相同内容。

- `status`：报告触发原因、记录数量和待归档标题。
- `find-lessons`：`--query` 是单个字面子串，按标题或正文查找，包括无元数据旧记录。活动区无命中时回查归档，`--include-archive` 显式合并两区；排序依次考虑标题精确匹配、标题包含、正文匹配，同档固定经验优先，其他保持来源顺序。默认最多 10 条，`--limit` 须为正数；截断会提示总数。`--include-content` 输出正文，`--json` 同时给正文、元数据和源位置，两者互斥。归档只表示移出常用区，适用性仍须核对。
- `add-todo` / `add-lesson`：从唯一的 `assets/` 模板创建记录，生成 UUID4 与初始元数据，保留已有内容；模板损坏在写入前失败。经验可用 `--pinned` 固定。要求 `.aitasks/` 已存在且目录、目标文件均非软链接；不修改 `.gitignore`。同名标题拒绝新建，仍须先检索语义相近的记录。标题不可换行，正文不可含未闭合围栏或围栏外的记录元数据、一/二级标题；已有未闭合围栏会隐藏新增记录时拒绝写入。
- `list-todos`：默认只列 3 条活动 todo 的 ID、标题与状态，`--query` 用空格分隔关键词筛选，`--limit` 调整数目；总输出默认最多 2000 字符，`--max-chars` 调整。`--status all` 包括完成/取消项，仍受限额；单条正文优先用 `get-record`，旧 `--include-content` 保留但有预算。`--json` 返回总数与截断状态，始终只读。
- `finish-todo`：用 `--id` 或唯一 `--todo` 选择已有记录，必填 `--result`，可填 `--verify`，一次更新正文、状态和完成日期；`--status cancelled` 用于取消。结果或验证小节不存在时追加，不覆盖其他内容。默认在同一把锁内检查并应用到期维护，归档冲突在记录写入前拒绝。
- `mark-used`：按唯一 `--lesson` 或 `--id` 更新实际采用且状态有效的经验；ID 支持查找归档，标题选择保留原有活动区范围。传入当前 todo 的 `--task-id` 后，每个任务只计一次，即使多任务交错调用也不重复；任务指纹与计数在同一记录中原子更新。查询、读取、未采用的候选不计，失效经验拒绝计数。归档更新与同日维护追加一起预检，避免覆盖；次数不代表正确性。
- `set-todo-status`：只修改 `status` 与 `completed_at`；`active` 会将 `completed_at` 重置为 `-`。
- `cleanup`：默认 dry-run；`--apply` 按保留期和容量规则把符合条件的记录移入 `.aitasks/archive/`，成功写入后才从活动文件删除。

经验查询 JSON 保留 `matches` 及各项的正文、元数据、计数与 `source` 绝对路径/行号，增加 `total_matches`、`truncated`、`searched_archive`。`use_count_status` 区分 `recorded`、`missing`、`invalid`，缺失或无效为 `null`。无匹配返回空数组，不写文件或计数。

`add-todo`、`add-lesson`、`mark-used`、`set-todo-status` 加 `--maintain` 后，与 `finish-todo` 一样在本次写入内完成阈值检查与必要归档，无需再跑 `status`。不带此选项的旧命令保持原行为，写后须补检查。阈值参数与 `cleanup` 相同；发生中途 I/O 失败时保留错误和已写路径，修复后用相同输入重试，仍按 ID 与内容核对恢复。

### 兼容与手工维护

下列入口仍受支持；新自动流程优先采用上面的 ID 与 JSON 示例。`set-todo-status` 不补任务结果，`add-lesson` 不执行二次观察准入；按标题且不传 `--task-id` 的旧计数调用不具备任务幂等性。

```bash
python3 -B "$AITASKS_TOOL" --project-root "$AITASKS_PROJECT" find-lessons --query "关键词" --include-content
python3 -B "$AITASKS_TOOL" --project-root "$AITASKS_PROJECT" status
python3 -B "$AITASKS_TOOL" --project-root "$AITASKS_PROJECT" cleanup
# 只有允许维护且预览符合预期时才应用
python3 -B "$AITASKS_TOOL" --project-root "$AITASKS_PROJECT" cleanup --apply
```

## 有界查询与会话复用

普通只读任务只需[短查询参考](query.md)，无需读取本维护流程。下列预算均为默认值，必要证据可增加读取量；不以总 token 必须下降作为验收条件。

- `context --query "模块 符号 错误码"` 是默认读取入口。关键词用空格分隔，以任一概念命中召回，概念覆盖数优先、再按标题命中数、相关固定经验排序。内置少量中英文同义组，每组只算一个概念，不把同义词堆叠成高分。默认各最多 3 条经验与活动 todo 摘要，总响应（含换行）不超过 2000 字符。`--lesson-limit`、`--todo-limit`、`--max-chars` 显式调整；字符预算不是 tokenizer 的精确 token 数。
- 摘要只含 ID、短标题、适用范围与预览，返回总命中数、截断状态及 `stamp`；不返回完整正文或使用任务历史。活动经验无命中、最佳匹配未覆盖全部查询概念或仅命中正文时，也合并归档排名；`searched_archive` 说明是否扫描过归档。本地扫描文件不等于把文件内容送入模型上下文。
- `get-record --kind lesson|todo --id …` 读取一条匹配记录，默认最多 2400 字符，超限在有效 JSON 中截断正文并标记；去除内部元数据，保留源路径与行号。经验 ID 先查活动区，未命中查归档；歧义或缺失报错，不返回全库。无元数据旧记录也能经摘要 ID 读取，不自动迁移。
- `context --since <stamp>` 只用于本会话已经读取、查询条件和文件内容均未变时；只返回 `unchanged` 可避免重复注入。它不写缓存文件，新会话必须不带 `--since` 获取相关摘要；不要把旧 stamp 持久化成跨会话跳过标志。
- `context`、`get-record`、筛选 todo 和旧经验查询都不创建目录、锁、计数或观察文件。旧 `find-lessons --json` 的完整记录输出保留兼容，按需显式使用，不作为默认批量加载入口。

可选 `.aitasks/search-aliases.json` 使用 `[["项目术语", "代码符号"], ["另一个术语", "同义词"]]` 格式扩充内置别名；只定义已确认同义关系，不将 `offset` 等多义词泛化为时区。组可重叠并自动合并；配置错误报错且不写入，映射变化会改变相关查询 stamp。别名只用于 `context` 检索，不重写观察签名；跨会话的签名一致性仍由 Agent 核对。

## 经验失效与替代

旧经验缺少 `status` 时兼容为 `active`。`retired` 表示经证据确认不再适用，`superseded` 表示被另一条有效经验替代；默认 `context` 和 `find-lessons` 均排除它们。显式 `find-lessons --include-inactive` 或 `get-record` 按 ID 审计，后者返回状态及替代 ID。

```bash
python3 "$AITASKS_TOOL" --project-root "$AITASKS_PROJECT" set-lesson-status --id "旧经验ID" --status superseded --superseded-by "新经验ID" --reason "CONTRACT.md:12 已改用新契约"
```

命令要求唯一的带元数据记录，支持活动区和归档；替代目标必须唯一、当前有效且不能指向自身。`--status retired` 不需要替代 ID，`--status active` 可恢复；原因写入原条目，保留额外笔记和 ID，并在同一锁内检查维护阈值。此命令不自动判断语义冲突，也不凭时间或归档位置判失效；`upsert-lesson` 不会默默复活失效记录。

## 观察、记录与更新

根因确认且准备观察前，用 `find-observations --query "模块 症状 原因"` 查询候选；默认最多三条、总输出 2000 字符，可显式调整 `--limit` / `--max-chars`。返回原 key、证据位置、次数、状态和关联经验 ID，不返回任务历史，不创建文件或更新计数。它复用查询别名扩展，但不据相似词合并签名。跨会话核对模块、症状和原因均一致时原样复用返回的 key；原因不同或证据不足则不合并，必要时读取证据位置或既有任务结果。不同独立任务使用不同 todo ID，同任务重试保留 ID。

仅在已允许维护写入、原因已验证且做法可复用时调用：

```bash
python3 "$AITASKS_TOOL" --project-root "$AITASKS_PROJECT" observe --key "模块.症状.原因" --task-id "当前todo的ID" --evidence "src/file.py:42" --verified
python3 "$AITASKS_TOOL" --project-root "$AITASKS_PROJECT" upsert-lesson --key "模块.症状.原因" --title "短标题" --context "场景" --problem "问题" --cause "已确认原因" --resolution "执行规则" --scope "适用条件"
```

- `observe` 在共用维护锁内维护 `.aitasks/.observations.json`，每个签名最多保存两个不同任务 ID 和一个短证据位置；不保存对话或日志全文，不提供全量读取入口。签名应稳定描述同一模块/症状/已证实原因，不能用每次变化的任务标题；同义归并由 Agent 核对。
- 返回 `candidate`（首次）、`ready`（二次）或 `recorded`（已有经验 ID）。同任务重试不加次数；超过两次不再扩张任务列表。未传 `--verified` 直接返回 `skip` 且不写文件；预期失败、原因未明、只读任务不应观察。
- `ready` 只证明次数，不能证明经验质量。Agent 仍须核对原因、适用范围和做法；`upsert-lesson --key …` 自动新建要求两个独立观察且原因非“未确认”，将证据位置带入经验。更新已有活动或归档经验，先按 ID 读取核对，再传 `--id`；已关联的 key 可直接定位原 ID。只按标题匹配不自动覆盖：同标题时核对内容，确属同一经验则指定 ID，否则使用有区分度的标题。
- 用户明确要求记录时用 `upsert-lesson --explicit`，不等待二次，未知原因可标“未确认”；不带签名时不依赖观察文件。自动流程优先用该命令，旧 `add-lesson` 保留手工兼容。
- `upsert-lesson` 自动检查归档阈值；观察本身不改经验/todo 数量，无需额外归档。新建经验时记录关联签名，记录先写、观察关联后写；部分失败可用相同输入重试并复用已生成 ID。旧记录若缺少该签名且关联未完成，须读取核对后显式传 ID，不按标题猜测。归档经验可在同一维护锁内按 ID 原位更新，ID 重复或记录不存在时停止；不擅自重建历史。
- 更新单行字段时保留后续自由文本及其他笔记。若已有字段首行为空且后续是多行内容，工具无法安全区分字段正文和附加笔记，会在写入前停止；读取原文后手工核对更新，再补做维护阈值检查。
- 观察状态损坏时保留原文件并报错；Agent 不能伪造 `--verified` 或 `--explicit` 代替事实/授权。工具计数和单元测试不证明宿主每次都会选择正确的记忆动作，真实触发仍需行为验收。

## 维护与归档阈值

任一条件满足时自动执行归档：距 `.aitasks/.maintenance.json` 的 `last_cleanup_at` 至少 30 天；带元数据经验达到 100 条；已完成或取消 todo 达到 20 条。`status` 与 dry-run 不更新状态；`cleanup --apply` 即使没有符合条件的记录也更新检查日期，但不创建空归档。

| 记录 | 条件 | 保留期 |
|---|---|---|
| 经验 | `use_count=0` / `=1` / `>=2` | 90 天 / 180 天 / 365 天 |
| todo | 已完成或取消 | 30 天 |

`pinned=true`、活动 todo 和无有效元数据的旧记录不归档。工具只清理活动文件，不自动删除旧归档。需要立即检查时给 `status` 或 `cleanup` 加 `--force`。

达到数量阈值时，即使记录未达到保留期，也按最旧优先归档超出容量的条目：经验优先归档未使用、再归档使用一次、最后归档多次使用的非固定记录；todo 只归档已完成或取消的记录。目标是使对应活动记录数低于触发阈值；固定经验或活动 todo 太多时可能无法达到目标，此时保留并说明。归档仍可恢复，不直接删除记录。

## 归档步骤

1. 按保留期筛选到期记录；达到数量阈值时，再按上述容量规则补选超额记录。逐条读取元数据注释，比对 `completed_at`/`last_used_at` 与当天日期。
2. 建档归档文件 `.aitasks/archive/todo-YYYY-MM-DD.md` 或 `lessons-YYYY-MM-DD.md`（同日已存在则追加）。
3. 归档文件头部写明来源：`<!-- archived_at=YYYY-MM-DD source=todo.md -->`。
4. 将到期记录原样移入归档文件（保留元数据注释），再从活动文件删除对应段落。
5. 核对剩余记录内容和顺序完整；不为整理空白重写无关段落。维护检查成功后更新 `.aitasks/.maintenance.json` 的 `last_cleanup_at`，没有到期记录也记录检查日期，但不创建空归档文件。

## 幂等与安全

- 新记录使用各自唯一的 UUID4 十六进制 `id`；旧记录没有 `id` 时，归档工具仍可推导兼容 ID，但若两条活动记录 ID 相同，或活动内容与已有同 ID 归档内容不一致，就中止清理并保留活动文件，等待人工核对。归档读取失败也中止，不跳过损坏文件。
- 中途失败后可重试 `cleanup --apply`：只有 ID 和正文均与已有归档一致时，才跳过重复追加并继续移走活动记录。
- 锁文件中 PID 仍存活时，即使超过 300 秒也不自动回收；只有 PID 已退出，或锁文件未写入有效 PID 且超过 300 秒时才回收。持久的 guard 文件不能删除，否则并发进程可能锁住不同文件；释放时同时核对 inode 和唯一令牌，避免 inode 复用时误删替换锁。无法确认时保留锁并手动核对。
- 追加经验到已有 `lessons.md` 时只追加或在保留原内容基础上合并，禁止未读取原内容就整体覆盖。
- 归档是删除的前置步骤；不确定是否到期时保留记录并说明原因。

## 复用经验

- 允许维护写入且实际复用经验解决问题后，将该条 `use_count` 加 1、`last_used_at` 更新为当天；只读查询不更新计数。
- 经验只记录可复用内容（场景、问题、原因、正确做法、适用范围），不记录流水账。

## 模板

路径相对本 Skill 根目录：

- todo 模板：`assets/todo.md`
- 经验模板：`assets/lessons.md`
