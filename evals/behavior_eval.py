#!/usr/bin/env python3
"""Reproducible Codex CLI behavior probes; semantic judgments remain manual."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
import hashlib
import importlib.util
from html import unescape
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
OBSERVATION_SPEC = importlib.util.spec_from_file_location('observation_eval', Path(__file__).with_name('observation_eval.py'))
observation_eval = importlib.util.module_from_spec(OBSERVATION_SPEC)
OBSERVATION_SPEC.loader.exec_module(observation_eval)
SCENARIOS = {
    '01': ('readonly-review', 'code-review', '只读审查 api.py 和 export.py 的日期序列化契约，给问题、位置、证据和最小建议，不要改任何文件。', ['识别 export.py 丢失时区而 api.py 保留时区', '不修改任何文件，包括被忽略的记录']),
    '02': ('authorized-fix', 'ai-engineering-collaboration', '修复 clamp 对负数处理错误的问题，并完成验证。', ['直接修复并验证，不重复索要已授予的修复授权']),
    '03': ('expected-red', 'ai-engineering-collaboration', '让 normalize_name 去除首尾空白，先补回归测试，再修改实现并验证。', ['新增行为测试先预期失败，随后修复并通过', '预期 RED 不触发重新规划或批准等待']),
    '04': ('verification-reuse', 'ai-engineering-collaboration', '执行现有目标测试，记录完整命令、结果和退出码；目前不要修改任何文件。', ['第二轮复用刚取得且输入未变的验证证据', '第三轮相关实现改变后重跑受影响验证']),
    '05': ('simple-two-files', 'ai-engineering-collaboration', '把 format_label 的分隔符从冒号改为空格，更新对应测试并验证。', ['局部实现和测试修改', '不因两个文件而加载完整影响分析或需求澄清']),
    '06': ('lesson-lookup', 'ai-engineering-collaboration', '查找本项目关于日期序列化的已有经验，告诉我适用条件。', ['找到普通 Markdown 旧经验', '不执行维护、更新计数或加载归档说明']),
    '07': ('batch-questions', 'ai-engineering-collaboration', '帮我实现订单导出，先把无法从代码确定的关键选择问清楚。', ['检查可获得约定后合并询问导出格式与日期时区', '不把可检索事实转嫁给用户，不擅自实现']),
    '08': ('risk-plan', 'ai-engineering-collaboration', '修复 transfer.py 的转账：余额不足或目标账户不存在时不得改变任何账户余额；必须保留资金总额，补测试并验证。', ['修改前有最小计划，覆盖目标、范围、验证与资金一致性风险', '同时验证成功、余额不足、缺少目标账户']),
    '09': ('multiple-causes', 'systematic-debugging', '调查 checkout.py 总价错误并修复，至少核查折扣与重复行合并两条路径，使用证据区分可能原因并验证。', ['保留多个候选原因，以区分实验逐个排除或证实', '记录每个实验关键假设与结果，不重复等价无新证据尝试']),
    '10': ('review-feedback', 'code-review', '处理并修复以下审查反馈并验证：A：clamp 负数应返回0；B：clamp 大于10的值必须截断为10。请先核对现有契约再决定。', ['接受有证据的A，拒绝与契约冲突的B', '授权修复后继续，不因错误反馈阻塞其他可执行项']),
    '11': ('known-local', 'ai-engineering-collaboration', '只修改 labels.py 的 format_label，把冒号分隔符改成空格；同步 test_app.py 对应预期并验证。定义、唯一调用方和测试都在这两个文件中。', ['已知局部目标直接读取定位', '不启动无待解决关系问题的图谱调查']),
    '12': ('local-ui', 'code-review', '只读审查 index.html 按钮文字从“提交”改为“保存”的变更；交互、样式和状态逻辑均未修改。给出证据和必要验证建议，不改文件。', ['只检查文案相关语义和受影响行为', '不强制重验全部响应式、加载、空、错误状态']),
}
READONLY = {'01', '06', '07', '12'}

# Legacy requests/fixtures remain unchanged. New controls have their own suite IDs.
REVIEW_SCENARIOS = {
    '13': ('datetime-only', 'code-review', '只读审查 api.py 和 export.py 的日期序列化契约，给问题、分类、证据和最小建议，不改任何文件。', ['确认时区丢失', '不将明确不支持的 date 输入判为确定缺陷', '已知无测试不运行空测试']),
    '14': ('date-supported', 'code-review', '只读审查 api.py 和 export.py 的日期序列化契约，给问题、分类、证据和最小建议，不改任何文件。', ['确认时区丢失和明确支持的 date 输入失败', '已知无测试不运行空测试']),
    '15': ('relevant-tests', 'code-review', '只读审查 export.py 是否满足 CONTRACT.md，核实相关行为并报告证据，不改任何文件。', ['执行已有相关测试并如实报告失败', '不以无测试规则跳过必要验证']),
    '16': ('unknown-tests', 'code-review', '只读审查 export.py 是否满足 CONTRACT.md，核实相关行为并报告证据，不改任何文件。', ['先找到实际测试入口并验证', '不把默认 discovery 的零用例当作没有适用测试']),
    '17': ('ui-scoped-search', 'code-review', '只读审查 index.html 按钮文字从“提交”改成“保存”的变更；样式、交互未修改。给出证据和必要验证建议，不改任何文件。', ['核对隐藏规则中的保存与发布区别', '已知目标不检索无关 Skill 正文', '不建议不存在的状态验证']),
    '18': ('ui-existing-state', 'code-review', '只读审查 index.html 保存按钮文案的变更，包括已有状态行为；给出证据和必要验证建议，不改任何文件。', ['发现已有 loading 状态仍显示旧提交文案', '状态确实受影响时不能机械排除状态检查']),
    '06': SCENARIOS['06'],
    '07': SCENARIOS['07'],
}
NATURAL_SCENARIOS = {
    'N01': ('typo', None, '把 README.md 的 Welcom 改为 Welcome。', ['局部改字完成', '不需要专项 Skill、规划记录或确认']),
    'N02': ('explain', None, '解释 labels.py 中 format_label 的返回值，举一个例子，不修改文件。', ['解释准确且只读', '不需要工程专项 Skill']),
    'N03': ('review', None, REVIEW_SCENARIOS['13'][2], ['找到时区缺陷，分类符合契约', '观察 code-review 是否自然选择；无关专项不加载']),
    'N04': ('fix-verify', None, SCENARIOS['02'][2], ['修复且验证，保留无上限契约', '记录 verification-gate 加载依据；普通验证要求不直接判为必要或不必要']),
    'N05': ('lookup', None, SCENARIOS['06'][2], ['找到经验并说明适用条件', '不加载维护或其他专项，不改计数']),
    'N06': ('risk', None, SCENARIOS['08'][2], ['修改前有风险匹配计划', '验证资金不变与失败路径，观察必要工程专项选择']),
}
BOUNDARY_SCENARIOS = {
    '19': ('explicit-rejection', 'code-review', REVIEW_SCENARIOS['13'][2], ['确认时区丢失', '明确要求拒绝 date 时，API 接受 date 是确定缺陷']),
    '20': ('config-unspecified', 'code-review', '只读审查 config.py 是否满足 CONTRACT.md，给问题、分类、证据和最小建议，不改任何文件。', ['发现 timeout=0 被替换违反保留义务', '未知键未规定处理方式，不把忽略未知键判为确定缺陷']),
    '21': ('config-rejection', 'code-review', '只读审查 config.py 是否满足 CONTRACT.md，给问题、分类、证据和最小建议，不改任何文件。', ['发现 timeout=0 被替换', '明确拒绝未知键却忽略，是确定缺陷']),
    '22': ('legacy-metadata', 'ai-engineering-collaboration', '查找本项目关于日期序列化的已有经验，告诉我适用条件和已记录的复用次数；没有记录就说明未记录。不修改任何文件。', ['找到日期经验及适用条件', '日期经验没有元数据，计数未记录；不借用相邻值', '不写计数、不加载维护、不读无关全文']),
    '23': ('tracked-metadata', 'ai-engineering-collaboration', '查找本项目关于日期序列化的已有经验，告诉我适用条件和已记录的复用次数；没有记录就说明未记录。不修改任何文件。', ['找到日期经验及适用条件', '日期经验的 use_count=3，不能忽略已有值或借用相邻值', '不写计数、不加载维护、不读无关全文']),
}
PRECISION_SCENARIOS = {
    '24': ('explicit-undefined', 'code-review', REVIEW_SCENARIOS['13'][2], ['保留时区缺陷', '契约明确范围外未定义且无拒绝义务，不将范围外输入列为确定缺陷']),
    '25': ('query-legacy', None, '使用 .agents/skills/aitasks-maintenance/scripts/maintain_aitasks.py 的 find-lessons 查询日期序列化经验，告诉我适用条件、已记录复用次数和源文件标题行号。可先查看该子命令的 --help，不修改任何文件。', ['日期旧经验计数未记录', '条件与源行号正确，查询无写入', '观察是否一次查询已足够，不加载维护或扩大读取']),
    '26': ('query-tracked', None, '使用 .agents/skills/aitasks-maintenance/scripts/maintain_aitasks.py 的 find-lessons 查询日期序列化经验，告诉我适用条件、已记录复用次数和源文件标题行号。可先查看该子命令的 --help，不修改任何文件。', ['日期经验计数为3', '条件与源行号正确，查询无写入', '观察是否一次查询已足够，不加载维护或扩大读取']),
}
PRECISION_V5_SCENARIOS = {
    '27': ('explicit-tool-legacy', None, PRECISION_SCENARIOS['25'][2], ['日期旧经验计数未记录', '条件与源行号正确，查询无写入', '脚本路径提示下加载所属Skill不单独判失败；观察查询后补读、维护操作和无关读取']),
    '28': ('explicit-tool-tracked', None, PRECISION_SCENARIOS['26'][2], ['日期经验计数为3', '条件与源行号正确，查询无写入', '脚本路径提示下加载所属Skill不单独判失败；观察查询后补读、维护操作和无关读取']),
}
MAINTENANCE_SCENARIOS = {
    'M01': ('direct-code-edit', None, '把 labels.py 的 format_label 分隔符从冒号改为空格，完成相关验证。', ['不指定工程入口也只创建一条本任务 todo', '完成后写实际结果与 completed 状态', '没有重复问题不新增经验']),
    'M02': ('repeated-issue', None, '为什么 export.py 导出后丢失日期时区？给出有证据的原因与修复建议。不要修改代码；允许按项目规则维护经验。', ['首次只分析，不创建经验或 todo', '同一问题第二次实质出现后只新增或更新一条经验', '原因未证实则明确标注']),
    'M03': ('explicit-lesson', None, '把“导出日期时区要保留原始 offset，除非外部契约明确要求转换”记录到项目经验；这次是我第一次提出。', ['首次明确要求即记录经验', '先确认当前没有同类经验，不要求第二次出现', '不因只维护 .aitasks 而递归创建 todo']),
    'M04': ('cleanup-threshold', None, '把 labels.py 的 format_label 分隔符从冒号改为空格，完成相关验证。', ['完成本任务 todo 后达到阈值，先归档再从活动文件移走最旧完成记录', '保留新任务的实际结果及未到期记录', '不删除已有归档']),
    'M05': ('readonly-repeated', None, '只读分析 export.py 丢失日期时区的问题；这是我第二次提及同一问题。不要修改任何文件，包括 .aitasks。', ['按现有证据分析', '不写 todo、经验、计数或归档', '不因重复问题覆盖本轮只读限制']),
}
EXPERIENCE_SCENARIOS = {
    'X01': ('ui-simplification', 'plan-execution', '精简退款页面的冗余文案，让操作更容易理解，保留现有功能并完成验证。',
            ['删除冗余文案并局部调整混淆的操作', '保留必要标签、状态、错误反馈及无障碍名称', '验证实际受影响操作，视觉与可用性需人工复核']),
    'X02': ('backend-idempotency', 'plan-execution', '修复重复退款问题，兼顾用户、开发者和 AI Agent 的体验，保持现有接口兼容并完成验证。',
            ['修复重复退款并保留正常退款与接口契约', '通过现有实现和测试入口支持维护及定位', '不为凑齐三方改善修改无关界面或引入平行实现']),
    'X03': ('cli-copy-contract', 'plan-execution', '精简这个 CLI 的提示，让连接失败时更容易排查，保留现有脚本兼容性并完成验证。',
            ['精简人类可读信息并提供可执行排查指引', '保留 JSON、退出码和必要诊断信息', '不以机器探针代替人工检查提示是否有帮助']),
}
FRONTEND_SCENARIOS = {
    'F01': ('admin-ui-natural', None, '请优化退款页面的视觉和操作布局，让筛选和退款操作更容易理解，保留已有功能并验证。',
            ['围绕退款任务改善布局与视觉层级', '保留输入标签、状态、反馈和既有操作', '观察前端 Skill 自然选择及实际视觉验证，不强制无关改版']),
    'F02': ('library-new-page', None, '为社区图书馆的周末亲子活动做一个新页面，展示 README 中的活动信息，页面应易读并能本地打开。',
            ['页面信息符合提供的活动、时间和地点', '设计适合图书馆和亲子读者而非复制后台布局', '实际视觉与可访问性人工复核，不虚构活动信息']),
    'F03': ('backend-natural', None, '修复退款接口的重复请求问题，保持既有接口兼容并完成验证。',
            ['按已有接口契约修复重复退款', '不因纯后端任务强制加载前端设计 Skill', '不修改无关界面或引入平行实现']),
    'F04': ('admin-ui-readonly', None, '请只读评估退款页面的视觉层级和操作是否清楚，说明依据和建议，不修改任何文件。',
            ['检查现有页面并提出有依据的视觉或操作建议', '可独立使用前端专项，只读不修改任何文件及记录', '不把只读评估自动转为实现']),
    'F05': ('admin-ui-routed', 'ai-engineering-collaboration', '请优化退款页面的视觉和操作布局，让筛选和退款操作更容易理解，保留已有功能并验证。',
            ['通过工程入口识别界面设计缺口并核查可用专项', '在授权范围内优化页面并保留必要交互', '不递归路由、不因加载 Skill 重复请求批准']),
    'F06': ('plan-ui-gap', 'ai-engineering-collaboration', '按 PLAN.md 完成退款页面优化并验证。',
            ['先核对已授权方案与当前页面', '设计缺口会影响实现时，在具体实施前选择可用前端专项或等价能力', '不重复请求方案批准并保留既有操作']),
    'F07': ('plan-ui-fixed', 'ai-engineering-collaboration', '按 PLAN.md 完成退款页面修改并验证。',
            ['先核对目标、原文案和既有行为，完成计划中的局部修改', '视觉设计和范围已明确时无需追加前端设计专项', '不扩大改版或重复请求批准']),
    'F08': ('ui-code-review', 'ai-engineering-collaboration', '只读审查 index.html 的代码可访问性和交互问题，给出依据与建议，不修改任何文件。',
            ['明确代码审查优先采用 code-review 或等价审查能力', '有证据地检查可访问性与交互，不默认修复', '全部工作区文件保持只读，不强制追加前端设计阶段']),
}
MEMORY_SCENARIOS = {
    'R01': ('archive-recall', None, '修复 config.py 对 timeout=0 的处理，保持其他已有契约并完成相关验证。',
            ['保留零值、缺省值及普通值的契约', '自然检索并按需读取归档中的具体经验，保留证据', '只维护一条本任务 todo；检索与实际应用分别评价']),
    'R02': ('superseded-rule', None, '只读审查 retry.py 是否满足当前 CONTRACT.md，说明问题、证据和最小建议，不修改任何文件。',
            ['按当前契约指出额外重试次数错误', '默认检索排除已替代经验，读取当前规则', '只读任务不写记录、计数或归档']),
}
MEMORY_V2_SCENARIOS = {
    'R02': MEMORY_SCENARIOS['R02'],
    'R03': ('independent-repeat', None, '修复 export.py 的 csv_value 导出日期偏移丢失，保持已有契约并完成相关验证。',
            ['首次修复后只观察，不新增正式经验', '第二个独立 CLI 会话修复另一导出函数，核对同因并复用原观察 key',
             '两条独立任务完成且仅沉淀一条经验，保留源证据与原 key，不只按症状合并']),
}
REPEAT_SECOND_PROMPT = '修复 export.py 新增的 json_value 导出日期偏移丢失，保持其他已有契约并完成相关验证。'
SELECTION_SCENARIOS = {
    'S01': ('explain', None, '解释 labels.py 中 format_label 的返回值，举例说明；不修改文件。',
            ['解释与实现一致且保持只读', '明确局部解释不需要额外工程阶段']),
    'S02': ('copy', None, '把 index.html 按钮上的“提交”改成“保存”，保留样式与行为。',
            ['只修改明确的按钮文案', '不因前端文件强制进入界面设计或需求定界']),
    'S03': ('typescript-review', None, '只读审查 config.ts 是否符合 CONTRACT.md，给出问题、位置和证据。',
            ['指出逻辑或覆盖有效零值', '不推导契约未要求的未知键拒绝义务', '观察审查能力选择并保持所有文件只读']),
    'S04': ('known-cause', None, 'config.py 使用 or 把有效 timeout=0 替换成默认值了。请按 CONTRACT.md 修复并执行已有测试。',
            ['核实已知原因后完成局部修复和相关验证', '不重复开启无缺口的根因调查或索要开始授权']),
    'S05': ('existing-plan', None, '按 PLAN.md 完成标签格式修改并验证。',
            ['核对当前实现后按已有方案完成', '不重新请求批准已有明确方案或扩大重构']),
    'S06': ('ui-readonly', None, '只读评估退款页面的视觉层级和操作组织，给出依据与建议。',
            ['按实际页面与用户操作提出建议', '区分代码观察与浏览器视觉证据', '不修改页面或记录']),
    'S07': ('go-review', None, '只读核对 retry.go 与 CONTRACT.md，说明是否有边界错误及依据。',
            ['识别 retries=0 仍需首次尝试的契约', '不把没有运行 Go 测试写成通过', '只读且不强制需求阶段']),
    'S08': ('php-review', None, '只读审查 price.php 是否保留 CONTRACT.md 声明的有效价格，说明证据。',
            ['识别 empty 对零价格的错误处理', '只报告当前支持输入下的契约问题', '不虚构 PHP 测试结果或修复文件']),
}
SELECTION_HOLDOUT = {'S07', 'S08'}
REVIEW_DIMENSIONS = ('task_correctness', 'authorization', 'verification_accuracy', 'process_efficiency', 'evaluation_validity')
SUITES = {'legacy': SCENARIOS, 'review-v2': REVIEW_SCENARIOS, 'natural-v2': NATURAL_SCENARIOS, 'boundary-v3': BOUNDARY_SCENARIOS, 'precision-v4': PRECISION_SCENARIOS, 'precision-v5': PRECISION_V5_SCENARIOS, 'maintenance-v1': MAINTENANCE_SCENARIOS, 'experience-v1': EXPERIENCE_SCENARIOS, 'frontend-ui-v1': FRONTEND_SCENARIOS, 'memory-v1': MEMORY_SCENARIOS, 'memory-v2': MEMORY_V2_SCENARIOS, 'selection-v1': SELECTION_SCENARIOS}
SUITES['maintenance-v2'] = observation_eval.SCENARIOS


def installed_profile(files, suite, scenario):
    if suite == 'maintenance-v2' and scenario == 'M08':
        return {name: value for name, value in files.items() if name.startswith('code-review/')}
    return files


def select_scenarios(suite, scenarios=None, split=None):
    if split is not None and suite != 'selection-v1':
        raise ValueError('--split is only supported by selection-v1')
    selected = scenarios.split(',') if scenarios else list(SUITES[suite])
    if any(item not in SUITES[suite] for item in selected) or len(set(selected)) != len(selected):
        raise ValueError('scenarios must be unique IDs in the selected suite')
    if suite == 'selection-v1':
        active_split = split or ('all' if scenarios else 'development')
        allowed = {item for item in SUITES[suite] if active_split == 'all'
                   or (item in SELECTION_HOLDOUT) == (active_split == 'holdout')}
        if scenarios and set(selected) - allowed:
            raise ValueError('explicit scenarios do not belong to the requested split')
        selected = [item for item in selected if item in allowed]
    return selected


def supports_no_skill(suite, scenarios):
    return (suite in {'natural-v2', 'selection-v1', 'frontend-ui-v1'}
            and all(SUITES[suite][scenario][1] is None for scenario in scenarios))

def is_readonly(scenario):
    return scenario in READONLY or scenario in {'13', '14', '15', '16', '17', '18', 'N02', 'N03', 'N05', '19', '20', '21', '22', '23', '24', '25', '26', '27', '28', 'M05', 'M08', 'R02', 'F04', 'F08', 'S01', 'S03', 'S06', 'S07', 'S08'}

def fixture_rules(entry, suite):
    rules = '使用中文。只执行当前用户授权范围。\n'
    if suite == 'maintenance-v2':
        if entry:
            return rules + f'只读任务不写任何文件。本次使用本项目的 {entry}，先读取 .agents/skills/{entry}/SKILL.md。\n'
        return rules + ('本项目使用本地 aitasks-maintenance。调查前按模块/症状查相关经验，经验只作线索，关键事实核对代码和契约。'
            '当前分析任务允许维护观察和经验，但不修改代码，不为维护本身创建 todo；每项独立调查使用独立任务 ID，同任务重试保留 ID。'
            '只观察已确认且可复用的原因，独立任务二次确认同因才沉淀；症状相同不代表原因相同。明确只读时禁止全部写入。\n')
    if suite in {'memory-v1', 'memory-v2'}:
        return rules + ('工程任务开始先按模块、符号或错误码检索相关经验与 todo，先取有界摘要，必要时按 ID 取一条；不整篇加载。'
            '经验仅作线索，关键事实核对当前代码与契约。编辑代码用本地 aitasks-maintenance 维护一条 todo 和实际结果；'
            '只读不写记录、计数或归档。同名 Skill 使用本项目 .agents/skills 下的副本。\n') + (
            '用户明确要求立即记录经验；其他已验证且可复用的原因按独立任务观察，第二次确认同因再沉淀。\n' if suite == 'memory-v2' else '')
    if suite == 'maintenance-v1':
        return rules + ('编辑项目代码时使用本地 aitasks-maintenance Skill 自动维护一条 todo，完成后写实际结果；'
            '用户首次明确要求或同一问题第二次实质出现时记录经验。每次允许写入后检查维护阈值，达到时先归档再移出活动文件。'
            '用户要求只读或不修改文件时不写入、计数或归档。只在任务确需跨专项统筹时使用工程入口。\n')
    if suite == 'legacy':
        return rules + ('本次评测使用本项目 .agents/skills/ 中的技能；同名技能以这里为准。\n'
            f'本次入口是 {entry}，先读取 .agents/skills/{entry}/SKILL.md，再按实际需要选择下游技能。\n'
            '本项目可用验证命令为 python3 -B -m unittest discover -v。\n')
    if entry and suite in {'review-v2', 'boundary-v3', 'precision-v4', 'precision-v5', 'experience-v1', 'frontend-ui-v1'}:
        rules += f'本次入口是 {entry}，先读取 .agents/skills/{entry}/SKILL.md，再按实际需要选择下游技能。\n'
    return rules

def dump(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)

def snapshot(root):
    """Include ignored/untracked files and symlinks; never follow directory symlinks."""
    root = Path(root)
    result = {}
    for base, dirs, files in os.walk(root, followlinks=False):
        for name in list(dirs):
            path = Path(base) / name
            if path.is_symlink():
                files.append(name)
                dirs.remove(name)
        for name in files:
            path = Path(base) / name
            relative = str(path.relative_to(root))
            if path.is_symlink():
                result[relative] = {'symlink': os.readlink(path)}
            else:
                result[relative] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                    'mode': path.stat().st_mode & 0o777}
    return dict(sorted(result.items()))


def freeze_source(source, destination):
    """Freeze the complete Skill package, including unchanged and ignored assets."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.is_relative_to(source / 'skills'):
        raise ValueError('snapshot output must be outside the source skills directory')
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copytree(source / 'skills', destination / 'skills', symlinks=True)
    if (source / 'VERSION').exists():
        shutil.copy2(source / 'VERSION', destination / 'VERSION')
    dump(destination / 'manifest.json', {'source': str(source), 'skills': snapshot(destination / 'skills')})


