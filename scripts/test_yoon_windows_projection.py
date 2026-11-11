"""Synthetic full-query projection oracle; never connects to a live service."""
import ast
from contextlib import contextmanager
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from worker.jobs.yoon_resume_store import ResumeStore

ORIGINAL_SQL = '''SELECT l.id,l.segment_start_index AS segment_index,h.raw_data
                FROM ops.set_run_leases l LEFT JOIN ops.segment_hits h
                ON h.set_run_id=l.set_run_id AND h.segment_index=l.segment_start_index
                WHERE l.set_run_id=%s AND l.status='pending'
                AND mod(l.segment_start_index / %s, %s)=%s
                AND coalesce(h.raw_data->'private_jackson_v2'->>'valid','false')<>'true'
                ORDER BY l.segment_start_index LIMIT %s FOR UPDATE OF l SKIP LOCKED'''


def current_sql():
    tree = ast.parse(Path(sys.modules[ResumeStore.__module__].__file__).read_text())
    method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'next_windows')
    return next(ast.literal_eval(node.args[0]) for node in ast.walk(method)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'execute')


def fixtures():
    values = [None, False, True, 0, 1, -1, 1.25, '', 'bad', 'private_jackson_v2',
              [], [None], ['private_jackson_v2'], {}, {'unrelated': 'value'}]
    due_values = values + [3600, 3600.5, 10**15, {'next_allowed_at': 3600},
                           ['next_allowed_at'], {'payload': ['synthetic'] * 8}]
    rows = []
    def add(label, raw, **extra):
        rows.append(dict(label=label, id=str(uuid.uuid5(uuid.NAMESPACE_URL, 'window-' + label)),
                         raw=raw, **extra))
    add('sql-null', None, sql_null=True)
    add('no-hit-left-join', None, no_hit=True)
    for index, value in enumerate(values):
        add(f'root-{index}', value)
        add(f'nested-{index}', {'unrelated': 'synthetic', 'private_jackson_v2': value})
    add('missing-child', {'unrelated': 'synthetic' * 1024})
    add('missing-due', {'private_jackson_v2': {'attempts': ['synthetic'] * 1024}})
    for index, due in enumerate(due_values):
        for valid in (None, False, True, 'true', 'false', 0, [], {}):
            add(f'due-{index}-valid-{json.dumps(valid)}', {'private_jackson_v2': {
                'next_allowed_at': due, 'valid': valid, 'attempts': ['synthetic'] * 32,
                'response': {'private': 'synthetic' * 16}}, 'other': 'synthetic' * 16})
    add('large-valid-shape', {'private_jackson_v2': {'next_allowed_at': 7200,
        'valid': False, 'in_flight': False, 'attempts': [{'state': 'finished',
        'diagnostic': {'http_status': 429}, 'padding': 'synthetic' * 100}] * 512,
        'response': {'payload': 'synthetic' * 10000}}, 'unrelated': 'synthetic' * 10000})
    return rows


def outcome(rows, state, now, *, slot=0, slots=1, size=10, limit=10):
    calls = []
    cursor = SimpleNamespace(execute=lambda sql, params: calls.append((sql, params)), fetchall=lambda: rows)
    @contextmanager
    def locked():
        yield cursor, {'db_now': now}, {**state, 'scheduler_plan': {'slot_count': slots, 'lease_size': size}}
    store = object.__new__(ResumeStore)
    store.run_id = '00000000-0000-4000-8000-000000000001'
    store.locked = locked
    try:
        candidates, wait = store.next_windows(slot, limit)
        assert all(set(candidate) == {'id', 'segment_index', 'raw_data'} for candidate in candidates)
        result = ['returned', [(row['id'], row['segment_index']) for row in candidates], wait]
    except Exception as error:
        result = ['raised', type(error).__name__, str(error)]
    return result, calls


def compare(data):
    checks = 0
    states = [{}]
    states += [{'next_allowed_at': value} for value in (None, False, True, 0, -1, 100, 7200,
                                                     7200.5, '', 'bad', [], [1], {}, {'x': 1})]
    clocks = [0, 4000, 8000, -1, None, 'bad']
    for case in data['cases']:
        old, new = case['old'], case['new']
        assert [(r['id'], r['segment_index']) for r in old] == [(r['id'], r['segment_index']) for r in new], case['label']
        checks += 1
        for state in states:
            for clock in clocks:
                old_result, old_calls = outcome(old, state, clock)
                new_result, new_calls = outcome(new, state, clock)
                assert old_result == new_result, (case['label'], state, clock, old_result, new_result)
                assert old_calls == new_calls
                checks += 2
    for case in data['ordering']:
        assert case['old'] == case['new'], case
        checks += 1
    return dict(status='passed', checks=checks, fixtures=len(data['cases']),
                ordering_cases=len(data['ordering']), sizes=data['sizes'])


if __name__ == '__main__':
    if sys.argv[1] == 'input':
        new_sql = current_sql()
        assert new_sql.split('FROM ops.set_run_leases', 1)[1] == ORIGINAL_SQL.split('FROM ops.set_run_leases', 1)[1]
        print(json.dumps(dict(old_sql=ORIGINAL_SQL, new_sql=new_sql, fixtures=fixtures())))
    else:
        print(json.dumps(compare(json.load(sys.stdin))))
