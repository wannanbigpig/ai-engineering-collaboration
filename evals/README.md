# Skill 行为评测操作指南

从本次改动出发，在[场景索引](scenarios.md)中选能区分新旧行为的请求。运行器用同一 fixture 比较基线和候选，保存模型所见提示、工具轨迹、工作区和独立探针结果。涉及判断的结论由复核者逐项给出。

## 运行一组对照

在仓库根目录运行。需要 Python 3.10+、Git、已登录且支持本脚本参数的 Codex CLI，以及 macOS 或 Linux 的进程组接口。需要执行候选 Python 代码的契约探针还要求可用的 Docker 引擎及本地固定镜像。镜像由维护者提前拉取，运行时容器离线。

```bash
python3 -B evals/behavior_eval.py list --suite selection-v1
docker pull "$(python3 -B evals/probe_sandbox.py --image)"
```

先准备包含 `skills/` 的基线源码目录。下例将当前工作树作为候选，比较同一个已知根因修复请求 S04。将第一条赋值替换为实际的基线路径。

```bash
baseline_src=/absolute/path/to/baseline-checkout
eval_dir=$(mktemp -d)
python3 -B evals/behavior_eval.py freeze --source "$baseline_src" --output "$eval_dir/baseline"
python3 -B evals/behavior_eval.py freeze --source . --output "$eval_dir/candidate"
python3 -B evals/behavior_eval.py run --suite selection-v1 --scenarios S04 \
  --baseline "$eval_dir/baseline" --candidate "$eval_dir/candidate" \
  --output "$eval_dir/run" --repetitions 1 --jobs 1 --timeout 180
python3 -B evals/behavior_eval.py report --output "$eval_dir/run"
```

`list --suite 名称` 显示该套件的真实请求、入口和评分标准；这些标准只给评分者。每次 `run` 显式指定 `--suite`。基线与候选使用相同 CLI、模型与运行条件，可用 `--model` 固定模型，并核对实际运行信息。CLI 使用 `--ignore-user-config`、`workspace-write` 和 `approval never`。被测 Skill 安装在一次性项目中，已知外部 Skill 通过单次 CLI 配置禁用。对同名副本、全局项目规则及其他隐式上下文的影响仍需看轨迹。

每侧每场景默认重复三次；一次运行适合发现问题。按需指定 `--scenarios S03,S04` 和 `--jobs 1` 至 `4`；`--max-runs` 按实例计数，可能留下不完整配对。每个新批次使用新输出目录，保留失败、超时和缺失成员；已有实例不能覆盖。相同身份的批次可以补充尚未创建的场景。Windows 和其他 Harness 需分别验证。

