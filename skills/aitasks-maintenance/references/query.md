# 项目记忆只读查询

只查询时读取本参考即可，无需加载维护 Skill 正文或归档流程。`AITASKS_TOOL` 指向本参考所属 Skill 的 `scripts/maintain_aitasks.py`，`AITASKS_PROJECT` 指向当前项目根目录；按实际安装位置解析，不写死 `.agents/` 或用户目录。

```bash
python3 -B "$AITASKS_TOOL" --project-root "$AITASKS_PROJECT" context --query "模块 符号 错误码"
python3 -B "$AITASKS_TOOL" --project-root "$AITASKS_PROJECT" get-record --kind lesson --id "命中ID"
```

- 任务开始、范围变化或新根因确认时查询。先取摘要，按 ID 读相关正文并核对当前契约；不把短预览当作完整做法。同会话已有未变内容可复用，新会话重新查询。
- 默认各最多三条经验和活动 todo、总计 2000 字符；正文默认 2400 字符。`truncated=true` 或证据不足时调整关键词、限额或 `--max-chars` 继续读取必要内容。预算是默认值，正确性与完整证据优先，不要求总 token 必须下降。
- 默认过滤 `retired` / `superseded`；归档仍可能有效。按 ID 审计旧条目时检查 `status` 和 `superseded_by`，跟随替代记录并核对适用条件。
- 查询不写文件、观察、计数或归档。只读任务不调用记录和维护命令；`python3 -B` 避免查询时生成字节码。
- 工具未安装、Python 不可用或子命令不支持时，按模块关键词只读取少量命中记录，包含其元数据、标题和所属正文，到下一同级标题或记录元数据前停止。默认排除失效条目；旧记录缺少状态视为有效线索，缺少计数标未记录。不整篇加载经验、todo 或观察状态。

根因已确认、准备维护经验时，再读维护 Skill 的观察规则；查询本身不证明一次实际复用或第二次问题出现。
