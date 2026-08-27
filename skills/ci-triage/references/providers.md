# CI provider 操作参考

provider 特定的日志获取、重跑与操作方式在此维护；通用定位流程见本 Skill 的 `SKILL.md`。记录失败时同时记录 provider 版本、runner 镜像与相关配置，便于区分环境失败与代码失败。

| provider | 获取完整失败日志 | 重跑 |
|---|---|---|
| GitHub Actions | job 完整日志（网页）或 `gh run view <run-id> --log-failed` | `gh run rerun <run-id>` |
| GitLab CI | job 完整日志（网页或 pipeline API） | 网页重试 job |
| Jenkins | Console Output 完整日志 | 网页重跑 build |

> `gh` CLI 仅在环境可用时使用；能力不可用时采用网页或 API 等价操作。
