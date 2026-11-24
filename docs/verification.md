# 验证说明

本仓库可自动验证 Skill 结构、版本一致性和 Markdown 空白；不同 Agent Harness 的发现与自动触发行为需要在目标环境中人工确认。

## 四层测试及结论边界

| 层级 | 检查什么 | 何时执行 | 能说明什么 |
| --- | --- | --- | --- |
| 格式与分发 | frontmatter、版本、单个 Skill 的资源引用 | 每次 CI | 文件结构和引用满足已检查的格式要求 |
| 工具行为 | 锁、归档、幂等、JSON 与评测器反例 | 相关变更定向跑，CI 跑完整套件 | Python 实现满足已测输入与副作用契约 |
| 触发选择 | 自然请求、相似负例、固定入口对照 | description、入口或边界改变时 | 在所测任务/模型下的选择表现；显式调用不能代替自然触发 |
| 任务效果 | 无技能/旧版/候选对照，正确性、授权、验证真实性与成本 | 相关行为变化时定向运行 | 是否有可见净收益；少量重复用于发现回归，不证明统计显著或普遍改善 |

关键词测试只保护历史措辞线索，不作为行为通过依据，也不继续扩写成“背诵规则”评分。语义判断明确标为 Agent 或人工复核；机器探针与评审结论分开，评审者不能用自己的最终宣称替代工具输出。开发集用于调优，保留集在候选冻结后验收；用保留集选优后必须另留新场景。

轻量源码探针无法判断等价实现时，可由实际页面或语义复核补证；缺少必需会话身份、只读边界证据时，单例及成对成本比较仍保留未验证。观察探针用 `required_evidence_unverified` 标记这类缺口，复核通过不能直接补成身份事实。

开源方法对照及 1.7.12 的实际验证与失败样本见 [1.7.12 报告](../evals/reports/1.7.12.md)。

工具修复、批次一致性及当前观察规则的验收见 [1.7.13 报告](../evals/reports/1.7.13.md)。历史 `maintenance-v1/M02` 保留原口径，当前允许首次观察的规则改用 `maintenance-v2`；同因、异因和单装缺工具分别验收，不放宽明确只读的边界。

## 本地与 CI 校验

```bash
python3 -B scripts/validate_repository.py --tests
```

统一入口先检查发行目录清单、各 Skill 版本与本地资源，再调用固定版本 `skills-ref==0.1.1` 和 `git diff --check`。`--tests` 追加单测，任一步失败即返回非零。`--offline` 跳过外部结构校验，保留差异检查和已启用的测试，并明确输出结构校验未运行。

只读查询的维护端和四个消费者使用同一源码；统一入口还核对生成脚本及别名资产的字节和权限。变更权威实现后先运行 `python3 -B scripts/sync_query_tools.py --write`。独立安装回归每次只复制一个 Skill 到临时目录。四个消费者逐个执行查询，比较前后快照以确认只读；维护工具单独执行任务创建和完成。

差异空白检查覆盖工作区与暂存区。资源检查按 `skills@1.9.0` 排除 `metadata.json` 和 `.git/`、`__pycache__/`、`__pypackages__/` 目录，支持常见的内联或引用式 Markdown 链接和可选标题，跳过普通围栏及行内代码。HTML 链接、嵌套容器或标签及多行引用定义需另行核对。

GitHub Actions 的 Linux/Python 3.12 主任务运行统一校验，并要求容器探针和 Node.js 22.20.0 的安装冒烟实测。兼容性任务分别使用 Linux/Python 3.10 和 macOS/Python 3.12 运行单测，执行结果见对应的 CI 记录。

## npx 安装冒烟

使用 Node.js 22.20.0 或更高版本、Git 和可访问 npm registry 的环境运行。

```bash
REQUIRE_NPX_INSTALL=1 python3 -B -m unittest discover -s tests -p test_standalone_skills.py
```

测试使用临时 HOME、项目、Git 源和 npm 缓存。固定 CLI 从本地工作树单装审查 Skill，再验证配置资源和只读脚本。Git 源测试核对同名手工副本、选择性更新、锁记录和分发过滤。对公开远程来源及实际客户端发现的检查见下表。