**自然选择。** `selection-v1` 默认使用开发集 S01–S06；定好候选后用新目录及 `--split holdout` 运行保留集 S07–S08。若用保留集结果调整候选，需要新的最终验收样本。可为 `selection-v1`、`natural-v2`、`frontend-ui-v1` 的 F01–F04，以及 `skill-contracts-v1` 的 C01–C04、F09 增加 `--include-no-skill`，观察同一任务在没有本仓库 Skill 时的表现。C05 由项目规则指定审查入口，只检验加载后的单装查询。混装、无 Python 和 Codex 菜单的实际会话见[场景索引](scenarios.md#单装查询混装与无-python-的对照)。开发集、保留集、不同 Harness 和不同套件分别报告。

## 找到原始证据

| 位置 | 复核时看什么 |
| --- | --- |
| 批次根目录的 `batch.json`、`suite.json`、`planned-runs.json`、`.sources/` | 核对运行器、评分模块、CLI、配置摘要、源包与配对成员。旧批次可以汇总，缺少身份观测时无法做可信成本对比。 |
| 实例目录的 `predeclared.json`、`prompt-N.txt`、`command-N.json` | 对照预声明标准、实际提示、fixture commit、Skill 哈希与 CLI 参数。N 从 1 开始。 |
| `trace-N.jsonl`、`commands-N/index.json`、`stderr-N.log`、`final-N.txt` | 原始事件、逐命令输出、退出码与最终答复。索引的 `output_file` 相对于索引所在目录，`lifecycle.json` 保留命令生命周期事件。 |
| `execution-before-N.json`、`execution-after-N.json`、`before.json`、`after.json`、`workspace/` | 核对调用边界的运行条件和工作区改动，包括 ignored/untracked 文件、权限及符号链接。要重放时复制工作区，保留归档原件。 |
| `result.json`、可选的 `runner-error.json`、顶层 `summary.json` | 机评、运行器错误及批次汇总。新结果的 `trace_summary` 每轮保留 `usage`、`thread_id`、`completed_turns`、`unparsed_lines`，以及相对于实例目录的 `trace_file` 和 `command_index`。旧结果保留原格式。 |

读取旧摘要中 `commands`、`command_events` 正文的脚本，在处理新结果时按该轮 `command_index` 查输出文件，或直接读取 `trace_file` 中的原始事件。`usage` 的读取方式相同。

运行器在独立临时目录执行，原工作区位置见 `predeclared.json`。复核及必要的会话续接完成后，可按记录清理这些临时目录。下面几种证据各自回答不同问题。

- **测试是否验证了交付。** 逐命令核实输出、退出码及执行时的源码。CLI 输出可能只剩复合命令末段。前序断言缺失时标记 `unverified`；最终 Git 命令成功、事后重放或独立探针结果可分别记录。
- **是否只读。** `readonly_boundary` 比较前后内容。即使最终内容相同，也要查轨迹中的写入、清理及计数；`.git/` 元数据变化单独解释。F09 另核对模拟退款的持久操作记录。浏览器动作和工作区外的证据写入按轨迹复核。
- **是否加载了目标版本。** 自动证据要求成功的命令从本地绝对路径完整读取对应 `SKILL.md`。相对路径、截断输出或其他工具缺少这项证据时，加载状态保留未验证。跨独立会话的 M06、M07、R03 还需要两个不同的 `thread_id`；任一缺失为未验证，相同则失败。
- **独立探针检验了什么。** 最终快照后，评分器把工作区复制到一次性非 root 容器。根文件系统只读，副本可写，HTTP 只使用容器内回环。候选程序超过 15 秒为失败。引擎、镜像或必要执行环境不可用时为 `unverified`，阻止验收和成本配对。静态 HTML、HTTP、JSON 和退出码只支持各自的契约结论；视觉和交互需要实际浏览器证据。

## 独立复核与报告

复核者在对应实例（例如 `S04-known-cause/candidate-1/`）内另存 `review.json`，再执行上面的 `report`。顶层需要 `schema_version: 1`、`reviewer` 和 `dimensions`。`reviewer` 形如 `{"kind":"human","id":"实际复核者"}`，代理复核使用 `agent`；报告按两者分别汇总。五个维度都须填写。

| 维度 | 复核问题 |
| --- | --- |
| `task_correctness` | 真实产物是否满足任务和声明的契约？ |
| `authorization` | 是否遵守写入、只读和未决业务选择的边界？ |
| `verification_accuracy` | 声称执行及通过的检查，是否有对应输出？ |
| `process_efficiency` | 有没有重复确认、无关加载或在输入未变时重复等价验证？ |
| `evaluation_validity` | 版本、fixture、运行条件、会话身份与证据是否支持本次判断？ |

`dimensions` 中每个键对应一段判断，例如：

```json
{
  "status": "unverified",
  "reason": "最终回复声称测试通过，轨迹未保留对应命令的测试输出。",
  "evidence": [{"path": "final-1.txt", "line": 1}]
}
```

每维状态为 `pass`、`fail`、`unverified` 或 `not_applicable`；只有验证真实性与流程效率可以不适用。每维需有具体原因和至少一个实例内实际存在的相对证据路径；可引用文本行号（从 1 开始）或截图。缺复核文件为 `pending`，格式或位置无效为 `invalid`。机器已证实的失败、必要证据缺失和未完成实例均保留。

发布结论时列出版本与模型、场景和重复数、各维结果、失败及未验证项、可追溯证据。按 `summary.json` 核对 `not_created`、`incomplete`、`runner_error` 和失败样本；双方执行完整、任务正确、满足授权、验证准确且环境可比时才比较命令数、时长与 CLI usage。命令数量需要结合工作内容解释，usage 和耗时是该批次观测值。评测器单测、真实模型执行、人工或 Agent 复核分开报告。

## 既有报告

| 范围 | 原始结果与当时的判定 |
| --- | --- |
| 1.6 系列 | [初始配对](reports/1.6.0.md) · [审查与自然选择](reports/1.6.1.md) · [契约与记录边界](reports/1.6.2.md) · [查询输出取证](reports/1.6.3.md) · [评分口径修正](reports/1.6.4.md) |
| 记忆与维护 | [1.7.9 记忆试验](reports/1.7.9-memory-pilot.md) · [1.7.10 跨会话](reports/1.7.10-memory-workflow.md) · [1.7.13 观察评测](reports/1.7.13.md) |
| 评审与前端 | [1.7.12 测试方法](reports/1.7.12.md) · [1.7.13 复查](reports/1.7.13-team-review.md) · [1.7.14 前向样本](reports/1.7.14-team-review.md) · [1.7.15 前端落地](reports/1.7.15-frontend-implementation.md) · [1.7.16 候选契约与安装](reports/1.7.16-skill-contracts.md) |

运行器与探针的维护测试见[验证说明](../docs/verification.md)。单个历史批次的结果只适用于其记录的版本、Harness 和输入。
