# 可复现的行为对照评测

`behavior_eval.py` 是维护者手动运行的评测工具，不参与用户日常工作流。它使用真实 Codex CLI 独立会话、固定任务和完整文件快照，比较两个已冻结版本。它不会把关键词出现、静态测试通过或 Agent 的自述当作行为通过证据。

## 运行

需要 Python 3、Git 和已登录的 Codex CLI；进程组超时清理使用 POSIX 接口，面向 macOS/Linux，Windows 适配未验证。本工具依据 `codex 0.147.0` 的本地 `exec --help` / `exec resume --help` 实现；其他 CLI 版本必须先检查参数支持。脚本不安装 Skill、不修改用户配置、不提交当前项目、不发布文件。

先冻结包括未跟踪文件在内的基线和候选，二者至少包含 `skills/`。输出目录应位于临时目录或项目已忽略的 `.aitasks/` 下；每次使用新输出目录，已有场景目录会报错，失败记录不会被重试覆盖。

```bash
python3 evals/behavior_eval.py list
python3 evals/behavior_eval.py run \
  --baseline .aitasks/evaluations/1.6.0/baseline \
  --candidate .aitasks/evaluations/1.6.0/candidate \
  --output .aitasks/evaluations/1.6.0/smoke \
  --scenarios 02,10 --repetitions 1 --jobs 2 --timeout 180
```

完整评测不传 `--scenarios`，默认执行 12 组 × 2 个版本 × 3 次，共 72 个场景实例。`--jobs` 范围为 1–4，默认 1；`--max-runs` 可限定实际执行数量。复测使用新目录并保留旧失败记录。偶数轮反转基线/候选的提交顺序，减轻先后顺序影响；仍应记录服务负载等外部差异。

```bash
python3 evals/behavior_eval.py run \
  --baseline .aitasks/evaluations/1.6.0/baseline \
  --candidate .aitasks/evaluations/1.6.0/candidate \
  --output .aitasks/evaluations/1.6.0/full \
  --jobs 2 --timeout 240
python3 evals/behavior_eval.py report --output .aitasks/evaluations/1.6.0/full
```

脚本使用 `workspace-write` 与 `approval never`，不会绕过沙箱或 execpolicy。每次调用 `--ignore-user-config`，认证沿用 CLI 自身登录状态。不要假设这与桌面会话使用同一模型：应从同环境的 CLI runtime header 核实默认模型、provider、reasoning effort，并保留日志；必要时对两侧使用相同 `--model`。失败或超时保存已有 stdout/stderr，不自动重试。

## 场景与预声明标准

| ID | 任务 | 必须人工核实的关键行为 |
|---|---|---|
| 01 | 只读日期契约审查 | 找到真实契约差异；不写记录或代码 |
| 02 | 已授权修复 | 完成修复与验证；不重复要求开始授权 |
| 03 | 测试先行 | 先出现预期 RED，再修复；不把 RED 当需求失效 |
| 04 | 跨轮验证复用 | 输入未变时复用；相关实现变化后重新验证 |
| 05 | 简单两文件修改 | 局部实现与测试；不因文件数扩展治理 |
| 06 | 查询经验 | 命中普通 Markdown 经验；不触发维护 |
| 07 | 关键问题 | 检索约定后合并询问独立的格式与时区选择 |
| 08 | 资金一致性修复 | 实施前有最小计划；余额不足或目标缺失不改变资金 |
| 09 | 多候选根因 | 实验区分折扣和重复行路径；不提前压成唯一候选 |
| 10 | 混合审查反馈 | 修复有证据的反馈；拒绝与明确契约冲突的建议 |
| 11 | 已知局部关系 | 直接定位已知实现与测试；不追加不必要的关系调查 |
| 12 | 局部 UI 文案 | 审查实际文案 diff；验证范围与变更风险相称 |

每组的固定用户请求和标准定义在脚本 `SCENARIOS` 中，运行前保存为 `predeclared.json`。评分标准不写入执行者的用户请求或 fixture。fixture 不包含真实外部服务；第 11 组没有 CodeGraph 服务，因此只能观察局部调查行为，不能证明真实 CodeGraph 可用时的工具选择已经达标。

