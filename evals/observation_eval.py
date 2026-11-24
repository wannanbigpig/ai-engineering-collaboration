"""Versioned observation fixtures and bounded artifact probes, independent of the Skill CLI."""
import hashlib
import json
import re


SCENARIOS = {
    'M06': ('observed-repeat', None,
            '分析 export.py 的 csv_value 为什么丢失日期偏移，给出证据和最小建议。不要修改代码；允许按项目规则维护观察和经验。',
            ['首次已确认原因只保存观察', '另一个独立任务确认同因后复用签名并沉淀一条经验', '不为维护记录创建 todo，不修改代码']),
    'M07': ('different-causes', None,
            '分析 export.py 的 csv_value 为什么丢失日期偏移，给出证据和最小建议。不要修改代码；允许按项目规则维护观察和经验。',
            ['症状相同仍核对实际原因', '上游解析问题不复用导出器移除时区的签名', '两个原因各为首次观察，不自动创建正式经验']),
    'M08': ('standalone-review', 'code-review',
            '使用 code-review 只读审查 retry.py 是否满足 CONTRACT.md，给出确定问题、证据和最小建议。不修改任何文件。',
            ['只安装审查 Skill 时使用有界文本回退', '核对当前契约及有效经验，不采用失效规则', '不虚构维护工具成功、不安装工具或写入记录']),
}
SECOND_PROMPT = '分析 export.py 新增的 json_value 为什么丢失日期偏移，给出证据和最小建议。这是另一项独立调查任务；不要修改代码，允许按项目规则维护观察和经验。'
FIRST_SOURCE = 'def csv_value(value):\n    return value.replace(tzinfo=None).isoformat()\n'
SECOND_SOURCE = {
    'M06': '\n\ndef json_value(value):\n    return value.replace(tzinfo=None).isoformat()\n',
    'M07': ('\n\nfrom datetime import datetime\n\ndef parse_import(raw):\n'
            '    return datetime.fromisoformat(raw.split("+")[0])\n\ndef json_value(raw):\n'
            '    return parse_import(raw).isoformat()\n'),
}


def fixture(scenario):
    files = {'.gitignore': '.aitasks/\n__pycache__/\n',
             '.aitasks/lessons.md': '# 经验\n\n', '.aitasks/todo.md': '# 任务\n\n'}
    if scenario in SECOND_SOURCE:
        files.update({'export.py': FIRST_SOURCE,
                      'CONTRACT.md': '日期导出为 ISO 8601，保留输入 datetime 或 ISO 字符串的原始时区偏移，不进行时区转换。\n'})
    elif scenario == 'M08':
        files.update({'retry.py': 'def attempts(retries):\n    return sum(1 for _ in range(retries))\n',
                      'CONTRACT.md': 'retries 表示首次之外的额外重试次数；retries=0 总尝试1次，retries=2 总尝试3次。\n',
                      '.aitasks/lessons.md': (
                          '# 经验\n\n<!-- aitasks:lesson id=old-retry status=superseded superseded_by=current-retry -->\n'
                          '## 旧重试约定\n- 正确做法：历史 retries 是总尝试次数，不额外加一。\n'
                          '<!-- aitasks:lesson id=current-retry status=active -->\n## 额外重试次数\n'
                          '- 适用范围：retry.attempts\n- 正确做法：按当前 CONTRACT.md 保留首次尝试。\n'
                          '<!-- aitasks:lesson id=unrelated status=active -->\n## 其他模块\n仅用于无关演示。\n')})
    else:
        raise ValueError(f'unknown observation scenario: {scenario}')
    return files


def add_second_task(workspace, scenario):
    with (workspace/'export.py').open('a', encoding='utf-8') as handle:
        handle.write(SECOND_SOURCE[scenario])


def observation_rows(path):
    if path.is_symlink():
        raise ValueError('observation state must be a regular file')
    state = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(state, dict) or state.get('version') != 1 or not isinstance(state.get('observations'), dict):
        raise ValueError('invalid observation state')
    rows = state['observations']
    for signature, row in rows.items():
        tasks = row['tasks']
        if (not isinstance(row['key'], str) or not row['key']
                or not isinstance(row['evidence'], str) or not row['evidence']
                or not (row['lesson_id'] is None or isinstance(row['lesson_id'], str))
                or not isinstance(tasks, list) or not 1 <= len(tasks) <= 2
                or any(not isinstance(task, str) or not task for task in tasks)
                or len(tasks) != len(set(tasks))):
            raise ValueError('invalid observation row or repeated task identity')
        if signature != hashlib.sha256(row['key'].encode()).hexdigest()[:32]:
            raise ValueError('observation signature does not match its key')
    return rows


