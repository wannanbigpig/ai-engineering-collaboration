# 项目记忆只读查询

只查询时读取本参考即可，无需加载维护 Skill 正文或归档流程。`AITASKS_TOOL` 指向本参考所属 Skill 的[只读查询脚本](../scripts/query_aitasks.py)，`AITASKS_PROJECT` 指向当前项目根目录；按实际安装位置解析，不写死 `.agents/` 或用户目录。脚本需 Python 3.10+，只提供只读查询命令，不写入记录或维护状态。

```bash
python3 -B "$AITASKS_TOOL" --project-root "$AITASKS_PROJECT" context --query "模块 符号 错误码"
python3 -B "$AITASKS_TOOL" --project-root "$AITASKS_PROJECT" get-record --kind lesson --id "命中ID"
```

- 任务开始、范围变化或新根因确认时查询。先取摘要，按 ID 读相关正文并核对当前契约；不把短预览当作完整做法。同会话已有未变内容可复用，新会话重新查询。
- 默认各最多三条经验和活动 todo、总计 2000 字符；正文默认 2400 字符。`truncated=true` 或证据不足时调整关键词、限额或 `--max-chars` 继续读取必要内容。预算是默认值，正确性与完整证据优先，不要求总 token 必须下降。
- 默认过滤 `retired` / `superseded`；归档仍可能有效。按 ID 审计旧条目时检查 `status` 和 `superseded_by`，跟随替代记录并核对适用条件。
- 查询不写文件、观察、计数或归档。只读任务不调用记录和维护命令；`python3 -B` 避免查询时生成字节码。

**无 Python 3.10+ 的降级。** 命令找不到或版本不够时，按以下两步查询，整个任务最多取三条命中标题。标题查询须先静默检查 Markdown 围栏，只有检查返回 1 才继续。发现围栏或读取失败时跳过该文件的标题和状态，标为未验证。关键词留在标题锚定式内。

```bash
if rg --no-config -q -- '^[[:blank:]]*(`{3,}|~{3,})' .aitasks/lessons.md; then
  printf '%s\n' '记录文件含围栏，标题和状态未验证。' >&2
elif [ "$?" -eq 1 ]; then
  rg --no-config -ni -m 3 -- '^##[[:blank:]]+.*(关键词一|关键词二)' .aitasks/lessons.md
fi
```

第一步有标题命中时，才逐条提取状态。将两个 `6` 换为标题行号减一，仅输出紧邻同类注释里的 `status`。

```bash
sed -nE -e '6s/^[ ]{0,3}<!-- aitasks:lesson( [^[:space:]<>]+)* status=(active|retired|superseded)( [^[:space:]<>]+)* -->[[:space:]]*$/status=\2/p' -e '6q' .aitasks/lessons.md
```

查 todo 时使用 `.aitasks/todo.md`、`aitasks:todo` 和状态 `active|completed|cancelled`。缺少对应状态或归属不明时标为未验证。两步结束即停止读记录文件。禁止宽泛关键词搜索、上下文行、区间读取或编写临时解析器。经验正文及适用性保留未验证，依据当前代码与契约取证。若无法隔离标题和状态输出，记为未验证，跳过经验查询。

根因已确认、准备维护经验时，再读维护 Skill 的观察规则；查询本身不证明一次实际复用或第二次问题出现。
