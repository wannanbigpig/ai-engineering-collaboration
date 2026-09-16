#!/usr/bin/env python3
"""Reproducible Codex CLI behavior probes; semantic judgments remain manual."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
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
SUITES = {'legacy': SCENARIOS, 'review-v2': REVIEW_SCENARIOS, 'natural-v2': NATURAL_SCENARIOS, 'boundary-v3': BOUNDARY_SCENARIOS, 'precision-v4': PRECISION_SCENARIOS, 'precision-v5': PRECISION_V5_SCENARIOS}

def is_readonly(scenario):
    return scenario in READONLY or scenario in {'13', '14', '15', '16', '17', '18', 'N02', 'N03', 'N05', '19', '20', '21', '22', '23', '24', '25', '26', '27', '28'}

def fixture_rules(entry, suite):
    rules = '使用中文。只执行当前用户授权范围。\n'
    if suite == 'legacy':
        return rules + ('本次评测使用本项目 .agents/skills/ 中的技能；同名技能以这里为准。\n'
            f'本次入口是 {entry}，先读取 .agents/skills/{entry}/SKILL.md，再按实际需要选择下游技能。\n'
            '本项目可用验证命令为 python3 -B -m unittest discover -v。\n')
    if entry and suite in {'review-v2', 'boundary-v3', 'precision-v4', 'precision-v5'}:
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

def fixture_v2(scenario):
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

def functional_check(scenario, workspace):
    """Independent contract probes; final workspace snapshot is taken BEFORE these run."""
    if scenario == 'N01':
        try:
            return {'status': 'pass' if (workspace / 'README.md').read_text() == 'Welcome\n' else 'fail'}
        except (OSError, UnicodeError) as error:
            return {'status': 'fail', 'reason': f'cannot read expected README.md: {error}'}
    scenario = {'N04': '02', 'N06': '08'}.get(scenario, scenario)
    expressions = {
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

def score(scenario, before, after, traces, runs, skill_text, entry, external_paths=(), suite='legacy'):
    commands = [command for trace in traces for command in trace['commands']]
    # Full observed output is required. Merely mentioning a path/version is not proof of loading.
    loaded = None if entry is None else any(command.get('exit_code') == 0 and
        f'{entry}/SKILL.md' in (command.get('command') or '') and
        skill_text.strip() in (command.get('aggregated_output') or '') for command in commands)
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
        'dimensions': {name: {'status': 'pending', 'evidence': []} for name in
                       ('task_correctness', 'authorization', 'verification_accuracy', 'process_efficiency', 'evaluation_validity')},
        'manual_review': {'status': 'pending', 'criteria': SUITES[suite][scenario][3],
            'required': ['复核隐式用户级规则/Skill污染与实际模型设置', '复核正确性、必要决策、授权边界和虚假完成声明',
                         '按相关输入是否改变判断重复验证；逐项记录无关读取和额外确认']},
        'acceptance': 'fail' if failure or (is_readonly(scenario) and content_changed) else 'unverified', 'command_count': len(commands)}

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
    if scenario != '04':
        command += ['--ephemeral']
    command += ['--output-last-message', str(output), '-']
    return command

def isolated_workspace():
    # Its only ancestor fixture directory contains no prompts, grader rules or other runs.
    workspace = Path(tempfile.mkdtemp(prefix='skill-behavior-')) / 'workspace'
    workspace.mkdir()
    return workspace

def run_case(args, source, variant, scenario, repetition):
    name, entry, prompt, criteria = SUITES[args.suite][scenario]
    destination = args.output / f'{scenario}-{name}' / f'{variant}-{repetition}'
    destination.mkdir(parents=True, exist_ok=False)  # Retain failed attempts; never overwrite.
    workspace = isolated_workspace()
    files = fixture(scenario, args.suite)
    for name, content in files.items():
        path = workspace / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    skill_root = workspace / '.agents/skills'
    shutil.copytree(source / 'skills', skill_root)
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
    traces, runs = [], []
    prompts = [prompt]
    if scenario == '04':
        prompts += ['现在核对交付证据并给我最终结果；文件及运行条件均未改变。',
                    '我刚把 app.py 的实现恢复为直接返回输入，请修复负数行为并核对交付证据。']
    dump(destination / 'predeclared.json', {'scenario': scenario, 'suite': args.suite, 'prompts': prompts,
        'criteria': criteria, 'workspace': str(workspace), 'fixture_commit': fixture_commit, 'source': str(source), 'source_skills': snapshot(skill_root),
        'model': args.model or 'CLI default: requires trace/config review', 'timeout': args.timeout,
        'policy': 'workspace-write / approval never / ignore-user-config; no ignore-rules',
        'external_skill_disables': [str(path) for path in args.external_skills],
        'limitations': ['External skill folders discovered in standard roots are disabled by per-command config; plugins and user rules still need review.',
                       'Natural mode has no pinned entry; inferred selection and invisible loads require manual review.' if entry is None else 'Entry is pinned by fixture AGENTS; this is not a trigger benchmark.',
                       'Scenario 11 has no CodeGraph mock or live server: CodeGraph tool selection remains unverified.']})
    thread_id = None
    for turn, prompt in enumerate(prompts, 1):
        if turn == 3:
            (workspace / 'app.py').write_text('def clamp(value):\n    return value\n')
        (destination / f'prompt-{turn}.txt').write_text(prompt)
        trace_path = destination / f'trace-{turn}.jsonl'
        command = command_for(args, workspace, destination / f'final-{turn}.txt', scenario, thread_id)
        dump(destination / f'command-{turn}.json', command)
        dump(destination / f'before-{turn}.json', snapshot(workspace))
        run = run_process(command, workspace, prompt, trace_path,
                          destination / f'stderr-{turn}.log', args.timeout)
        trace = parse_trace(trace_path)
        command_evidence(trace, destination / f'commands-{turn}')
        runs.append(run)
        traces.append(trace)
        dump(destination / f'after-{turn}.json', snapshot(workspace))
        if run.get('exit_code') != 0 or run.get('timed_out') or not trace['completed_turns']:
            break
        thread_id = trace['thread_id'] or thread_id
        if scenario == '04' and not thread_id:
            break
    after = snapshot(workspace)
    dump(destination / 'after.json', after)
    shutil.copytree(workspace, destination / 'workspace', symlinks=True)
    result = score(scenario, before, after, traces, runs,
        (source / 'skills' / entry / 'SKILL.md').read_text() if entry else '', entry, args.external_skills, args.suite)
    # Record observable full loads for every local Skill; missing proof is not proof of no load.
    result['local_skill_reads_proven'] = []
    for path in sorted((source / 'skills').glob('*/SKILL.md')):
        body = path.read_text().strip()
        if any(c.get('exit_code') == 0 and f'{path.parent.name}/SKILL.md' in (c.get('command') or '')
               and body in (c.get('aggregated_output') or '') for t in traces for c in t['commands']):
            result['local_skill_reads_proven'].append(path.parent.name)
    if len(runs) != len(prompts):
        result['execution'] = 'fail'
    result.update({'scenario': scenario, 'suite': args.suite, 'variant': variant, 'repetition': repetition,
        'runs': runs, 'trace_summary': traces, 'contract_probe': functional_check(scenario, workspace)})
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

def report(output):
    results = [json.loads(path.read_text()) for path in sorted(output.glob('*/*/result.json'))]
    suites = {r.get('suite', 'legacy') for r in results}
    if len(suites) > 1:
        raise ValueError(f'cannot aggregate different suites: {sorted(suites)}')
    summary = {'suite': next(iter(suites), None), 'scenario_runs': len(results), 'execution_completed': sum(r['execution'] == 'completed' for r in results),
        'target_read_proven': sum(r['target_skill_read_proven'] is True for r in results),
        'readonly_failures': sum(r['readonly_boundary'] == 'fail' for r in results),
        'contract_failures': sum(r['contract_probe']['status'] == 'fail' for r in results),
        'behavior_acceptance': 'unverified until manual judgments and isolation/model review are supplied',
        'runs': [{'suite': r.get('suite', 'legacy'), **{key: r[key] for key in ('scenario', 'variant', 'repetition', 'execution',
                 'target_skill_read_proven', 'readonly_boundary', 'contract_probe', 'command_count')}} for r in results]}
    dump(output / 'summary.json', summary)
    return summary

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='action', required=True)
    lister = subparsers.add_parser('list')
    lister.add_argument('--suite', choices=SUITES, default='legacy')
    reporter = subparsers.add_parser('report')
    reporter.add_argument('--output', required=True, type=Path)
    runner = subparsers.add_parser('run')
    runner.add_argument('--baseline', required=True, type=Path)
    runner.add_argument('--candidate', type=Path, default=ROOT)
    runner.add_argument('--output', required=True, type=Path)
    runner.add_argument('--suite', choices=SUITES, default='legacy')
    runner.add_argument('--scenarios')
    runner.add_argument('--repetitions', type=int, default=3)
    runner.add_argument('--timeout', type=int, default=180)
    runner.add_argument('--codex', default='codex')
    runner.add_argument('--model')
    runner.add_argument('--jobs', type=int, default=1, help='bounded concurrent independent scenario runs (1-4)')
    runner.add_argument('--max-runs', type=int, help='cap actual scenario runs without retrying failures')
    args = parser.parse_args()
    if args.action == 'list':
        print(json.dumps(SUITES[args.suite], ensure_ascii=False, indent=2))
        return
    args.output = args.output.resolve()
    if args.action == 'report':
        print(json.dumps(report(args.output), ensure_ascii=False, indent=2))
        return
    selected = args.scenarios.split(',') if args.scenarios else list(SUITES[args.suite])
    if any(item not in SUITES[args.suite] for item in selected) or len(set(selected)) != len(selected):
        parser.error('scenarios must be unique IDs in the selected suite')
    if not 1 <= args.jobs <= 4 or (args.max_runs is not None and args.max_runs < 1):
        parser.error('jobs must be 1-4 and max-runs must be positive')
    if args.repetitions < 1 or args.timeout < 1:
        parser.error('repetitions and timeout must be positive')
    for source in (args.baseline, args.candidate):
        if not (source / 'skills').is_dir():
            parser.error(f'missing skills directory: {source}')
    roots = [Path.home() / '.agents/skills', Path.home() / '.codex/skills', Path('/etc/codex/skills')]
    args.external_skills = sorted({path.parent.absolute() for root in roots if root.exists()
                                  for path in root.rglob('SKILL.md')})
    try:
        prepare_output(args.output, args.suite)
    except ValueError as error:
        parser.error(str(error))
    tasks = []
    for repetition in range(1, args.repetitions + 1):
        variants = [('baseline', args.baseline), ('candidate', args.candidate)]
        if repetition % 2 == 0:
            variants.reverse()
        for scenario in selected:
            for variant, source in variants:
                tasks.append((source.resolve(), variant, scenario, repetition))
    if args.max_runs:
        tasks = tasks[:args.max_runs]
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {}
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
                raise
            report(args.output)

if __name__ == '__main__':
    main()