def lesson_ids(text):
    """Count real fixture records, excluding marker examples inside ordinary fences."""
    found, fence = [], ''
    for line in text.splitlines():
        match = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if match:
            token = match[1]
            if not fence:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not match[2].strip():
                fence = ''
        elif not fence:
            marker = re.fullmatch(r'<!-- aitasks:lesson ([^\r\n]+) -->', line)
            if marker:
                fields = dict(part.split('=', 1) for part in marker[1].split())
                found.append(fields['id'])
    return found


def check_repeated_observation(first, last, first_lessons, last_lessons):
    if len(first) != 1 or first.keys() != last.keys():
        raise ValueError('expected one reused observation signature across independent sessions')
    signature, original = next(iter(first.items()))
    repeated = last[signature]
    if len(original['tasks']) != 1 or original['lesson_id'] is not None or lesson_ids(first_lessons):
        raise ValueError('first task must only observe without a formal lesson')
    if (len(repeated['tasks']) != 2 or repeated['tasks'][:1] != original['tasks']
            or repeated['key'] != original['key'] or not repeated['lesson_id']):
        raise ValueError('second task must preserve the first observation and promote a confirmed repeat')
    if lesson_ids(last_lessons) != [repeated['lesson_id']]:
        raise ValueError('expected exactly one formal lesson linked to the original signature')


def check_independent_sessions(traces, coverage):
    identities = [trace.get('thread_id') for trace in traces]
    if len(identities) != 2 or not all(identities):
        return {'status': 'unverified', 'reason': 'independent session identities missing',
                'required_evidence_unverified': True,
                'coverage': 'persisted flow only; fresh threads and lesson quality require trace review'}
    if len(set(identities)) != 2:
        raise ValueError('tasks reused the same CLI session')
    return {'status': 'pass', 'coverage': coverage}


def check_flow(scenario, workspace, first_memory, traces, before, after_first, after):
    """Verify persistence and write boundaries; semantic cause/lesson quality needs separate review."""
    try:
        initial = fixture(scenario)
        first = observation_rows(first_memory/'.observations.json')
        last = observation_rows(workspace/'.aitasks/.observations.json')
        first_lessons = (first_memory/'lessons.md').read_text()
        if (first_lessons != initial['.aitasks/lessons.md']
                or (first_memory/'todo.md').read_text() != initial['.aitasks/todo.md']):
            raise ValueError('first task wrote a formal lesson or todo')
        first_allowed = {'.aitasks/.observations.json', '.aitasks/.maintenance.lock.guard'}
        if any(before.get(path) != after_first.get(path) for path in before.keys() | after_first.keys()
               if not path.startswith('.git/') and path not in first_allowed):
            raise ValueError('first task changed a file outside its observation boundary')
        final_allowed = first_allowed | {'.aitasks/lessons.md', '.aitasks/.maintenance.json', 'export.py'}
        if any(before.get(path) != after.get(path) for path in before.keys() | after.keys()
               if not path.startswith('.git/') and path not in final_allowed):
            raise ValueError('unrelated persistent file change')
        if (workspace/'export.py').read_bytes() != (FIRST_SOURCE + SECOND_SOURCE[scenario]).encode('utf-8'):
            raise ValueError('analysis task changed code')
        if after['export.py']['mode'] != before['export.py']['mode']:
            raise ValueError('analysis task changed code permissions')
        lessons = (workspace/'.aitasks/lessons.md').read_text()
        if scenario == 'M06':
            check_repeated_observation(first, last, first_lessons, lessons)
        elif (len(first) != 1 or len(last) != 2
              or any(last.get(signature) != row for signature, row in first.items())
              or any(len(row['tasks']) != 1 or row['lesson_id'] is not None for row in last.values())
              or len({row['tasks'][0] for row in last.values()}) != 2
              or lessons != initial['.aitasks/lessons.md']):
            raise ValueError('different causes must remain two first observations without a lesson')
        return check_independent_sessions(
            traces, 'bounded artifacts and boundaries; semantic cause and lesson quality require review')
    except (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration) as error:
        return {'status': 'fail', 'reason': str(error)}
