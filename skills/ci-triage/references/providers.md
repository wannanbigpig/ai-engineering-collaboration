# CI provider 操作参考

provider 特定的日志获取、重跑与操作方式在此维护；通用定位流程见本 Skill 的 `SKILL.md`。仅保留与归因有关且可获得的 provider、runner 与配置信息。重跑命令供已授权的验证使用；先核对 job 是否包含部署或其他外部写入，不因参考表列出命令而执行。

| provider | 获取完整失败日志 | 重跑 |
|---|---|---|
| GitHub Actions | job 完整日志（网页）或 `gh run view <run-id> --log-failed` | `gh run rerun <run-id>` |
| GitLab CI | job 完整日志（网页或 pipeline API） | 网页重试 job |
| Jenkins | Console Output 完整日志 | 网页重跑 build |

> `gh` CLI 仅在环境可用时使用；能力不可用时采用网页或 API 等价操作。
