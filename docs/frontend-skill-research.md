# 前端 Skill 的开源参考与取舍

本次针对“只讲原则，落地效果差”调整 `frontend-ui-ux`。2026-11-06 核对了以下一手源码；star 是当时的仓库关注度，不是其中某个 Skill 的效果评分。参考用于提炼执行机制，未安装第三方脚本，也未复制其规则正文或整套数据。

| 来源 | 仓库 star | 核对版本与许可 | 采用的机制 |
| --- | ---: | --- | --- |
| [Anthropic skills](https://github.com/anthropics/skills) | 187,879 | [frontend-design](https://github.com/anthropics/skills/blob/ca45fc496a3436251f191354091d557da31c15b5/skills/frontend-design/SKILL.md)，[Apache-2.0](https://github.com/anthropics/skills/blob/ca45fc496a3436251f191354091d557da31c15b5/skills/frontend-design/LICENSE.txt) | 编码前落实具体颜色、字体与布局，对照 brief 后编码，环境支持时截图自评。 |
| [UI/UX Pro Max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | 145,853 | [Skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/blob/b7d5353e0130feb8c5574ef1251f8a1db1873ccb/.claude/skills/ui-ux-pro-max/SKILL.md)、[实现](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/tree/b7d5353e0130feb8c5574ef1251f8a1db1873ccb/src/ui-ux-pro-max/scripts)，[MIT](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/blob/b7d5353e0130feb8c5574ef1251f8a1db1873ccb/LICENSE) | 将产品目标转换成版式、颜色角色、字体、间距与控件状态等可实现决策；按具体问题补充知识。 |
| [Impeccable](https://github.com/pbakaus/impeccable) | 104,193 | [Skill](https://github.com/pbakaus/impeccable/blob/c3bb418ee38ee49a6b999b7752c1368f3123a2bd/skill/SKILL.src.md)，[Apache-2.0](https://github.com/pbakaus/impeccable/blob/c3bb418ee38ee49a6b999b7752c1368f3123a2bd/LICENSE) | 按操作、阅读等任务安排构图和密度；观察真实渲染后，先修结构与层级，再修细节。 |
| [Vercel agent-skills](https://github.com/vercel-labs/agent-skills) | 33,614 | [界面审查入口](https://github.com/vercel-labs/agent-skills/blob/1a2c79d4e6c4a2283dc2c614b6538cbe1ed5ca62/skills/web-design-guidelines/SKILL.md)；实际规则源为 [web-interface-guidelines](https://github.com/vercel-labs/web-interface-guidelines/blob/434b7f91364665f2f733b310ec54809bf8f37937/command.md)，后者为 [MIT](https://github.com/vercel-labs/web-interface-guidelines/blob/434b7f91364665f2f733b310ec54809bf8f37937/LICENSE) | 将检查落到可见标签、错误恢复、异步反馈、焦点及遮挡等具体行为。 |

`agent-skills` 的该版本仓库树没有仓库级 LICENSE；其 React Skill 自声明 MIT，不据此推定所有文件的许可。这里只比较机制并提供链接。其 React 性能规则仅适用于对应栈和实际性能问题，不作为所有界面的默认设计要求。

## 本项目如何落地

- 主 Skill 要求先确定页面骨架、具体视觉值和交互规格，再实现可运行的主要路径。已有设计系统直接复用，不为局部优化重建品牌。
- 按需参考补充“规格如何变成结构、样式与状态”的例子；示例值只解释选择，不要求每个项目采用同一字体、配色、布局或组件库。
- 实施后实际渲染和操作，按内容与操作阻塞、布局层级、视觉细节的顺序修正。构建、源码关键词和直接 API 请求各有用途，均不能单独证明页面可用或视觉质量。
- 只读评估和仅方案请求保留原边界；没有真实浏览器证据时明确限制，不把环境假设写成已验证事实。

没有引入第三方搜索引擎、整库 CSV、固定风格禁令、固定提案数量或截图轮数。它们是否值得采用，需要实际任务证据，不能由 star 数推导。

## 验证范围

结构与资源校验只证明包可分发。页面行为需要相同原始任务和运行条件下的旧版/候选产出，以及真实浏览器的独立检查；显式加载 Skill 的比较不证明自然触发准确性，单次样本也不证明普遍提升。实际运行、失败与主机检查见[落地评测](../evals/reports/1.7.15-frontend-implementation.md)，未完成的检查不得由本研究代替。