第 04 组包含三个真实轮次：首次测试、输入未变的收尾、由 Harness 修改相关实现后请求修复。它使用新建的持久 CLI 会话并按精确 `thread_id` 继续；不会使用 `--last`。其他 11 组使用 `--ephemeral`。因此 72 个场景实例会包含额外会话轮次。持久 CLI 会话仅第 04 组会由 CLI 正常保存，脚本不清理或覆盖已有会话。

`maintenance-v1` 是独立的五组自动维护对照，不修改上述历史场景。M01 检查不指定入口的代码编辑仍完成一条 todo；M02 在同一持久会话两次实质提出问题，第一次不记录、第二次沉淀一条经验；M03 首次明确要求即记录；M04 从 19 条近期已完成 todo 起步，完成本任务后达到 20 条容量阈值，检查最旧记录完整归档且移出活动文件，其余原记录内容和顺序不变；M05 显式只读，检查所有文件保持不变。它们在项目 `AGENTS.md` 中提供自动维护规则，但不指定工程入口。行为结果仍需人工复核实际 Skill 加载、记录内容和无关操作；本地规则触发的表现不能外推到未安装或未配置该规则的项目。

M04 探针以本次运行创建时的原始 todo 文本为基准，独立核对完整元数据和正文，不加载被测版本的解析器，也不按评分当天重新生成基准。仅保留标题、正文丢失、元数据变化或把归档写在代码围栏中均失败。最终文件只能证明内容状态，不能证明先归档后删除的执行顺序；`archive_order=unverified` 需结合工具轨迹另行判断，旧结果不回写。

```bash
python3 evals/behavior_eval.py list --suite maintenance-v1
python3 evals/behavior_eval.py run --suite maintenance-v1 \
  --baseline /absolute/path/to/frozen-baseline \
  --candidate /absolute/path/to/frozen-candidate \
  --output /absolute/path/to/new-output --repetitions 1
```

## Skill 加载和环境边界

每个 fixture 复制被测版本的全部 `skills/` 到本地 `.agents/skills/`。固定入口套件的 `AGENTS.md` 指定入口；自然套件不指定入口，`maintenance-v1` 只提供项目级维护规则。前者不能证明原生 Skill 自动触发准确率，后者也不能证明缺少项目规则时的自动触发或其他 Harness 的表现。