## 单元测试

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests
```

维护工具测试覆盖记录字节与权限保留、归档恢复、经验排序、归档回退与截断提示，以及按 ID 完成 todo、更新结果和状态、在同一把锁内检查归档阈值。命令示例在可用的 bash/zsh 中执行含空格路径的操作。质量契约测试检查历史静态线索，真实 Agent 的表现由单独的行为评测验证。

记忆流程另验证摘要数量和序列化字符预算、单条/归档/旧记录读取、todo 筛选、显式会话 stamp 与查询零写入；观察覆盖独立任务计数、并发、未验证跳过、损坏状态保留；经验覆盖明确要求直记、二次准入、原 ID 更新、关联失败重试及交错任务复用幂等。预算由实际工具输出长度检查，不把它换算成模型 token 或节省比例。

召回与失效测试覆盖同义概念去重、项目别名变化、弱匹配归档补查、失效记录排除及显式审计、可恢复状态和有效替代 ID；归档经验计数和状态变化与同日维护追加不能互相覆盖。`memory-v1` 另以真实 CLI 轨迹检查 Agent 是否实际采用查询路径，结果见 [1.7.9 记忆试验](../evals/reports/1.7.9-memory-pilot.md)，不能由这些单元测试推定自然触发通过。

观察查询测试覆盖有界候选、零写入、缺失/损坏状态、独立进程复用 key 及不同原因不自动合并；短查询参考在含空格路径的临时项目实际执行。`memory-v2` 的 R03 使用两个新 CLI 会话核对持久观察复用，分别保存首次与第二次记录，不以单个会话中的复述代替跨会话验证。验收优先检查正确性、记忆动作和只读边界，token 仅作效率观察，必要正文与证据可扩大读取预算。

三次只读配对和跨会话试验的实际结果见 [1.7.10 验收报告](../evals/reports/1.7.10-memory-workflow.md)。

## `.aitasks` CLI smoke test

在临时项目中运行，不要对真实项目直接使用 `cleanup --apply`：

```bash
python3 skills/aitasks-maintenance/scripts/maintain_aitasks.py --project-root /tmp/example-project status
python3 skills/aitasks-maintenance/scripts/maintain_aitasks.py --project-root /tmp/example-project find-lessons --query "关键词"
python3 skills/aitasks-maintenance/scripts/maintain_aitasks.py --project-root /tmp/example-project cleanup
```

确认 `cleanup` 默认只预览。需要验证写入时，在临时 fixture 中使用 `--force --apply`，检查活动记录被移入 `archive/`，且重复执行不会重复追加。

## Harness 人工验证

安装到目标 Harness 后，重启会话并确认：

1. Skill 可被列出或显式调用。
2. `ai-engineering-collaboration` 能发现同一安装范围内的专项 Skill。
3. `agents/openai.yaml` 只影响 Codex UI，不影响其他 Harness 读取标准 `SKILL.md`。

未在具体 Harness 中实际执行时，应报告“未验证”，不要将目录或静态检查写成运行时验证。

## 兼容与生效矩阵

| 层级 | 当前检查入口/证据 | 不能据此推断 |
| --- | --- | --- |
| 标准格式与单包资源 | `validate_repository.py`，本地资源不得越出 Skill 目录 | 自然触发准确率 |
| 项目安装与 Codex 发现 | CI 覆盖本地工作树安装与临时 Git 源更新。核对公开远程来源时，在隔离项目按安装说明执行 `add`、`npx skills@1.9.0 list --json`，再用 `codex debug prompt-input` 检查模型可见路径 | Skill 在实际任务中被选中或正确执行 |
| Python 与操作系统 | CI 的显式版本矩阵；本地实测另记版本 | 尚未执行的远程结果；Windows 全部路径已通过 |
| Codex 显式调用与自然选择 | 真实 CLI 场景、原始轨迹与逐维复核 | 其他模型和 Harness 有相同行为 |
| Claude Code / Gemini / OpenCode / Cursor / ZCode | CLI 的项目安装目录见[安装说明](installation.md#客户端与项目规则)，实际加载和运行效果按客户端验收 | Codex 发现结果可外推到其他客户端 |
| 前端视觉与交互 | 实际页面、视口、截图及操作记录 | 构建成功或源码包含内容即体验通过 |

`compatibility: universal` 指文本工作流设计，不是以上所有组合的通过声明。只安装入口或专项时，检查其资源自足及可选维护能力缺失时的回退；这些实际选择须单独观察。

## 行为评测

根据本次改动选择对应任务。例如调整防御代码规则时，同一轮验证应覆盖「已在入口验证的对象」和「需要重新核对的外部结果」。具体输入、预期行为和证据要求见[场景清单](../evals/scenarios.md)。

用相同请求对照旧版与候选版，保留每次运行的输入、命令和结果。套件选择、运行命令、历史报告和独立复核格式见[评测指南](../evals/README.md)。
