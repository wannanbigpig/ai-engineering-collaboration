# 验证说明

本仓库可自动验证 Skill 结构、版本一致性和 Markdown 空白；不同 Agent Harness 的发现与自动触发行为需要在目标环境中人工确认。

## 本地与 CI 校验

```bash
release=$(tr -d '\r\n' < VERSION)
test -n "$release"

for skill in skills/*; do
  test "$(sed -n 's/^  version: //p' "$skill/SKILL.md")" = "$release"
  uvx --from 'skills-ref==0.1.1' agentskills validate "$skill"
done

git diff --check
```

GitHub Actions 运行同一版本一致性检查和 `agentskills validate`。这只能验证文件结构，不代表某个 Harness 已实际发现、加载或执行了 Skill。

## 单元测试

```bash
python3 -m unittest discover -s tests -v
```

测试在临时 Git 项目中验证首次安装、重复运行、dry-run、冲突拒绝、`.aitasks` 跟踪选项、Custom Instructions 输出，以及 Claude Code、Gemini、ZCode 兼容链接的创建与幂等、相同副本保留、冲突拒绝和失败指引；经验维护测试覆盖无元数据/混合经验检索、JSON正文与元数据归属/计数状态/源行号、只读检索与维护写入隔离，以及无到期记录时仅更新检查状态；命令示例测试在可用的 bash/zsh 中执行含空格路径的只读命令。质量契约测试仅检查历史规则的静态线索，不能证明指令之间没有冲突或真实行为正确。GitHub Actions 运行完整测试发现命令。

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

## 可维护性行为评测

[可维护性行为评测场景](../evals/maintainability-scenarios.md)覆盖复用已有实现、影响分析、错误处理、量化证据、避免过度拆分、沿用后端主流风格、无设计稿时沿用现有 UI 和无关修改保护。它们用于验证 Skill 对 Agent 实际行为的影响，不由静态单元测试替代。

在每个目标 Harness 中分别执行：

1. 安装当前版本的全部 Skill，并为每个场景建立新的临时 Git fixture。
2. 使用场景中的用户请求启动新会话，不额外泄露评分项。
3. 保存提示、工具调用、最终 diff、验证输出和最终回复，逐项核对“必须观察到”与“不得出现”。
4. 记录 Harness、模型、Skill 版本、fixture commit 和日期；存在禁止项或缺少工具证据时判定失败。

通用场景可在不同 Harness 中手工执行；[成对行为运行器](../evals/behavior-evaluation.md)提供 Codex CLI 适配。某个适配器的运行结果不能代表其他 Harness，实际模型行为也不能由场景定义或质量契约推断。

## 工作流边界评测

[工作流边界场景](../evals/workflow-boundaries.md)覆盖只读不写记录、授权继承、预期失败、证据复用、简单跨文件修改、经验查询和合并独立问题。按文件中的 fixture 与用户请求，在每个目标 Harness 的新会话中分别执行并保存工具轨迹；不能将静态关键词测试、指令复审或文件存在记为行为通过。

只读评测需要比对完整工作区文件快照，包括 Git 忽略文件；重复读取、重复验证和额外确认按场景中的定义评分。通过与未验证项应分别报告，并明确运行环境和 Skill 版本。

## 成对行为验收

对照基线应为修改前的真实工作区快照，包含未跟踪源文件；同时保存文件清单和内容哈希，不能用较早提交替代已完成的未提交成果。评测输出、凭据和本机配置不打包进源基线。

使用相同场景、模型设置、项目规则和运行环境，对受影响场景的两个版本各执行三次独立场景组；仅完整 legacy 回归才是 12 组共 72 个样本，跨轮复用组还包含同会话后续轮次。先完成连接和加载预检，再进行全量验收；失败样本保留，不覆盖重试，也不事后修改评分标准美化结果。

判定分为：

- **正确性**：实际功能断言、契约和必要验证是否满足；仅 CLI 退出成功不算通过。
- **边界**：只读写入、越权改动、遗漏必要决策和虚假完成必须为零；缺证据记为未验证。
- **流程成本**：结合工具轨迹审查无关读取、额外确认、等价重跑与不必要加载，关键词只能辅助定位。
- **耗时与 tokens**：保留实测数据，仅比较两侧都正确完成的样本；不预设节省百分比。

机器检查、人工语义复核及加载隔离状态分别记录。其他 Skill 未读到不等于严格隔离已证实；明确调用成功也不证明自动触发准确。对于没有 CodeGraph 或浏览器的环境，只能验证对应回退或静态检查，图谱选择和视觉效果继续标记未验证。评测工具仅供维护者主动运行，不加入日常工程任务的强制流程。


后续窄范围优化使用 `review-v2` 的契约、测试入口与 UI 正反对照；`natural-v2` 在不指定入口的条件下单独观察选择行为，先做有限抽样。五维评分、逐命令证据索引和判定边界见[新版评测说明](../evals/behavior-evaluation.md#161-新版对照与自然触发)。不同 suite 必须使用独立输出目录，运行器在启动前拒绝混用；旧结果缺少 suite 字段时按 legacy 处理。原始输出不足以证明的项目仍为未验证，不能据此断言模型未看到工具结果；诊断补充证据须独立注明来源，不改写原CLI记录。归档工作区不可原地重放命令。详见[查询完整性与输出取证](../evals/behavior-evaluation.md#163-查询完整性与输出取证)。