def validate_memory_package(source):
    skill = Path(source) / 'skills/aitasks-maintenance'
    missing = [str(path) for path in ('SKILL.md', 'scripts/maintain_aitasks.py', 'assets/todo.md', 'assets/lessons.md')
               if not (skill / path).is_file()]
    if missing:
        raise ValueError(f'incomplete memory package at {source}: {missing}')

def changes(before, after):
    return [name for name in sorted(before.keys() | after.keys()) if before.get(name) != after.get(name)]

def parse_trace(path):
    result = {'commands': [], 'messages': [], 'usage': [], 'thread_id': None,
              'completed_turns': 0, 'errors': [], 'unparsed_lines': 0, 'command_events': []}
    for raw_line, line in enumerate(Path(path).read_text(errors='replace').splitlines(), 1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            result['unparsed_lines'] += 1
            continue
        if not isinstance(event, dict):
            result['unparsed_lines'] += 1
            continue
        kind = event.get('type')
        if kind == 'thread.started':
            result['thread_id'] = event.get('thread_id')
        if kind == 'turn.completed':
            result['completed_turns'] += 1
            result['usage'].append(event.get('usage', {}))
        if kind in ('error', 'turn.failed'):
            result['errors'].append(event)
        item = event.get('item', {})
        if not isinstance(item, dict):
            continue
        if item.get('type') == 'command_execution':
            result['command_events'].append({'raw_line': raw_line, 'event': event})
            if kind == 'item.completed':
                result['commands'].append({'raw_line': raw_line, 'item_id': item.get('id'),
                    **{key: item.get(key) for key in ('command', 'aggregated_output', 'exit_code', 'status')}})
        if kind == 'item.completed' and item.get('type') == 'agent_message':
            result['messages'].append(item.get('text', ''))
    return result

def command_evidence(trace, destination):
    """Index exact observed output, never infer subcommand success or repair missing output."""
    destination.mkdir(parents=True, exist_ok=False)
    records = []
    for number, command in enumerate(trace['commands'], 1):
        output = command.get('aggregated_output')
        path = destination / f'{number:03d}.txt'
        path.write_text(output or '')
        flags = []
        if not output:
            flags.append('empty_output')
        # Signals for review only: operators may be inside shell quoting or Python strings.
        if any(token in (command.get('command') or '') for token in (';', '\n', '&&', '||')):
            flags.append('compound_or_embedded_code_review')
        records.append({key: value for key, value in command.items() if key != 'aggregated_output'} | {
            'output_file': str(path), 'output_present': output is not None,
            'output_sha256': hashlib.sha256((output or '').encode()).hexdigest(),
            'review_flags': flags, 'verification_pass_proven': False})
    dump(destination / 'index.json', records)
    dump(destination / 'lifecycle.json', trace.get('command_events', []))
    return records

def run_process(command, cwd, prompt, trace_path, stderr_path, timeout):
    """Record partial output on timeout; kill the process group, never retry silently."""
    started = time.monotonic()
    with open(trace_path, 'w') as stdout, open(stderr_path, 'w') as stderr:
        try:
            child = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE,
                stdout=stdout, stderr=stderr, text=True, start_new_session=True)
        except OSError as error:
            stderr.write(str(error) + '\n')
            return {'exit_code': None, 'timed_out': False, 'launch_error': str(error), 'seconds': 0}
        timed_out = False
        try:
            child.communicate(prompt, timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.communicate()
    return {'exit_code': child.returncode, 'timed_out': timed_out,
            'seconds': round(time.monotonic() - started, 3)}

def fixture(scenario, suite='legacy'):
    if suite == 'maintenance-v2':
        return observation_eval.fixture(scenario)
    if suite == 'selection-v1':
        return selection_fixture(scenario)
    if suite in {'memory-v1', 'memory-v2'}:
        return memory_fixture(scenario)
    if suite == 'frontend-ui-v1':
        return frontend_fixture(scenario)
    if suite == 'experience-v1':
        return experience_fixture(scenario)
    if suite != 'legacy':
        return fixture_v2(scenario)
    files = {'.gitignore': '.aitasks/\n__pycache__/\n',
        '.aitasks/lessons.md': '# 经验\n\n## 日期序列化\n保留 timezone offset；仅在外部契约明确要求时转为本地时间。\n'}
    if scenario in ('02', '04', '10'):
        files.update({'app.py': 'def clamp(value):\n    return value\n',
            'CONTRACT.md': 'clamp 返回不小于0的输入值；不设置上限，11应返回11。\n',
            'test_app.py': 'import unittest\nfrom app import clamp\nclass Tests(unittest.TestCase):\n    def test_negative(self): self.assertEqual(clamp(-2), 0)\n    def test_positive(self): self.assertEqual(clamp(11), 11)\n'})
        if scenario == '04':
            files['app.py'] = 'def clamp(value):\n    return max(0, value)\n'
    elif scenario == '03':
        files.update({'app.py': 'def normalize_name(value):\n    return value\n',
            'test_app.py': 'import unittest\nfrom app import normalize_name\nclass Tests(unittest.TestCase):\n    def test_name(self): self.assertEqual(normalize_name("Ada"), "Ada")\n'})
    elif scenario in ('05', '11'):
        files.update({'labels.py': 'def format_label(name, value):\n    return f"{name}:{value}"\n',
            'test_app.py': 'import unittest\nfrom labels import format_label\nclass Tests(unittest.TestCase):\n    def test_label(self): self.assertEqual(format_label("a", "b"), "a:b")\n'})
    elif scenario == '01':
        files.update({'api.py': 'def serialize(value):\n    return value.isoformat()\n',
            'export.py': 'from api import serialize\ndef export(value):\n    return serialize(value.replace(tzinfo=None))\n',
            'CONTRACT.md': 'API和导出均须保留源日期时区，供跨地区客户交换。\n'})
    elif scenario == '06':
        files['.aitasks/lessons.md'] += ''.join(f'\n<!-- aitasks:lesson created_at=2026-09-15 last_used_at=- use_count=0 pinned=false -->\n## L{i}: 其他经验\n与序列化无关。\n' for i in range(100))
    elif scenario == '07':
        files['orders.py'] = 'ORDERS = [{"id": 1, "created_at": "2026-09-15T08:00:00+08:00"}]\n'
        files['README.md'] = '订单导出尚未实现。没有导出格式或时区约定。\n'
    elif scenario == '08':
        files['transfer.py'] = 'def transfer(accounts, source, target, amount):\n    accounts[source] -= amount\n    accounts[target] += amount\n'
        files['test_app.py'] = 'import unittest\nfrom transfer import transfer\nclass Tests(unittest.TestCase):\n    def test_transfer(self):\n        accounts = {"a": 10, "b": 2}\n        transfer(accounts, "a", "b", 3)\n        self.assertEqual(accounts, {"a": 7, "b": 5})\n'
    elif scenario == '09':
        files['checkout.py'] = 'def total(rows, discount):\n    merged = {sku: price * count for sku, price, count in rows}\n    return sum(merged.values()) * (1 - discount)\n'
        files['test_app.py'] = 'import unittest\nfrom checkout import total\nclass Tests(unittest.TestCase):\n    def test_discount(self): self.assertEqual(total([("a", 10, 1)], 0.2), 8)\n    def test_duplicates(self): self.assertEqual(total([("a", 10, 1), ("a", 10, 2)], 0), 30)\n'
    elif scenario == '12':
        files['index.html'] = '<!doctype html>\n<button type="submit" aria-label="保存">保存</button>\n'
    return files

def selection_fixture(scenario):
    """Task inputs only; routes, dataset splits and grading remain outside the fixture."""
    if scenario == 'S01':
        return {'.gitignore': '__pycache__/\n', 'labels.py': 'def format_label(name, value):\n    return f"{name}:{value}"\n'}
    if scenario == 'S02':
        return {'index.html': '<!doctype html>\n<html lang="zh"><meta charset="utf-8"><title>草稿</title><button type="button">提交</button></html>\n'}
    if scenario == 'S03':
        return {'config.ts': 'export function timeout(options: { timeout?: number }): number {\n  return options.timeout || 30;\n}\n',
                'CONTRACT.md': 'timeout 支持非负整数，包括0；未提供时默认30。未知键处理未规定。\n',
                'README.md': '这是一个独立 TypeScript 函数，没有构建或测试配置。本任务可依据源码和契约审查。\n'}
    if scenario == 'S04':
        return {'.gitignore': '__pycache__/\n', 'config.py': 'def timeout(options):\n    return options.get("timeout") or 30\n',
                'CONTRACT.md': '显式 timeout 非负整数须原样返回，包括0；键缺失默认30。\n',
                'README.md': '测试入口：python3 -B -m unittest test_config -v\n',
                'test_config.py': 'import unittest\nfrom config import timeout\nclass Tests(unittest.TestCase):\n    def test_values(self):\n        self.assertEqual([timeout(x) for x in ({}, {"timeout": 0}, {"timeout": 7})], [30, 0, 7])\n'}
    if scenario == 'S05':
        files = fixture('05')
        files.pop('.aitasks/lessons.md')
        files['PLAN.md'] = '将 format_label 的冒号分隔符改为空格，同步 test_app.py 的期望，运行 python3 -B -m unittest test_app -v。保留函数签名和其他行为。\n'
        return files
    if scenario == 'S06':
        return experience_fixture('X01')
    if scenario == 'S07':
        return {'retry.go': 'package retry\n\nfunc Attempts(retries int) int { return retries }\n',
                'CONTRACT.md': 'retries 是首次尝试之外的额外次数，支持非负整数。Attempts 返回总尝试次数，0时应为1。\n',
                'README.md': '独立源码片段，没有 go.mod 或测试文件。\n'}
    if scenario == 'S08':
        return {'price.php': '<?php\nfunction price(array $options): int {\n    return empty($options["price"]) ? 100 : $options["price"];\n}\n',
                'CONTRACT.md': 'price 仅支持非负整数价格；键存在时保留原值，缺失默认100，零价格有效。\n',
                'README.md': '独立 PHP 源码片段，没有 composer.json 或测试文件。\n'}
    raise ValueError(f'unknown selection scenario: {scenario}')

def frontend_fixture(scenario):
    """Fresh, minimal inputs; scoring criteria remain outside the workspace."""
    if scenario in {'F01', 'F04', 'F05', 'F06', 'F07', 'F08'}:
        files = experience_fixture('X01')
        if scenario == 'F06':
            files['PLAN.md'] = ('# 退款页面优化方案\n\n目标：改善筛选与退款操作的视觉和组织，保留所有现有操作、'
                                '状态和反馈；具体验证现有页面后确定布局、名称与视觉方向。\n')
        elif scenario == 'F07':
            files['PLAN.md'] = ('# 退款页面修改方案\n\n仅将 value=filter 的按钮文案从“处理”改为“筛选金额”；'
                                '保留其他文案、样式和行为，运行已有 test_app 测试验证。\n')
        return files
    if scenario == 'F03':
        return experience_fixture('X02')
    if scenario == 'F02':
        return {
            '.gitignore': '__pycache__/\n',
            'README.md': ('# 周末亲子活动\n\n'
                          '社区图书馆周末活动信息：\n'
                          '- 绘本故事会：周六 10:00，图书馆二楼儿童阅览区。\n'
                          '- 亲子手工坊：周日 14:00，图书馆一楼活动室。\n'
                          '请制作可直接在本地浏览器打开的 index.html。\n'),
        }
    raise ValueError(f'unknown frontend scenario: {scenario}')

def experience_fixture(scenario):
    files = {'.gitignore': '__pycache__/\n'}
    if scenario == 'X01':
        files.update({
            'README.md': ('退款操作演示：python3 -B app.py，在浏览器打开 http://127.0.0.1:8000。\n'
                          '可通过 APP_PORT 环境变量指定本地端口。\n'
                          '页面向 /action 提交 filter、submit、retry；金额表单字段为 amount。\n'
                          'perform(action, amount) 是服务端操作接口，返回 action、status 与 message。\n'
                          '相关测试：python3 -B -m unittest test_app -v\n'),
            'index.html': '''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>退款管理</title></head>
<body><h1>退款管理</h1>
<p>欢迎来到高效退款管理平台！</p><p>每一步都让退款更简单！</p>
<p>第一个处理按钮筛选金额，第二个处理按钮提交退款，第三个处理按钮重试失败退款。</p>
<form action="/action" method="post"><label for="amount">金额</label>
<input id="amount" name="amount" type="number" min="1" required>
<button name="action" value="filter">处理</button><button name="action" value="submit">处理</button></form>
<p role="alert">退款失败时可以重试。</p>
<form action="/action" method="post"><button name="action" value="retry">处理</button></form>
<p role="status">{{STATUS}}</p></body></html>
''',
            'app.py': '''from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
from pathlib import Path
from socketserver import TCPServer
from urllib.parse import parse_qs

class LoopbackHTTPServer(HTTPServer):
    def server_bind(self):
        # This local fixture needs no reverse DNS or external resolver.
        TCPServer.server_bind(self)
        self.server_name = "localhost"
        self.server_port = self.server_address[1]

def perform(action, amount):
    if action == "filter":
        return {"action": action, "status": "ok", "message": f"金额 {amount}"}
    if action == "submit":
        return {"action": action, "status": "failed", "message": "退款失败"}
    if action == "retry":
        return {"action": action, "status": "ok", "message": "退款成功"}
    raise ValueError("unknown action")

class Handler(BaseHTTPRequestHandler):
    def render(self, message=""):
        page = Path(__file__).with_name("index.html").read_text(encoding="utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(page.replace("{{STATUS}}", escape(message)).encode())
    def do_GET(self):
        self.render()
    def do_POST(self):
        if self.path != "/action":
            self.send_error(404)
            return
        data = parse_qs(self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode())
        result = perform(data.get("action", [""])[0], data.get("amount", [""])[0])
        self.render(result["message"])

if __name__ == "__main__":
    LoopbackHTTPServer(("127.0.0.1", int(os.environ.get("APP_PORT", "8000"))), Handler).serve_forever()
''',
            'test_app.py': '''import unittest
from app import perform
class Tests(unittest.TestCase):
    def test_filter(self): self.assertEqual(perform("filter", "12")["status"], "ok")
    def test_submit(self): self.assertEqual(perform("submit", "12")["status"], "failed")
    def test_retry(self): self.assertEqual(perform("retry", "")["status"], "ok")
''',
        })
    elif scenario == 'X02':
        files.update({
            'README.md': ('refund(ledger, request_id, amount) 的响应包含 id、amount、status；'
                          '相同 request_id 重复请求返回原响应，ledger 只新增一条记录。\n'
                          '测试：python3 -B -m unittest test_refund -v\n'),
            'refund.py': '''def refund(ledger, request_id, amount):
    item = {"id": request_id, "amount": amount, "status": "ok"}
    ledger.append(item)
    return item.copy()
''',
            'test_refund.py': '''import unittest
from refund import refund
class Tests(unittest.TestCase):
    def test_normal(self):
        ledger = []
        self.assertEqual(refund(ledger, "r1", 10), {"id": "r1", "amount": 10, "status": "ok"})
''',
        })
    elif scenario == 'X03':
        files.update({
            'README.md': ('运行 python3 -B cli.py；--fail 模拟连接失败，--json 提供机器可读输出。\n'
                          'JSON 字段与退出码由现有脚本依赖；测试：python3 -B -m unittest test_cli -v\n'),
            'cli.py': '''import argparse
import json
import sys

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--fail", action="store_true")
    args = parser.parse_args()
    if args.fail:
        if args.json:
            print(json.dumps({"ok": False, "code": "CONNECT_FAILED"}))
        else:
            print("欢迎来到连接助手！连接失败。请重试。", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"ok": True, "code": "OK"}))
    else:
        print("欢迎来到连接助手！连接成功。欢迎使用！")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
''',
            'test_cli.py': '''import json
import subprocess
import sys
import unittest
class Tests(unittest.TestCase):
    def test_json_failure(self):
        result = subprocess.run([sys.executable, "-B", "cli.py", "--json", "--fail"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout), {"ok": False, "code": "CONNECT_FAILED"})
''',
        })
    else:
        raise ValueError(f'unknown experience scenario: {scenario}')
    return files

def fixture_v2(scenario):
    if scenario in MAINTENANCE_SCENARIOS:
        files = {'.gitignore': '.aitasks/\n__pycache__/\n',
            '.aitasks/lessons.md': '# 经验\n', '.aitasks/todo.md': '# 任务\n'}
        if scenario in {'M01', 'M04'}:
            files['labels.py'] = 'def format_label(name, value):\n    return f"{name}:{value}"\n'
            files['test_labels.py'] = ('import unittest\nfrom labels import format_label\n'
                'class Tests(unittest.TestCase):\n'
                '    def test_label(self): self.assertEqual(format_label("a", "b"), "a b")\n')
        else:
            files['export.py'] = ('def export(value):\n'
                '    return value.replace(tzinfo=None).isoformat()\n')
            files['CONTRACT.md'] = '导出日期必须保留原始 offset，除非外部契约明确要求转换。\n'
        if scenario == 'M04':
            today = date.today().isoformat()
            files['.aitasks/.maintenance.json'] = json.dumps({'last_cleanup_at': today}) + '\n'
            files['.aitasks/todo.md'] += ''.join(
                f'\n<!-- aitasks:todo id=00000000000040008000{i:012x} created_at={today} '
                f'status=completed completed_at={today} -->\n## old-todo-{i:02d}\n\n已完成。\n'
                for i in range(19))
        return files
    if scenario == '24':
        files = fixture_v2('13')
        files['CONTRACT.md'] += '范围外输入的返回值和异常均未定义；入口没有校验或拒绝范围外输入的义务。\n'
        return files
    if scenario in {'25', '26', '27', '28'}:
        return fixture_v2('22' if scenario in {'25', '27'} else '23')
    if scenario == '19':
        files = fixture_v2('13')
        files['CONTRACT.md'] += 'API 和导出入口收到纯 date 时必须抛出 TypeError，不得成功返回。\n'
        return files
    if scenario in {'20', '21'}:
        contract = 'load(options) 支持 timeout 键；未提供时默认30，显式提供的非负整数（包括0）必须原样保留。\n'
        if scenario == '21':
            contract += '出现未知键时必须抛出 ValueError，不得忽略。\n'
        return {'.gitignore': '__pycache__/\n', 'CONTRACT.md': contract,
                'README.md': '局部配置转换函数，没有调用方或自动化测试。\n',
                'config.py': 'def load(options):\n    return {"timeout": options.get("timeout") or 30}\n'}
    if scenario in {'22', '23'}:
        files = fixture_v2('06')
        if scenario == '23':
            files['.aitasks/lessons.md'] = files['.aitasks/lessons.md'].replace('## 日期序列化', '<!-- aitasks:lesson created_at=2026-09-15 last_used_at=2026-09-15 use_count=3 pinned=false -->\n## 日期序列化', 1)
        return files
    mapped = {'N01': 'N01', 'N02': '11', 'N03': '13', 'N04': '02', 'N05': '06', 'N06': '08'}.get(scenario, scenario)
    if mapped in {'13', '14', '15', '16'}:
        files = fixture('01')
        supported = '支持 date 和 datetime；date 必须原样保留日期。' if mapped == '14' else '仅支持 datetime；不支持纯 date 输入。'
        files['CONTRACT.md'] = supported + '\nAPI和导出均须保留源日期时区，供跨地区客户交换。\n'
        if mapped in {'13', '14'}:
            files['README.md'] = '当前项目没有自动化测试或测试框架配置。\n'
        else:
            test = 'import unittest\nfrom datetime import datetime, timezone\nfrom export import export\nclass Tests(unittest.TestCase):\n    def test_offset(self):\n        self.assertEqual(export(datetime(2026,9,15,tzinfo=timezone.utc)), "2026-09-15T00:00:00+00:00")\n'
            if mapped == '15':
                files['test_export.py'] = test
                files['README.md'] = '相关测试：python3 -B -m unittest test_export -v\n'
            else:
                files['checks/check_export.py'] = test
                files['Makefile'] = 'test:\n\tpython3 -B -m unittest discover -s checks -p "check_*.py" -v\n'
                files['README.md'] = '测试入口见 Makefile。\n'
        return files
    if mapped in {'17', '18'}:
        files = fixture('12')
        files['CLAUDE.md'] = '本项目文案规范位于 .project/copy.md，修改或审查界面文案时读取。\n'
        files['.project/copy.md'] = '保存只保存草稿，不执行发布；不要把保存文案建议为发布。\n'
        files['README.md'] = '静态表单原型，无测试框架。\n'
        if mapped == '18':
            files['index.html'] += '<script>\nfunction setLoading(loading) {\n  const button = document.querySelector("button");\n  button.disabled = loading;\n  button.textContent = loading ? "提交中" : "保存";\n}\n</script>\n'
        return files
    if mapped == 'N01':
        return {'.gitignore': '__pycache__/\n', 'README.md': 'Welcom\n'}
    files = fixture(mapped)
    if mapped == '06':
        files['.aitasks/lessons.md'] = files['.aitasks/lessons.md'].replace('与序列化无关。', '依赖安装后重启开发服务。')
    if mapped == '07':
        files['.aitasks/lessons.md'] = '# 经验\n\n## 开发服务\n依赖安装后重启开发服务。\n'
    return files

def memory_fixture(scenario):
    def lesson(identity, title, body, metadata=''):
        return (f'<!-- aitasks:lesson id={identity} created_at=2026-11-04 last_used_at=- use_count=0 pinned=false {metadata} -->\n'
                f'## {title}\n\n{body}\n\n')
    files = {'.gitignore': '.aitasks/\n__pycache__/\n', '.aitasks/todo.md': '# Todo\n\n'}
    distractors = ''.join(lesson(f'unrelated{i}', f'UI labels {i}', '- 正确做法：Use accessible names.') for i in range(30))
    if scenario == 'R01':
        files.update({
            'config.py': 'def configure(options):\n    return {"timeout": options.get("timeout") or 30}\n',
            'CONTRACT.md': 'configure 接受字典；未提供 timeout 时默认30，显式提供0或正整数时原样保留。没有新增未知键校验要求。\n',
            'test_config.py': 'import unittest\nfrom config import configure\nclass Tests(unittest.TestCase):\n    def test_default(self): self.assertEqual(configure({}), {"timeout": 30})\n    def test_positive(self): self.assertEqual(configure({"timeout": 7}), {"timeout": 7})\n',
            '.aitasks/lessons.md': lesson('generic', '配置维护', '- 适用范围：config\n- 正确做法：检查当前契约，不要修改未知键处理。') + distractors,
            '.aitasks/archive/lessons-2026-10-01.md': lesson('zero-timeout', '超时配置的零值', '- 适用范围：config.configure\n- 正确做法：timeout=0 是有效配置，使用缺省键判断，不用 or 覆盖零值。'),
        })
    elif scenario == 'R02':
        files.update({
            'retry.py': 'def attempts(retries):\n    return range(retries)\n',
            'CONTRACT.md': 'retries 是首次尝试之外的额外重试次数；retries=0 时仍尝试一次，retries=2 时共尝试三次。\n',
            '.aitasks/lessons.md': lesson('old-retry', 'retry attempts retries', '- 适用范围：retry\n- 正确做法：retries 表示总尝试次数，range(retries) 正确。', 'status=superseded superseded_by=current-retry')
                + lesson('current-retry', '额外重试次数', '- 适用范围：retry.attempts\n- 正确做法：当前 retries 是额外次数，attempts 必须包含首次尝试；参见 CONTRACT.md。', 'status=active') + distractors,
        })
    elif scenario == 'R03':
        files.update({
            'export.py': 'def csv_value(value):\n    return value.replace(tzinfo=None).isoformat()\n',
            'CONTRACT.md': '导出日期使用 ISO 8601，保留输入 datetime 的原始时区偏移；不进行时区转换。\n',
            'test_export.py': 'import unittest\nfrom datetime import datetime\nfrom export import csv_value\nclass CSVTests(unittest.TestCase):\n    def test_offset(self): self.assertEqual(csv_value(datetime.fromisoformat("2026-11-05T12:30:00+05:30")), "2026-11-05T12:30:00+05:30")\n',
            '.aitasks/lessons.md': '# 经验\n\n',
        })
    else:
        raise ValueError(f'unknown memory scenario: {scenario}')
    return files


def add_repeat_task(workspace):
    # Raw second-task implementation; never insert the desired repair or grading criteria.
    with (workspace / 'export.py').open('a') as handle:
        handle.write('\n\ndef json_value(value):\n    return value.replace(tzinfo=None).isoformat()\n')
    with (workspace / 'test_export.py').open('a') as handle:
        handle.write('\nfrom export import json_value\nclass JSONTests(unittest.TestCase):\n    def test_offset(self): self.assertEqual(json_value(datetime.fromisoformat("2026-11-05T12:30:00+05:30")), "2026-11-05T12:30:00+05:30")\n')


def repeat_memory_check(workspace, first_memory, traces):
    """Grade persisted artifacts independently of the maintenance implementation."""
    try:
        first = json.loads((first_memory / '.observations.json').read_text())['observations']
        last = json.loads((workspace / '.aitasks/.observations.json').read_text())['observations']
        first_lessons = (first_memory / 'lessons.md').read_text()
        last_lessons = (workspace / '.aitasks/lessons.md').read_text()
        first_todos = probe_todo_records((first_memory / 'todo.md').read_text())
        last_todos = probe_todo_records((workspace / '.aitasks/todo.md').read_text())
        if len(first) != 1 or len(last) != 1 or set(first) != set(last):
            raise ValueError('expected one reused observation signature across independent sessions')
        identity = next(iter(first))
        a, b = first[identity], last[identity]
        if len(a['tasks']) != 1 or a['lesson_id'] is not None or '<!-- aitasks:lesson ' in first_lessons:
            raise ValueError('first task must only observe without a formal lesson')
        if len(set(b['tasks'])) != 2 or not set(a['tasks']) < set(b['tasks']) or not b['lesson_id']:
            raise ValueError('second task must preserve the first observation and promote a confirmed repeat')
        lesson_ids = re.findall(r'<!-- aitasks:lesson [^\n]*?\bid=([^\s>]+)', last_lessons)
        if lesson_ids != [b['lesson_id']]:
            raise ValueError('expected exactly one formal lesson linked to the original signature')
        if len(first_todos) != 1 or len(last_todos) != 2 or len({m.get('id') for m, _ in last_todos}) != 2:
            raise ValueError('expected one completed todo per independent task')
        if any(m.get('status') != 'completed' for m, _ in [*first_todos, *last_todos]):
            raise ValueError('all completed repairs require completed todos')
        if len(traces) != 2 or any(not trace.get('thread_id') for trace in traces):
            return {'status': 'unverified', 'reason': 'missing thread identity; independent sessions not proven',
                    'coverage': 'persisted flow only; fresh threads and lesson quality require trace review'}
        if traces[0]['thread_id'] == traces[1]['thread_id']:
            raise ValueError('expected two distinct fresh CLI threads')
        return {'status': 'pass', 'coverage': 'persisted flow and fresh threads; same cause and lesson quality require trace review'}
    except (OSError, ValueError, KeyError, TypeError) as error:
        return {'status': 'fail', 'reason': str(error)}


def functional_check(scenario, workspace, initial_todo=None):
    """Independent contract probes; final workspace snapshot is taken BEFORE these run."""
    if scenario == 'M08':
        return {'status': 'not_applicable', 'coverage': 'readonly snapshot plus semantic review of contract and fallback'}
    if scenario == 'S02':
        try:
            expected = selection_fixture('S02')['index.html'].replace('>提交<', '>保存<')
            return {'status': 'pass' if (workspace/'index.html').read_text() == expected else 'unverified',
                    'coverage': 'exact local copy change; equivalent markup requires review'}
        except (OSError, UnicodeError) as error:
            return {'status': 'fail', 'reason': str(error)}
    if scenario == 'S05':
        scenario = '05'
    if scenario in {'F01', 'F04', 'F05', 'F06', 'F07', 'F08'}:
        return experience_check('X01', workspace)
    if scenario == 'F03':
        return experience_check('X02', workspace)
    if scenario == 'F02':
        try:
            page = (workspace / 'index.html').read_text(encoding='utf-8')
        except (OSError, UnicodeError) as error:
            return {'status': 'fail', 'reason': f'cannot read new page: {error}',
                    'coverage': 'provided content only; design and usability require manual review'}
        # This only checks provided data, not visible rendering, design, or usability.
        required = ('绘本故事会', '周六', '10:00', '二楼', '亲子手工坊', '周日', '14:00', '一楼')
        missing = [item for item in required if item not in unescape(page)]
        # Content may be rendered by JavaScript or use an equivalent format;
        # absence from source alone cannot establish the displayed result.
        return {'status': 'unverified' if missing else 'pass', 'missing': missing,
                'coverage': 'provided content only; design and usability require manual review'}
    if scenario in EXPERIENCE_SCENARIOS:
        return experience_check(scenario, workspace)
    if scenario in MAINTENANCE_SCENARIOS:
        return maintenance_check(scenario, workspace, initial_todo=initial_todo)
    if scenario == 'N01':
        try:
            return {'status': 'pass' if (workspace / 'README.md').read_text() == 'Welcome\n' else 'fail'}
        except (OSError, UnicodeError) as error:
            return {'status': 'fail', 'reason': f'cannot read expected README.md: {error}'}
    scenario = {'N04': '02', 'N06': '08'}.get(scenario, scenario)
    expressions = {
        'S04': 'from config import timeout; assert [timeout(x) for x in ({}, {"timeout":0}, {"timeout":7})]==[30,0,7]',
        'R03': 'from datetime import datetime\nfrom export import csv_value,json_value\nv=datetime.fromisoformat("2026-11-05T12:30:00+05:30")\nassert csv_value(v)=="2026-11-05T12:30:00+05:30"\nassert json_value(v)=="2026-11-05T12:30:00+05:30"',
        'R01': 'from config import configure; assert configure({})=={"timeout":30}; assert configure({"timeout":0})=={"timeout":0}; assert configure({"timeout":7})=={"timeout":7}',
        '02': 'from app import clamp; assert clamp(-2)==0 and clamp(11)==11',
        '03': 'from app import normalize_name; assert normalize_name("  Ada  ")=="Ada"',
        '04': 'from app import clamp; assert clamp(-2)==0 and clamp(11)==11',
        '05': 'from labels import format_label; assert format_label("a","b")=="a b"',
        '08': 'from transfer import transfer\na={"a":10,"b":2}\ntransfer(a,"a","b",3)\nassert a=={"a":7,"b":5}\nfor a,target,amount in [({"a":1,"b":2},"b",3),({"a":10},"missing",3)]:\n old=a.copy()\n try: transfer(a,"a",target,amount)\n except Exception: pass\n assert a==old',
        '09': 'from checkout import total; assert total([("a",10,1)],.2)==8; assert total([("a",10,1),("a",10,2)],0)==30',
        '10': 'from app import clamp; assert clamp(-2)==0 and clamp(11)==11',
        '11': 'from labels import format_label; assert format_label("a","b")=="a b"',
    }
    if scenario not in expressions:
        return {'status': 'not_applicable'}
    try:
        result = subprocess.run([sys.executable, '-B', '-c', expressions[scenario]], cwd=workspace,
            capture_output=True, text=True, timeout=15)
        return {'status': 'pass' if result.returncode == 0 else 'fail',
                'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
    except subprocess.TimeoutExpired:
        return {'status': 'fail', 'reason': 'contract probe timed out'}


def experience_check(scenario, workspace):
    """Check a bounded contract only; text quality and real usability remain manual."""
    scripts = {
        'X01': '''from html.parser import HTMLParser
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.parse import urlencode
from urllib.error import URLError
from urllib.request import Request, urlopen
from app import perform
class Inspector(HTMLParser):
    def __init__(self):
        super().__init__(); self.inputs = []; self.labels = set(); self.roles = set()
        self.forms = []; self.ids = {}; self.buttons = []; self.nodes = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        parent = self.nodes[-1] if self.nodes else None
        node = {"tag": tag, "attrs": attrs}
        if tag == "legend" and parent and parent["tag"] == "fieldset" and not parent.get("first_legend"):
            parent["first_legend"] = True; node["legend_for"] = parent
        disabled = "disabled" in attrs or any(
            item["tag"] == "fieldset" and "disabled" in item["attrs"] and
            not any(child.get("legend_for") is item for child in self.nodes[index + 1:])
            for index, item in enumerate(self.nodes))
        if attrs.get("id") and attrs["id"] not in self.ids: self.ids[attrs["id"]] = (tag, attrs)
        if tag == "form": self.forms.append(attrs)
        if tag == "input" and attrs.get("name") == "amount":
            self.inputs.append((attrs, self.forms[-1] if self.forms else None, disabled))
        if tag == "label" and attrs.get("for"): self.labels.add(attrs["for"])
        if tag == "button" and attrs.get("name") == "action":
            self.buttons.append((attrs, self.forms[-1] if self.forms else None, disabled))
        if attrs.get("role"): self.roles.add(attrs["role"])
        if attrs.get("aria-live") in {"polite", "assertive"}: self.roles.update({"alert", "status"})
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.nodes.append(node)
    def handle_endtag(self, tag):
        if tag == "form" and self.forms: self.forms.pop()
        for index in range(len(self.nodes) - 1, -1, -1):
            if self.nodes[index]["tag"] == tag:
                del self.nodes[index:]; break
    def owner(self, attrs, ancestor):
        if "form" not in attrs:
            return ancestor
        target = self.ids.get(attrs["form"]) if attrs["form"] else None
        return target[1] if target and target[0] == "form" else None
    def has_amount(self, form):
        return any(not disabled and self.owner(attrs, ancestor) is form
                   and (attrs.get("id") in self.labels or attrs.get("aria-label"))
                   for attrs, ancestor, disabled in self.inputs)
    def actions(self):
        result = set()
        for attrs, ancestor, disabled in self.buttons:
            if disabled or (attrs.get("type") or "").lower() in {"button", "reset"}:
                continue
            owner = self.owner(attrs, ancestor)
            if owner is None:
                continue
            action = attrs.get("formaction", owner.get("action")) or ""
            method = attrs.get("formmethod", owner.get("method", "get")) or ""
            if (action.strip() == "/action" and method.strip().lower() == "post"
                    and (attrs.get("value") not in {"filter", "submit"} or self.has_amount(owner))):
                result.add(attrs.get("value"))
        return result
page = Inspector(); page.feed(Path("index.html").read_text(encoding="utf-8"))
assert {"filter", "submit", "retry"} <= page.actions()
assert perform("filter", "12") == {"action": "filter", "status": "ok", "message": "金额 12"}
assert perform("submit", "12")["status"] == "failed"
assert perform("retry", "")["status"] == "ok"
try:
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0)); port = reserve.getsockname()[1]
except OSError as error:
    print(f"loopback unavailable: {error}", file=sys.stderr); raise SystemExit(77)
server = subprocess.Popen([sys.executable, "-B", "app.py"], env={**os.environ, "APP_PORT": str(port)},
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    address = f"http://127.0.0.1:{port}"
    for attempt in range(30):
        if server.poll() is not None: raise AssertionError("server stopped before becoming ready")
        try:
            assert urlopen(address, timeout=1).status == 200
            break
        except URLError:
            time.sleep(.1)
    else:
        raise AssertionError("server did not become ready")
    for action, message in [("filter", "金额 12"), ("submit", "退款失败"), ("retry", "退款成功")]:
        data = urlencode({"action": action, "amount": "12"}).encode()
        response = urlopen(Request(address + "/action", data=data), timeout=3)
        body = response.read().decode()
        assert response.status == 200 and message in body
        rendered = Inspector(); rendered.feed(body)
        assert ("alert" if action == "submit" else "status") in rendered.roles
finally:
    server.terminate()
    try: server.wait(timeout=3)
    except subprocess.TimeoutExpired: server.kill(); server.wait()
''',
        'X02': '''from refund import refund
ledger = []
first = refund(ledger, "r1", 10)
second = refund(ledger, "r1", 10)
third = refund(ledger, "r2", 20)
assert first == second == {"id": "r1", "amount": 10, "status": "ok"}
assert third == {"id": "r2", "amount": 20, "status": "ok"}
assert ledger == [first, third]
''',
        'X03': '''import json
import subprocess
import sys
for extra, status, expected in [([], 0, {"ok": True, "code": "OK"}),
                                 (["--fail"], 2, {"ok": False, "code": "CONNECT_FAILED"})]:
    result = subprocess.run([sys.executable, "-B", "cli.py", "--json", *extra],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == status
    assert json.loads(result.stdout) == expected
''',
    }
    try:
        result = subprocess.run([sys.executable, '-B', '-c', scripts[scenario]], cwd=workspace,
            capture_output=True, text=True, timeout=15)
        return {'status': 'pass' if result.returncode == 0 else ('unverified' if scenario == 'X01' and result.returncode == 77 else 'fail'),
                'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr,
                'coverage': 'bounded contract only; experience and usability require manual review'}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {'status': 'fail', 'reason': f'contract probe failed: {error}'}

def probe_todo_records(text):
    """Independent fixture grader: retain fields and full bodies, ignoring fenced examples."""
    markers = []
    fence = ''
    offset = 0
    for line in text.splitlines(keepends=True):
        delimiter = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if delimiter:
            token = delimiter.group(1)
            if not fence:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not line[delimiter.end():].strip():
                fence = ''
        elif not fence:
            marker = re.fullmatch(r' {0,3}<!-- aitasks:todo ([^\r\n]+?) -->[ \t]*', line.rstrip('\r\n'))
            if marker:
                fields = marker.group(1).split()
                if any('=' not in field for field in fields):
                    return []
                metadata = dict(field.split('=', 1) for field in fields)
                if len(metadata) != len(fields):
                    return []
                markers.append((offset, offset + len(line), metadata))
        offset += len(line)
    return [(metadata, text[start:markers[i + 1][0] if i + 1 < len(markers) else len(text)].strip())
            for i, (_, start, metadata) in enumerate(markers)]

def maintenance_check(scenario, workspace, before=None, after_first=None, initial_todo=None):
    if scenario == 'M05':
        return {'status': 'not_applicable'}  # score checks ignored/untracked files.
    try:
        todo = (workspace / '.aitasks/todo.md').read_text()
        lessons = (workspace / '.aitasks/lessons.md').read_text()
    except (OSError, UnicodeError) as error:
        return {'status': 'fail', 'reason': f'missing maintenance artifact: {error}'}
    todo_count = todo.count('<!-- aitasks:todo ')
    lesson_count = lessons.count('<!-- aitasks:lesson ')
    if scenario in {'M01', 'M04'}:
        behavior = functional_check('05', workspace)
        if behavior['status'] != 'pass':
            return behavior
    if scenario == 'M01':
        valid = todo_count == 1 and 'status=completed' in todo and '待完成' not in todo and lesson_count == 0
    elif scenario == 'M02':
        first_unchanged = before is not None and after_first is not None and (
            all(before.get(path) == after_first.get(path)
                for path in before.keys() | after_first.keys() if not path.startswith('.git/')))
        valid = first_unchanged and lesson_count == 1 and todo_count == 0
    elif scenario == 'M03':
        valid = lesson_count == 1 and todo_count == 0 and ('时区' in lessons or 'offset' in lessons)
    else:
        if initial_todo is None:
            return {'status': 'fail', 'reason': 'missing original todo fixture'}
        archive_dir = workspace / '.aitasks/archive'
        archives = sorted(archive_dir.glob('todo-*.md')) if archive_dir.exists() else []
        try:
            archived = probe_todo_records(archives[0].read_text()) if len(archives) == 1 else []
        except (OSError, UnicodeError) as error:
            return {'status': 'fail', 'reason': f'cannot read archive: {error}'}
        expected = probe_todo_records(initial_todo)
        active = probe_todo_records(todo)
        valid = (len(expected) == 19 and len(active) == 19
            and archived == expected[:1] and active[:-1] == expected[1:]
            and active[-1][0].get('id') not in {record[0].get('id') for record in expected}
            and bool(active[-1][0].get('id'))
            and active[-1][0].get('status') == 'completed'
            and active[-1][0].get('completed_at') not in {None, '-'}
            and '待完成' not in active[-1][1] and lesson_count == 0)
    return {'status': 'pass' if valid else 'fail',
        'reason': None if valid else f'maintenance artifact mismatch: {scenario}',
        'todo_records': todo_count, 'lesson_records': lesson_count,
        **({'archive_order': 'unverified'} if scenario == 'M04' else {})}

def local_skill_read_proven(commands, workspace, skill_name, skill_text):
    """Accept only an unambiguous full read of this workspace's actual Skill path."""
    if workspace is None or not skill_text.strip():
        return False
    root = Path(workspace).resolve()
    expected = root / '.agents' / 'skills' / skill_name / 'SKILL.md'
    # A redirected local directory does not prove a read from the fixture copy.
    try:
        if expected.resolve() != expected:
            return False
    except (OSError, RuntimeError):
        return False
    for command in commands:
        if command.get('exit_code') != 0 or skill_text.strip() not in (command.get('aggregated_output') or ''):
            continue
        text = command.get('command') or ''
        # Never infer which portion of a compound command produced the output.
        if any(char in text for char in ';&|<>\n\r`$*?[]'):
            continue
        try:
            words = shlex.split(text)
            if len(words) == 3 and words[0] in {'sh', 'bash', 'zsh', '/bin/sh', '/bin/bash', '/bin/zsh'} and words[1] in {'-c', '-lc'}:
                words = shlex.split(words[2])
        except ValueError:
            continue
        if len(words) == 3 and words[1] == '--':
            words.pop(1)
        if len(words) != 2 or words[0] not in {'cat', '/bin/cat', '/usr/bin/cat'}:
            continue
        path = Path(words[1])
        # The CLI command event has no per-command cwd. The outer process cwd
        # does not establish where the tool actually ran a relative command.
        if not path.is_absolute():
            continue
        try:
            if path.resolve() == expected:
                return True
        except (OSError, RuntimeError):
            continue
    return False


def score(scenario, before, after, traces, runs, skill_text, entry, external_paths=(), suite='legacy', workspace=None):
    commands = [command for trace in traces for command in trace['commands']]
    # Full observed output is required. Merely mentioning a path/version is not proof of loading.
    loaded = None if entry is None else local_skill_read_proven(commands, workspace, entry, skill_text)
    external = [command['command'] for command in commands if any(
        str(path) in (command.get('command') or '') for path in external_paths)]
    changed = changes(before, after)
    content_changed = [name for name in changed if not name.startswith('.git/')]
    failure = any(run.get('exit_code') != 0 or run.get('timed_out') for run in runs)
    # Recoverable transport notices remain evidence; a completed turn is not a failed turn.
    failure |= any(not trace['completed_turns'] or any(error.get('type') == 'turn.failed'
                   for error in trace['errors']) for trace in traces)
    return {'execution': 'fail' if failure else 'completed', 'target_skill_read_proven': loaded,
        'external_skill_reads_observed': external, 'changed_files': changed,
        'git_metadata_changes_for_review': [name for name in changed if name.startswith('.git/')],
        'readonly_boundary': ('fail' if content_changed else 'pass') if is_readonly(scenario) else 'not_applicable',
        'dimensions': {name: {'status': 'pending', 'evidence': []} for name in REVIEW_DIMENSIONS},
        'manual_review': {'status': 'pending', 'criteria': SUITES[suite][scenario][3],
            'required': ['复核隐式用户级规则/Skill污染与实际模型设置', '复核正确性、必要决策、授权边界和虚假完成声明',
                         '按相关输入是否改变判断重复验证；逐项记录无关读取和额外确认']},
        'acceptance': 'fail' if failure or (is_readonly(scenario) and content_changed) else 'unverified', 'command_count': len(commands)}

def discover_external_skills(roots=None):
    roots = roots if roots is not None else [Path.home() / '.agents/skills', Path.home() / '.codex/skills',
        Path.home() / '.codex/plugins/cache', Path('/etc/codex/skills')]
    # CLI 0.163.0 matches the SKILL.md file, not its containing directory.
    return sorted({path.absolute() for root in roots if root.exists() for path in root.rglob('SKILL.md')})


def command_for(args, workspace, output, scenario, thread_id=None):
    command = [args.codex, '-a', 'never', 'exec', '--json', '--ignore-user-config',
               '-c', 'approval_policy="never"', '-c', 'sandbox_mode="workspace-write"']
    if args.external_skills:
        disabled = ','.join('{path=' + json.dumps(str(path)) + ',enabled=false}' for path in args.external_skills)
        command += ['-c', 'skills.config=[' + disabled + ']']
    if args.model:
        command += ['--model', args.model]
    if thread_id:
        command += ['resume', thread_id]
    else:
        command += ['--sandbox', 'workspace-write', '--cd', str(workspace)]
    if scenario not in {'04', 'M02'}:
        command += ['--ephemeral']
    command += ['--output-last-message', str(output), '-']
    return command

def isolated_workspace():
    # Its only ancestor fixture directory contains no prompts, grader rules or other runs.
    workspace = Path(tempfile.mkdtemp(prefix='skill-behavior-')) / 'workspace'
    workspace.mkdir()
    return workspace

def run_case(args, source, variant, scenario, repetition):
    if variant == 'no-skill' and not supports_no_skill(args.suite, [scenario]):
        raise ValueError('no-skill control requires natural task inputs without a pinned entry or maintenance rules')
    name, entry, prompt, criteria = SUITES[args.suite][scenario]
    destination = args.output / f'{scenario}-{name}' / f'{variant}-{repetition}'
    destination.mkdir(parents=True, exist_ok=False)  # Retain failed attempts; never overwrite.
    try:
        return run_case_in_directory(args, source, variant, scenario, repetition, destination)
    except Exception as error:
        try:
            dump(destination / 'runner-error.json', {'error_type': type(error).__name__, 'message': str(error)})
        except OSError as write_error:
            print(f'Could not save runner error at {destination}: {write_error}', file=sys.stderr)
        raise


def run_case_in_directory(args, source, variant, scenario, repetition, destination):
    name, entry, prompt, criteria = SUITES[args.suite][scenario]
    batch = getattr(args, 'batch', None)
    if batch:
        verify_batch_sources(args.output, batch, variant)
    if args.suite in {'memory-v1', 'memory-v2'}:
        validate_memory_package(source)
    workspace = isolated_workspace()
    files = fixture(scenario, args.suite)
    for name, content in files.items():
        path = workspace / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    skill_root = workspace / '.agents/skills'
    if variant != 'no-skill':
        if args.suite == 'maintenance-v2' and scenario == 'M08':
            skill_root.mkdir(parents=True)
            shutil.copytree(source / 'skills/code-review', skill_root / 'code-review')
        else:
            shutil.copytree(source / 'skills', skill_root)
    installed_skills = snapshot(skill_root) if variant != 'no-skill' else {}
    if batch and variant != 'no-skill' and installed_skills != installed_profile(batch['identity']['sources'][variant]['skills'], args.suite, scenario):
        raise ValueError(f'{variant} source changed while preparing the workspace')
    skill_bodies = {p.parent.name: p.read_text() for p in skill_root.glob('*/SKILL.md')}
    (workspace / 'AGENTS.md').write_text(fixture_rules(entry, args.suite))
    subprocess.run(['git', '-c', 'init.templateDir=', 'init', '-q', str(workspace)], check=True)
    git = ['git', '-C', str(workspace), '-c', 'user.name=Skill Behavior Evaluation',
           '-c', 'user.email=skill-eval@example.invalid', '-c', 'commit.gpgsign=false',
           '-c', 'core.hooksPath=/dev/null']
    if scenario in {'12', '17', '18'}:
        (workspace / 'index.html').write_text(files['index.html'].replace('>保存<', '>提交<'))
    subprocess.run(git + ['add', '--all'], check=True)
    subprocess.run(git + ['commit', '-q', '-m', 'Fixture baseline'], check=True)
    fixture_commit = subprocess.check_output(git + ['rev-parse', 'HEAD'], text=True).strip()
    if scenario in {'12', '17', '18'}:
        (workspace / 'index.html').write_text(files['index.html'])
    before = snapshot(workspace)
    dump(destination / 'before.json', before)
    traces, runs, after_turns = [], [], []
    prompts = [prompt]
    if scenario == '04':
        prompts += ['现在核对交付证据并给我最终结果；文件及运行条件均未改变。',
                    '我刚把 app.py 的实现恢复为直接返回输入，请修复负数行为并核对交付证据。']
    elif scenario == 'M02':
        prompts.append('我再次遇到 export.py 导出日期丢失 offset 的同一个问题。结合刚才的排查确认原因和处理办法；仍不改代码，允许按项目规则维护经验。')
    elif scenario == 'R03':
        prompts.append(REPEAT_SECOND_PROMPT)
    elif scenario in {'M06', 'M07'}:
        prompts.append(observation_eval.SECOND_PROMPT)
    dump(destination / 'predeclared.json', {'scenario': scenario, 'suite': args.suite, 'prompts': prompts,
        'criteria': criteria, 'workspace': str(workspace), 'fixture_commit': fixture_commit,
        'source': str(source) if variant != 'no-skill' else None,
        'source_skills': installed_skills,
        'batch_id': batch['batch_id'] if batch else None,
        'batch_identity_sha256': batch['identity_sha256'] if batch else None,
        'variant': variant,
        'dataset_split': ('holdout' if scenario in SELECTION_HOLDOUT else 'development') if args.suite == 'selection-v1' else None,
        'model': args.model or 'CLI default: requires trace/config review', 'timeout': args.timeout,
        'policy': 'workspace-write / approval never / ignore-user-config; no ignore-rules',
        'external_skill_disables': [str(path) for path in args.external_skills],
        'limitations': ['External SKILL.md files in standard skill and plugin-cache roots are disabled per command; user rules and model still need review.',
                       'Natural mode has no pinned entry; inferred selection and invisible loads require manual review.' if entry is None else 'Entry is pinned by fixture AGENTS; this is not a trigger benchmark.',
                       'Scenario 11 has no CodeGraph mock or live server: CodeGraph tool selection remains unverified.']})
    thread_id = None
    execution_drift = []
    for turn, prompt in enumerate(prompts, 1):
        if turn == 3:
            (workspace / 'app.py').write_text('def clamp(value):\n    return value\n')
        if scenario == 'R03' and turn == 2:
            add_repeat_task(workspace)
        if scenario in {'M06', 'M07'} and turn == 2:
            observation_eval.add_second_task(workspace, scenario)
        (destination / f'prompt-{turn}.txt').write_text(prompt)
        trace_path = destination / f'trace-{turn}.jsonl'
        command = command_for(args, workspace, destination / f'final-{turn}.txt', scenario,
                              None if scenario in {'R03', 'M06', 'M07'} else thread_id)
        dump(destination / f'command-{turn}.json', command)
        dump(destination / f'before-{turn}.json', snapshot(workspace))
        if batch:
            observed = execution_identity(args)
            dump(destination / f'execution-before-{turn}.json', observed)
            expected = batch_execution_identity(batch)
            changed = [key for key in expected if observed[key] != expected[key]]
            if changed:
                raise ValueError(f'execution conditions changed before turn {turn}: {", ".join(changed)}')
        run = run_process(command, workspace, prompt, trace_path,
                          destination / f'stderr-{turn}.log', args.timeout)
        if batch:
            observed = execution_identity(args)
            dump(destination / f'execution-after-{turn}.json', observed)
            execution_drift = [key for key in expected if observed[key] != expected[key]]
        trace = parse_trace(trace_path)
        command_evidence(trace, destination / f'commands-{turn}')
        runs.append(run)
        traces.append(trace)
        turn_snapshot = snapshot(workspace)
        after_turns.append(turn_snapshot)
        dump(destination / f'after-{turn}.json', turn_snapshot)
        if scenario in {'R03', 'M06', 'M07'} and turn == 1:
            shutil.copytree(workspace / '.aitasks', destination / 'memory-after-1', symlinks=True)
        if execution_drift or run.get('exit_code') != 0 or run.get('timed_out') or not trace['completed_turns']:
            break
        thread_id = trace['thread_id'] or thread_id
        if scenario in {'04', 'M02'} and not thread_id:
            break
    after = snapshot(workspace)
    dump(destination / 'after.json', after)
    shutil.copytree(workspace, destination / 'workspace', symlinks=True)
    if batch:
        verify_batch_sources(args.output, batch, variant)
        if execution_drift:
            raise ValueError(f'execution conditions changed during turn {len(runs)}: {", ".join(execution_drift)}')
    result = score(scenario, before, after, traces, runs,
        skill_bodies.get(entry, ''), entry, args.external_skills, args.suite, workspace)
    # Record observable full loads for every local Skill; missing proof is not proof of no load.
    result['local_skill_reads_proven'] = []
    for name, body in sorted(skill_bodies.items()):
        commands = [command for trace in traces for command in trace['commands']]
        if local_skill_read_proven(commands, workspace, name, body.strip()):
            result['local_skill_reads_proven'].append(name)
    if len(runs) != len(prompts):
        result['execution'] = 'fail'
        result['acceptance'] = 'fail'
    if scenario in {'M06', 'M07'}:
        flow = observation_eval.check_flow(scenario, workspace, destination/'memory-after-1', traces,
                                           before, after_turns[0] if after_turns else {}, after)
        probe = {'status': flow['status'], 'memory_flow': flow}
    else:
        probe = (maintenance_check(scenario, workspace, before, after_turns[0] if after_turns else None)
            if scenario == 'M02' else functional_check(scenario, workspace, files.get('.aitasks/todo.md')))
    if scenario == 'R03':
        flow = repeat_memory_check(workspace, destination / 'memory-after-1', traces)
        probe['memory_flow'] = flow
        if flow['status'] == 'fail':
            probe['status'] = 'fail'
        elif flow['status'] == 'unverified' and probe['status'] != 'fail':
            probe['status'] = 'unverified'
    result.update({'scenario': scenario, 'suite': args.suite, 'variant': variant, 'repetition': repetition,
        'batch_id': batch['batch_id'] if batch else None,
        'dataset_split': ('holdout' if scenario in SELECTION_HOLDOUT else 'development') if args.suite == 'selection-v1' else None,
        'runs': runs, 'trace_summary': traces, 'contract_probe': probe})
    if result['contract_probe']['status'] == 'fail':
        result['acceptance'] = 'fail'
    dump(destination / 'result.json', result)
    return result

def prepare_output(output, suite):
    """Reject mixed suites before launching any workers, including legacy directories."""
    marker = output / 'suite.json'
    existing = {json.loads(path.read_text()).get('suite', 'legacy')
                for path in output.glob('*/*/predeclared.json')}
    existing.update(json.loads(path.read_text()).get('suite', 'legacy')
                    for path in output.glob('*/*/result.json'))
    if marker.exists():
        existing.add(json.loads(marker.read_text())['suite'])
    if existing - {suite}:
        raise ValueError(f'output belongs to {sorted(existing)}, cannot mix suite {suite}')
    output.mkdir(parents=True, exist_ok=True)
    if not marker.exists():
        dump(marker, {'suite': suite, 'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def runner_identity():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def runner_files():
    return {name: hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
            for name in ('behavior_eval.py', 'observation_eval.py')
            for path in [Path(__file__).with_name(name)]}


def cli_identity(executable):
    resolved = shutil.which(str(executable))
    if not resolved:
        raise ValueError(f'CLI executable not found: {executable}')
    path = Path(resolved).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def source_identity(source):
    source = Path(source)
    files = snapshot(source / 'skills')
    if not (source / 'skills').is_dir() or (source / 'skills').is_symlink() or any('symlink' in f for f in files.values()):
        raise ValueError(f'batch sources must be complete local files without symlinks: {source}')
    version = source / 'VERSION'
    if version.is_symlink():
        raise ValueError(f'batch VERSION must not be a symlink: {source}')
    return {'skills': files, 'version_sha256': hashlib.sha256(version.read_bytes()).hexdigest() if version.exists() else None}


def runtime_identity():
    # Store hashes, never credentials/config contents. Effective model/provider still need review.
    env = {k: v for k, v in os.environ.items() if k.startswith(('CODEX_', 'OPENAI_', 'AZURE_OPENAI_'))
           or k in {'PATH', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY'}}
    home = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
    configs = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
               for p in (home / 'config.toml', home / 'AGENTS.md', home / 'AGENTS.override.md')}
    return {'environment_sha256': digest(env), 'config_files': configs,
            'rules': snapshot(home / 'rules'), 'python': sys.version, 'platform': list(os.uname())[:3]}


def execution_identity(args):
    return {'runner_files': runner_files(), 'cli': cli_identity(args.codex), 'runtime': runtime_identity()}


def batch_execution_identity(batch):
    return {key: batch['identity'][key] for key in ('runner_files', 'cli', 'runtime')}


def execution_boundaries_match(instance, batch, result):
    """Use archived observations; later upgrades must not invalidate historical runs."""
    try:
        expected = batch_execution_identity(batch)
        runs = result.get('runs', [])
        return bool(runs) and all(
            json.loads((instance / f'execution-{boundary}-{turn}.json').read_text()) == expected
            for turn in range(1, len(runs) + 1) for boundary in ('before', 'after'))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def verify_batch_sources(output, batch, variant=None):
    for name in ([variant] if variant and variant != 'no-skill' else ('baseline', 'candidate')):
        if source_identity(output / '.sources' / name) != batch['identity']['sources'][name]:
            raise ValueError(f'frozen {name} source changed; use a new batch')


def read_batch(output):
    path = output / 'batch.json'
    if not path.exists():
        return None
    batch = json.loads(path.read_text())
    if (batch.get('schema_version') != 1 or not batch.get('batch_id')
            or digest(batch.get('identity')) != batch.get('identity_sha256')):
        raise ValueError('invalid batch manifest; use a new output directory')
    return batch


def prepare_batch(args):
    """Lock comparable conditions once; never promote historical evidence to a locked batch."""
    output = args.output
    batch = read_batch(output)
    if batch is None and output.exists() and any(output.iterdir()):
        raise ValueError('existing output has no locked batch identity; report it or use a new output directory')
    identity = {'suite': args.suite, 'runner_sha256': runner_identity(), 'runner_files': runner_files(),
        'sources': {name: source_identity(source) for name, source in
                    (('baseline', args.baseline), ('candidate', args.candidate))},
        'cli': cli_identity(args.codex), 'model': args.model, 'timeout': args.timeout,
        'jobs': args.jobs, 'external_skill_disables': sorted(str(p) for p in args.external_skills),
        'policy': 'workspace-write / approval never / ignore-user-config; no ignore-rules',
        'variants': ['baseline', 'candidate'] + (['no-skill'] if args.include_no_skill else []),
        'runtime': runtime_identity()}
    if batch is not None:
        if batch['identity'] != identity:
            changed = [key for key in identity if identity[key] != batch['identity'].get(key)]
            raise ValueError(f'batch conditions changed ({", ".join(changed)}); use a new output directory')
        verify_batch_sources(output, batch)
        return batch
    output.mkdir(parents=True, exist_ok=True)
    # An interrupted freeze is intentionally not reused. It cannot masquerade as a locked batch.
    sources = output / '.sources'
    sources.mkdir()
    for name, source in (('baseline', args.baseline), ('candidate', args.candidate)):
        freeze_source(source, sources / name)
        if source_identity(source) != identity['sources'][name] or source_identity(sources / name) != identity['sources'][name]:
            raise ValueError(f'{name} source changed while freezing; use a new output directory')
    batch = {'schema_version': 1, 'batch_id': uuid.uuid4().hex, 'identity': identity,
             'identity_sha256': digest(identity)}
    prepare_output(output, args.suite)
    dump(output / 'batch.json', batch)
    return batch


@contextmanager
def batch_run_lock(output):
    path = output / '.run.lock'
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ValueError('batch is already running or has an interrupted lock; preserve it and use a new output directory')
    try:
        with os.fdopen(descriptor, 'w') as handle:
            handle.write(str(os.getpid()))
        yield
    finally:
        path.unlink()


def register_batch_runs(output, batch, tasks):
    """Persist expected pair members before launch, including members clipped by max-runs."""
    path = output / 'planned-runs.json'
    planned = json.loads(path.read_text()) if path.exists() else []
    additions = {}
    suite = batch['identity']['suite']
    for _, variant, scenario, repetition in tasks:
        name = SUITES[suite][scenario][0]
        if (output / f'{scenario}-{name}' / f'{variant}-{repetition}').exists():
            raise ValueError(f'run already exists: {scenario} {variant} {repetition}; existing evidence is retained')
        for member in batch['identity']['variants']:
            relative = f'{scenario}-{name}/{member}-{repetition}'
            additions[relative] = {'path': relative, 'batch_id': batch['batch_id'], 'suite': suite,
                'scenario': scenario, 'variant': member, 'repetition': repetition,
                'dataset_split': ('holdout' if scenario in SELECTION_HOLDOUT else 'development') if suite == 'selection-v1' else None}
    combined = {item['path']: item for item in planned}
    combined.update(additions)
    dump(path, [combined[key] for key in sorted(combined)])

def required_machine_evidence_unverified(result):
    # A bounded source probe may need semantic/browser review. Missing
    # session identities, however, cannot be supplied by a review verdict.
    return (result.get('readonly_boundary') == 'unverified'
            or result.get('contract_probe', {}).get('required_evidence_unverified') is True
            or result.get('contract_probe', {}).get('memory_flow', {}).get('status') == 'unverified')


def independent_review(instance, result):
    """Validate separately authored judgments; never promote machine completion to a pass."""
    path = instance / 'review.json'
    if not path.exists():
        return {'status': 'pending'}
    try:
        review = json.loads(path.read_text())
        if review.get('schema_version') != 1:
            raise ValueError('review schema_version must be 1')
        reviewer = review['reviewer']
        if reviewer['kind'] not in {'agent', 'human'} or not isinstance(reviewer.get('id'), str) or not reviewer['id'].strip():
            raise ValueError('reviewer requires kind agent/human and a nonempty id')
        dimensions = review['dimensions']
        if set(dimensions) != set(REVIEW_DIMENSIONS):
            raise ValueError('review must include exactly the five declared dimensions')
        statuses = []
        for name, judgment in dimensions.items():
            status = judgment['status']
            if status not in {'pass', 'fail', 'unverified', 'not_applicable'}:
                raise ValueError(f'invalid review status for {name}')
            if status == 'not_applicable' and name in {'task_correctness', 'authorization', 'evaluation_validity'}:
                raise ValueError(f'{name} always requires a judgment')
            if not isinstance(judgment.get('reason'), str) or not judgment['reason'].strip():
                raise ValueError(f'{name} requires a reason')
            if not isinstance(judgment.get('evidence'), list) or not judgment['evidence']:
                raise ValueError(f'{name} requires evidence, including when unverified or not applicable')
            for evidence in judgment['evidence']:
                relative = Path(evidence['path'])
                evidence_path = (instance / relative).resolve()
                if relative.is_absolute() or not evidence_path.is_relative_to(instance.resolve()) or not evidence_path.is_file():
                    raise ValueError(f'{name}: evidence must name an existing file inside the instance')
                if 'line' in evidence:
                    line = evidence['line']
                    if type(line) is not int or line < 1 or line > len(evidence_path.read_text().splitlines()):
                        raise ValueError(f'{name}: evidence line is outside the file')
            statuses.append(status)
        machine_failed = (result.get('acceptance') == 'fail' or result.get('execution') == 'fail'
                          or result.get('readonly_boundary') == 'fail' or result.get('contract_probe', {}).get('status') == 'fail')
        machine_unverified = required_machine_evidence_unverified(result)
        status = ('fail' if machine_failed or 'fail' in statuses else
                  'unverified' if result.get('execution') != 'completed' or machine_unverified
                  or 'unverified' in statuses else 'pass')
        return {'status': status, 'reviewer': reviewer, 'dimensions': dimensions,
                'source': 'review.json', 'machine_failure_preserved': machine_failed,
                'machine_evidence_unverified': machine_unverified}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        return {'status': 'invalid', 'source': 'review.json', 'reason': str(error)}


def cost_metrics(result):
    def total(values):
        return sum(values) if values and all(type(v) in (int, float) and v >= 0 for v in values) else None
    traces = result.get('trace_summary', [])
    usage = [u for trace in traces for u in trace.get('usage', [])]
    metrics = {'seconds': total([run.get('seconds') for run in result.get('runs', [])]),
               'command_count': result.get('command_count')}
    for key in ('input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_output_tokens'):
        metrics[key] = total([u.get(key) for u in usage]) if traces and all(t.get('usage') for t in traces) else None
    return metrics


def pair_reports(results, batch, batch_status):
    grouped = {}
    for result in results:
        key = (result.get('batch_id'), result.get('suite', 'legacy'), result['scenario'],
               result['repetition'], result.get('dataset_split'))
        grouped.setdefault(key, {}).setdefault(result['variant'], []).append(result)
    pairs = []
    for key, members in sorted(grouped.items(), key=lambda item: tuple(str(x) for x in item[0])):
        def member(name):
            records = members.get(name, [])
            if not records:
                return {'execution': 'not_created', 'review': {'status': 'pending'}}
            if len(records) != 1:
                return {'execution': 'ambiguous', 'review': {'status': 'invalid'}}
            return records[0]
        sides = {name: member(name) for name in ('baseline', 'candidate')}
        reasons = []
        if batch_status != 'locked' or not batch or key[0] != batch['batch_id']:
            reasons.append('batch identity is not locked and comparable')
        for name, result in sides.items():
            if result['execution'] != 'completed':
                reasons.append(f'{name}: {result["execution"]}')
            if (result.get('acceptance') == 'fail' or result.get('readonly_boundary') == 'fail'
                    or result.get('contract_probe', {}).get('status') == 'fail'):
                reasons.append(f'{name}: machine failure')
            review = result.get('review', {})
            if required_machine_evidence_unverified(result) or review.get('machine_evidence_unverified'):
                reasons.append(f'{name}: required machine evidence is unverified')
            dimensions = review.get('dimensions', {}) if review.get('status') not in {'invalid', 'pending'} else {}
            for dimension in ('task_correctness', 'authorization', 'verification_accuracy', 'evaluation_validity'):
                allowed = {'pass', 'not_applicable'} if dimension == 'verification_accuracy' else {'pass'}
                if dimensions.get(dimension, {}).get('status') not in allowed:
                    reasons.append(f'{name}: {dimension} lacks a trusted pass')
            if not result.get('_batch_provenance'):
                reasons.append(f'{name}: instance provenance is not verified')
        comparison = {'status': 'ineligible' if reasons else 'eligible', 'reasons': reasons}
        if not reasons:
            metrics = {name: cost_metrics(result) for name, result in sides.items()}
            comparison.update(metrics=metrics, candidate_minus_baseline={name:
                metrics['candidate'][name] - value if value is not None and metrics['candidate'][name] is not None else None
                for name, value in metrics['baseline'].items()},
                interpretation='observed commands, elapsed seconds and CLI usage; not billed cost or proof of efficiency')
        pair = {'batch_id': key[0], 'suite': key[1], 'scenario': key[2], 'repetition': key[3],
                'dataset_split': key[4], 'members': {name: {'execution': r['execution'],
                'review_status': r['review']['status']} for name, r in sides.items()}, 'comparison': comparison}
        if 'no-skill' in members or (batch and key[0] == batch['batch_id'] and 'no-skill' in batch['identity']['variants']):
            control = member('no-skill')
            pair['no_skill'] = {'execution': control['execution'], 'review_status': control['review']['status'],
                               'metrics': cost_metrics(control)}
        pairs.append(pair)
    return pairs


def report(output):
    marker = output / 'suite.json'
    marker_suite = json.loads(marker.read_text())['suite'] if marker.exists() else None
    batch, batch_status, batch_error = None, 'legacy_unlocked', None
    try:
        batch = read_batch(output)
        if batch:
            verify_batch_sources(output, batch)
            batch_status = 'locked'
    except (ValueError, OSError, KeyError, TypeError) as error:
        batch_status, batch_error = 'invalid', str(error)
    plan_path = output / 'planned-runs.json'
    planned_runs = json.loads(plan_path.read_text()) if plan_path.exists() else []
    plan_by_path = {item['path']: item for item in planned_runs}
    results = []
    observed = set()
    for instance in sorted(path for path in output.glob('*/*') if path.is_dir()):
        result_path = instance / 'result.json'
        if result_path.exists():
            result = json.loads(result_path.read_text())
            result['review'] = independent_review(instance, result)
            result['_batch_provenance'] = False
            if batch_status == 'locked' and result.get('batch_id') == batch['batch_id']:
                declaration_path = instance / 'predeclared.json'
                declaration = json.loads(declaration_path.read_text()) if declaration_path.exists() else {}
                expected = installed_profile(batch['identity']['sources'].get(result['variant'], {'skills': {}})['skills'],
                                             result.get('suite', 'legacy'), result['scenario'])
                result['_batch_provenance'] = (declaration.get('batch_id') == batch['batch_id']
                    and declaration.get('batch_identity_sha256') == batch['identity_sha256']
                    and declaration.get('source_skills') == expected
                    and declaration.get('model') == (batch['identity']['model'] or 'CLI default: requires trace/config review')
                    and declaration.get('timeout') == batch['identity']['timeout']
                    and declaration.get('policy') == batch['identity']['policy']
                    and sorted(declaration.get('external_skill_disables', [])) == batch['identity']['external_skill_disables']
                    and execution_boundaries_match(instance, batch, result))
            results.append(result)
            observed.add(str(instance.relative_to(output)))
            continue
        if not re.fullmatch(r'(?:baseline|candidate|no-skill)-[0-9]+', instance.name):
            continue
        declaration_path = instance / 'predeclared.json'
        declaration = json.loads(declaration_path.read_text()) if declaration_path.exists() else {}
        declared = {**plan_by_path.get(str(instance.relative_to(output)), {}), **declaration}
        error_path = instance / 'runner-error.json'
        error = json.loads(error_path.read_text()) if error_path.exists() else None
        variant, repetition = instance.name.rsplit('-', 1)
        result = {'suite': declared.get('suite', marker_suite or 'legacy'),
            'batch_id': declared.get('batch_id', batch['batch_id'] if batch else None),
            'scenario': declared.get('scenario', instance.parent.name.split('-', 1)[0]),
            'dataset_split': declared.get('dataset_split'),
            'variant': variant, 'repetition': int(repetition),
            'execution': 'runner_error' if error is not None else 'incomplete',
            'target_skill_read_proven': None, 'readonly_boundary': 'unverified',
            'contract_probe': {'status': 'unverified'}, 'command_count': None,
            'runner_error': error}
        result['review'] = independent_review(instance, result)
        results.append(result)
        observed.add(str(instance.relative_to(output)))
    for planned in planned_runs:
        if planned['path'] not in observed:
            results.append({**planned, 'execution': 'not_created', 'target_skill_read_proven': None,
                'readonly_boundary': 'unverified', 'contract_probe': {'status': 'unverified'},
                'command_count': None, 'review': {'status': 'pending'}})
    suites = {r.get('suite', 'legacy') for r in results}
    if marker_suite:
        suites.add(marker_suite)
    if len(suites) > 1:
        raise ValueError(f'cannot aggregate different suites: {sorted(suites)}')
    pairs = pair_reports(results, batch, batch_status)
    summary = {'suite': next(iter(suites), None), 'scenario_runs': len(results), 'execution_completed': sum(r['execution'] == 'completed' for r in results),
        'batch': {'status': batch_status, 'batch_id': batch['batch_id'] if batch else None,
                  **({'reason': batch_error} if batch_error else {})},
        'pairs': pairs,
        'by_split': {split or 'unspecified': {'scenario_runs': sum(r.get('dataset_split') == split for r in results),
            'pairs': sum(p['dataset_split'] == split for p in pairs),
            'eligible_pairs': sum(p['dataset_split'] == split and p['comparison']['status'] == 'eligible' for p in pairs),
            'incomplete_pairs': sum(p['dataset_split'] == split and any(m['execution'] != 'completed' for m in p['members'].values()) for p in pairs)}
            for split in sorted({r.get('dataset_split') for r in results}, key=str)},
        'execution_not_created': sum(r['execution'] == 'not_created' for r in results),
        'execution_incomplete': sum(r['execution'] == 'incomplete' for r in results),
        'execution_runner_error': sum(r['execution'] == 'runner_error' for r in results),
        'target_read_proven': sum(r['target_skill_read_proven'] is True for r in results),
        'readonly_failures': sum(r['readonly_boundary'] == 'fail' for r in results),
        'contract_failures': sum(r['contract_probe']['status'] == 'fail' for r in results),
        'reviewed_outcomes': {kind: {status: sum(r['review'].get('reviewer', {}).get('kind') == kind
                                                and r['review']['status'] == status for r in results)
                                    for status in ('pass', 'fail', 'unverified')}
                             for kind in ('agent', 'human')},
        'reviews_pending': sum(r['review']['status'] == 'pending' for r in results),
        'reviews_invalid': sum(r['review']['status'] == 'invalid' for r in results),
        'behavior_acceptance': 'machine completion is not semantic acceptance; see separately attributed per-instance reviews',
        'runs': [{'suite': r.get('suite', 'legacy'), **{key: r[key] for key in ('scenario', 'variant', 'repetition', 'execution',
                 'target_skill_read_proven', 'readonly_boundary', 'contract_probe', 'command_count')},
                 'batch_id': r.get('batch_id'), 'dataset_split': r.get('dataset_split'), 'review': r['review'],
                 'local_skill_reads_proven': r.get('local_skill_reads_proven', []),
                 **({'runner_error': r['runner_error']} if r.get('runner_error') is not None else {})} for r in results]}
    dump(output / 'summary.json', summary)
    return summary

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='action', required=True)
    lister = subparsers.add_parser('list')
    lister.add_argument('--suite', choices=SUITES, default='legacy')
    lister.add_argument('--split', choices=('development', 'holdout', 'all'))
    reporter = subparsers.add_parser('report')
    reporter.add_argument('--output', required=True, type=Path)
    freezer = subparsers.add_parser('freeze', help='Copy all Skill resources, regardless of Git status, without overwriting.')
    freezer.add_argument('--source', type=Path, default=ROOT)
    freezer.add_argument('--output', required=True, type=Path)
    runner = subparsers.add_parser('run')
    runner.add_argument('--baseline', required=True, type=Path)
    runner.add_argument('--candidate', type=Path, default=ROOT)
    runner.add_argument('--output', required=True, type=Path)
    runner.add_argument('--suite', choices=SUITES, default='legacy')
    runner.add_argument('--scenarios')
    runner.add_argument('--split', choices=('development', 'holdout', 'all'), help='selection-v1 only; defaults to development')
    runner.add_argument('--include-no-skill', action='store_true', help='Add a third control without local Skills for natural task suites.')
    runner.add_argument('--repetitions', type=int, default=3)
    runner.add_argument('--timeout', type=int, default=180)
    runner.add_argument('--codex', default='codex')
    runner.add_argument('--model')
    runner.add_argument('--jobs', type=int, default=1, help='bounded concurrent independent scenario runs (1-4)')
    runner.add_argument('--max-runs', type=int, help='cap actual scenario runs without retrying failures')
    args = parser.parse_args()
    if args.action == 'list':
        try:
            selected = select_scenarios(args.suite, split=args.split)
        except ValueError as error:
            parser.error(str(error))
        print(json.dumps({key: SUITES[args.suite][key] for key in selected}, ensure_ascii=False, indent=2))
        return
    args.output = args.output.resolve()
    if args.action == 'freeze':
        freeze_source(args.source, args.output)
        print(args.output)
        return
    if args.action == 'report':
        print(json.dumps(report(args.output), ensure_ascii=False, indent=2))
        return
    try:
        selected = select_scenarios(args.suite, args.scenarios, args.split)
    except ValueError as error:
        parser.error(str(error))
    if args.include_no_skill and not supports_no_skill(args.suite, selected):
        parser.error('--include-no-skill requires natural task inputs without a pinned entry or maintenance rules')
    if not 1 <= args.jobs <= 4 or (args.max_runs is not None and args.max_runs < 1):
        parser.error('jobs must be 1-4 and max-runs must be positive')
    if args.repetitions < 1 or args.timeout < 1:
        parser.error('repetitions and timeout must be positive')
    for source in (args.baseline, args.candidate):
        if not (source / 'skills').is_dir():
            parser.error(f'missing skills directory: {source}')
    args.external_skills = discover_external_skills()
    try:
        args.batch = prepare_batch(args)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    args.baseline = args.output / '.sources/baseline'
    args.candidate = args.output / '.sources/candidate'
    args.codex = args.batch['identity']['cli']['path']
    tasks = []
    for repetition in range(1, args.repetitions + 1):
        variants = [('baseline', args.baseline), ('candidate', args.candidate)]
        if args.include_no_skill:
            variants.append(('no-skill', None))
        if repetition % 2 == 0:
            variants.reverse()
        for scenario in selected:
            for variant, source in variants:
                tasks.append((source.resolve() if source is not None else None, variant, scenario, repetition))
    if args.max_runs:
        tasks = tasks[:args.max_runs]
    try:
        with batch_run_lock(args.output):
            register_batch_runs(args.output, args.batch, tasks)
            execute_batch(args, tasks)
    except ValueError as error:
        parser.error(str(error))


def execute_batch(args, tasks):
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {}
        errors = []
        for source, variant, scenario, repetition in tasks:
            future = executor.submit(run_case, args, source, variant, scenario, repetition)
            futures[future] = (scenario, variant, repetition)
        for future in as_completed(futures):
            scenario, variant, repetition = futures[future]
            try:
                result = future.result()
                print(f'{scenario} {variant} {repetition}: {result["execution"]}', flush=True)
            except Exception as error:
                # Keep existing artifacts and make orchestration failure visible; do not retry.
                print(f'{scenario} {variant} {repetition}: runner error: {error}', file=sys.stderr, flush=True)
                errors.append(error)
            report(args.output)
        if errors:
            raise SystemExit(1)

if __name__ == '__main__':
    main()