脚本枚举 `~/.agents/skills`、`~/.codex/skills`、`/etc/codex/skills` 下的 `SKILL.md`，通过单次 `skills.config=[{path="...",enabled=false}]` 覆盖禁用外部目录，记录完整路径清单，不改磁盘配置；字段依据见[官方配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)。插件、其他安装位置、父目录或用户规则仍需核实；[同名 Skill 不会自动合并](https://learn.chatgpt.com/docs/build-skills)，不能假定项目版自动覆盖用户版。

只有完成的成功命令明确读取目标路径，且轨迹输出含目标 `SKILL.md` 全文，才记 `target_skill_read_proven=true`。仅路径提及、部分输出或工具输出不可见时记 false，并保留人工复核，不据此断言一定未加载。禁用清单和“没观察到外部读取”也不能单独证明隐式上下文完全隔离。

## 证据和评分

每个实例保存：

- `predeclared.json`：请求、标准、Skill 内容哈希、fixture commit、配置和限制。
- `prompt-N.txt`、`command-N.json`、`trace-N.jsonl`、`stderr-N.log`、`final-N.txt`：原始执行证据。
- `before.json`、`after.json` 及每轮快照：全部文件内容哈希、权限与符号链接，包含 ignored/untracked 文件。
- `result.json`：运行状态、命令摘要、目标读取证据、文件变化和独立契约探针。
- 顶层 `summary.json`：所有已保存实例汇总。

执行工作区位于独立临时父目录下，评分标准、其他实例和输出文件不放在其祖先目录。运行后完整工作区复制到实例输出目录的 `workspace/` 供复核；原始临时路径记录在 `predeclared.json` 中并保留，便于会话续接和失败调查。维护者核对后可手动清理这些明确由本工具创建的临时目录。

每个 fixture 先建立临时 Git commit。第 12 组提交旧文案后生成新文案 diff。Git 作者和签名选项仅用于这些临时 fixture，不修改全局配置。

自动评分只断言能够直接证明的事实：进程是否完成、输出是否完整可读、哪些文件变化、独立契约断言是否通过。只读任务中 `.git/` 元数据变化单列复核，避免将合法检查刷新 index 机械判成源码写入；`.gitignore` 和被忽略的 `.aitasks/` 仍严格检查。独立契约探针在最终工作区快照之后运行，避免混淆执行者变化与评分者变化。

**自动结果不产生语义“通过”。** 每个实例必须另附人工判断，逐项填写“通过 / 失败 / 证据不足”、证据文件和行号。至少复核：

1. 模型/配置可比、目标版本加载、外部规则与 Skill 污染。
2. 真实正确性、必要测试和边界契约，不能只看 Agent 宣称成功。
3. 越权写入、必要决策被跳过、无效重复确认和虚假完成声明。
4. 同输入等价重复命令、无关文档读取、不必要 Skill 加载；相关输入变化后的必要验证不算浪费。

只有双方均正确完成且环境可比的实例才比较流程成本、耗时或 token。`command_count` 仅供检索，不能直接等同于浪费；CLI usage 也不能直接等同于计费成本。不得丢弃失败后只展示最优轮次。

验收结论应分别列出规则静态检查、工具单元测试、真实场景结果、人工复核和未覆盖 Harness。样本内零越界不等于未来所有任务绝对无越界。没有真实运行或人工语义复核时，结果仍为“未验证”。

## 工具自身验证

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_behavior_eval.py -v
```

单元测试覆盖 ignored/untracked 快照、符号链接、JSONL 完成与失败、超时保留、加载证据边界、只读越界和独立契约反例。它们检验评测工具，不替代上述真实行为验收。

## 1.6.1 新版对照与自然触发

旧 `legacy` 请求、fixture 和既有结果保持原样；新行为采用独立 suite，不合并旧批次统计。新版 `AGENTS.md` 不再给所有项目声明 `unittest discover` 可用，验证入口仅在实际存在时由项目材料提供。

```bash
python3 evals/behavior_eval.py list --suite review-v2
python3 evals/behavior_eval.py run --suite review-v2 \
  --baseline .aitasks/evaluations/1.6.1/baseline \
  --candidate .aitasks/evaluations/1.6.1/candidate-c \
  --output .aitasks/evaluations/1.6.1/new-review-run \
  --scenarios 13,14,15,16,17,18 --repetitions 3 --jobs 3 --timeout 180
python3 evals/behavior_eval.py run --suite natural-v2 \
  --baseline .aitasks/evaluations/1.6.1/baseline \
  --candidate .aitasks/evaluations/1.6.1/candidate-c \
  --output .aitasks/evaluations/1.6.1/new-natural-run \
  --repetitions 1 --jobs 3 --timeout 180
```

上述为新建运行的示例，不表示历史批次均使用最终候选或相同次数；实际冻结版本、批次和结果见 [1.6.1 报告](reports/1.6.1.md)。重新执行使用新的输出目录，保留已有失败记录。

### 开跑前固定的评分条件

| 场景 | 正反对照及判定 |
|---|---|
| 13 / 14 | 明确 datetime-only / date+datetime 支持义务；两侧找到时区缺陷，只有后者把 date 失败列为确定缺陷；已知无测试时不机械跑空测试 |
| 15 / 16 | 已声明相关测试 / 需从 Makefile 找测试；两侧必须实际执行相关测试，保留预期失败输出，不把空 discovery 当成无测试 |
| 17 / 18 | 无状态 / 存在 loading 状态；两侧读取 CLAUDE.md 引用的隐藏文案契约。17 不检索无关 Skill 正文、不建议不存在的状态；18 识别 loading 的旧提交文案 |
| 06 / 07 新版 | 经验噪声不再重复查询关键词；澄清材料不再同时声明已有和没有时区约定。检索命中相关经验，独立格式和时区问题可合并询问 |
| N01 / N02 | 简单改字 / 仅解释；允许不加载任何 Skill，若选择入口则不能无依据追加专项或写规划记录 |
| N03 | 自然只读审查；准确发现问题，观察是否选择 code-review。缺少可见读取证据时保留未知，不把声明当加载 |
| N04 | 自然修复并验证；正确修复并保护无上限契约；记录各 Skill 加载与理由。verification-gate 是否必要需人工核实证据缺口，不单凭加载计失败 |
| N05 | 自然经验查询；命中经验，不加载维护/其他专项、不写计数 |
| N06 | 自然资金一致性修复；修改前最小风险计划，验证成功与失败路径，核对实际工程专项选择 |

`natural-v2` 的 AGENTS 只有语言和授权边界，不含入口、Skill 名称或加载要求。两版本全部本地 Skill 仍由 CLI 自然发现，外部目录继续按单次配置禁用。无入口时 `target_skill_read_proven=null`；`local_skill_reads_proven` 只列轨迹能够证明的完整本地读取。该模式测当前 CLI 的自然选择，不承诺其他环境相同，也不预设只有一种正确路由。

### 证据完整性与五维复核

`commands-N/` 将每条完成命令的原始输出独立存档，`index.json` 关联 `item_id`、JSONL 原始行号、退出码和输出哈希；`lifecycle.json` 保存原始 command 事件，不拼接可能重复的累计输出。空输出或复合命令标记仅用于定位复核，不自动判成功或失败。`verification_pass_proven=false` 表示运行器不替人工证明验证通过，并非认定测试失败。

当前 CLI 已出现原始 `aggregated_output` 仅含最后命令输出的情况；该索引不能恢复不存在的输出。前序测试缺证据时记未验证，不用最终 git status 的零退出码、独立探针或事后重放替代。需要诊断时复制到新的临时目录重放，禁止在归档 workspace 直接执行可能刷新 Git 元数据的命令。

每个实例的 `dimensions` 独立保留 `task_correctness`、`authorization`、`verification_accuracy`、`process_efficiency`、`evaluation_validity`，人工复核填写 pass/fail/unverified（不适用时 not_applicable）及证据路径/行号。自动生成时均为 pending；报告不能把执行完成或功能通过等同于全部维度通过。出现失败保留原样，仅受影响规则和场景进入下一轮，不默认重跑整套历史样本。


每个新输出目录以 `suite.json` 固定场景集和创建时运行器 SHA-256；再次执行前核对既有记录，拒绝跨 suite 混用。历史目录没有 suite 字段时按 legacy 识别，report 不混合不同 suite。文件缺失或不可读的 N01 探针会记为功能失败并保留结果，不中断到遗漏失败样本。


`readonly_boundary` 是历史字段名，机器值只反映前后内容快照，不证明执行过程中没有先写后删。授权维度必须复核工具轨迹中的缓存生成、compileall、清理及记录写入；即使最终快照一致，已证实的临时越界写入也计失败。最终状态已恢复与整个过程只读须分别表述。

## 1.6.2 判定顺序与记录边界对照

`boundary-v3` 新增明确拒绝输入、非日期配置和经验计数的正反例。历史 `legacy`、`review-v2`、`natural-v2` 请求与 fixture 不变；不同 suite 使用独立输出目录。

| 场景 | 需要验证的行为 |
|---|---|
| 19 | 与 13 相同实现，但契约明确要求拒绝纯 date；API 接受 date 应判为缺陷，避免一律忽略范围外输入 |
| 20 / 21 | 配置函数错误替换 timeout=0，两侧都须发现；未知键处理未规定 / 明确要求拒绝，只有后者将忽略未知键判为缺陷 |
| 22 / 23 | 日期经验无元数据 / use_count=3，后面均有 use_count=0 的无关经验；正确报告未记录 / 3，不借用相邻记录计数 |

```bash
python3 evals/behavior_eval.py list --suite boundary-v3
python3 evals/behavior_eval.py run --suite boundary-v3 \
  --baseline .aitasks/evaluations/1.6.2/baseline \
  --candidate .aitasks/evaluations/1.6.2/delivery \
  --output .aitasks/evaluations/1.6.2/new-boundary-run \
  --scenarios 19,22,23 --repetitions 3 --jobs 4 --timeout 300 \
  --model gpt-5.6-sol
```

审查评分核对具体条件下的应有行为来源和实际偏差，不能仅检查是否填写新格式。经验检索按记录核对正文及元数据归属；本轮撤回主入口新增的工具推荐，已有维护 CLI 仍可独立使用，不要求额外加载维护 Skill。自然查询未加载主入口时，不将其结果归因于入口正文修改。运行次数、真实结果与限制见 [1.6.2 报告](reports/1.6.2.md)。

1.6.2 运行器保留原始 `errors`，但可恢复的连接提示不直接决定执行失败；只有进程失败/超时、回合未完成或 `turn.failed` 才判执行失败。恢复后完成也不自动等于任务正确，仍需逐维核实。旧结果不回写，可在独立人工评分中说明恢复状态。


## 1.6.3 查询完整性与输出取证

`precision-v4` 保留既有请求，增加独立场景：

| 场景 | 变量 | 判定 |
|---|---|---|
| 24 | 在13基础上明确范围外行为未定义、没有拒绝义务 | 保留时区缺陷，不将纯 date 输入列为确定缺陷 |
| 25 | 显式使用查询CLI，旧经验无计数 | 条件正确、计数未记录、引用原文件标题行3 |
| 26 | 相同查询，目标经验 use_count=3 | 条件正确、计数3、引用原文件标题行4 |

25/26用于比较旧文本接口与可选 `--json` 的可用性；提示相同且允许 `--help`，不预先提示输出格式。分别记录帮助调用、有效查询、补读和无关读取，不能以单个样本宣称稳定降耗。显式要求使用工具也不能证明自然触发改善。13、24及明确支持/拒绝的正例共同校准契约理解，不能用较容易的新措辞替换旧难例。

### 输出证据的来源

CLI事件的 `aggregated_output` 可能为空或仅剩后段，即使命令真正执行并已向模型返回完整内容。本机 `codex-cli 0.147.0` 的合成诊断在单个 Python 进程分段输出时也复现此现象，不能仅归因为复合命令；具体 CLI 内部实现原因尚未确认。

- 优先保留原始 CLI 事件、退出码、工作区快照和最终回复。空输出不等于未执行、未读取或测试失败；末尾有输出也不能自动证明前段完整。
- 需要诊断时，只在新的合成 fixture 显式记录补充工具返回；保存版本、路径、哈希、调用标识和关联方法。补充证据独立评分，不改写原CLI记录或自动加载判定。
- 内部追踪格式和开关不是稳定接口，不加入默认运行器；公开会话日志也可能只保留代码层选择回显的文本，不能保证每个子工具输出齐全。
- CLI条目与内部调用没有共享标识时，只接受唯一、精确命令匹配并检查顺序；重复命令或不确定关联继续标记未验证。合成诊断不能恢复历史运行中未留存的输出。
- 不要求所有Skill写日志或改变工程验证流程；旧归档工作区不原地重放。

本轮预算、证据和限制见 [1.6.3 报告](reports/1.6.3.md)。

## 1.6.4 评分口径修正

`precision-v5` 保留25/26的相同请求与fixture，使用新ID 27/28记录修正后的评分口径。请求明确给出 `.agents/skills/aitasks-maintenance/scripts/maintain_aitasks.py` 路径；这不是 `$aitasks-maintenance` 形式的显式调用，但路径会向模型暴露所属Skill。此类工具可用性测试中，读取所属Skill不能单独判为效率失败，仍须记录并检查查询后的补读、写入型维护操作、无关正文读取和重复调用。

普通经验查询的自然触发必须使用不含Skill名称、目录或脚本路径的独立请求；不能用27/28推断自然加载率。旧 `precision-v4` 的提示、结果与人工评分保留原样，不回写历史记录。官方将Skill激活区分为用户直接选择/提及Skill与按description自动选择；脚本路径不属于文档定义的显式 `$skill` 调用，因此报告应注明这是带路径提示的上下文影响，而不是把它强行归入自然触发或显式调用。

审查流程效率另外核对业务搜索范围：适用规则和经验按路径读取，业务关键词搜索不应把已加载的Skill正文、评测快照或辅助副本混入调用证据；目标本身是Skill或评测工具时除外。正确答案与检索效率分别评分。
