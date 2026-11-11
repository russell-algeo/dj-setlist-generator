"""Narrow passive guard API/routing and fail-closed retry regressions."""
import ast
from contextlib import contextmanager
import inspect
from pathlib import Path
import unittest
from unittest.mock import patch
from psycopg.errors import LockNotAvailable
from worker.recognition_transactions import RolledBackLockTimeout
from worker.jobs.yoon_resume_store import ResumeStore


class PassiveGuardTests(unittest.TestCase):
    def test_only_passive_method_requests_partial_state(self):
        tree=ast.parse(inspect.getsource(ResumeStore))
        callers=[]
        for method in tree.body[0].body:
            if not isinstance(method,ast.FunctionDef): continue
            for node in ast.walk(method):
                if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='locked':
                    if any(k.arg=='_owner_check' for k in node.keywords): callers.append(method.name)
        self.assertEqual(callers,['check_owner'])
        self.assertNotIn('save_state',inspect.getsource(ResumeStore.check_owner))
        self.assertNotIn('return state',inspect.getsource(ResumeStore.check_owner))
        self.assertIn('return state',inspect.getsource(ResumeStore.require_owner))

    def test_only_three_ignored_return_runner_sites_change(self):
        root=Path(__file__).resolve().parents[1]
        tree=ast.parse((root/'worker/jobs/yoon_resume.py').read_text())
        calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)]
        self.assertEqual(sum(n.func.attr=='check_owner' for n in calls),3)
        self.assertEqual(sum(n.func.attr=='require_owner' for n in calls),1)
        for n in ast.walk(tree):
            if isinstance(n,ast.Assign) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Attribute):
                self.assertNotEqual(n.value.func.attr,'check_owner')

    def test_retry_rechecks_owner_and_review_with_same_bound(self):
        with patch('worker.db.connect',side_effect=AssertionError('NO LIVE DB')):
            s=ResumeStore('12345678-1234-1234-1234-123456789012','1','1')
        calls=[]
        @contextmanager
        def locked(**kwargs):
            calls.append(kwargs)
            if len(calls)==1: raise RolledBackLockTimeout(LockNotAvailable('synthetic timeout'))
            raise RuntimeError('private_resume_owner_changed')
            yield
        with patch.object(s,'locked',locked),self.assertRaisesRegex(RuntimeError,'owner_changed'):
            s.check_owner()
        self.assertEqual(calls,[{'_owner_check':True}]*2)
        calls.clear()
        @contextmanager
        def always_timeout(**kwargs):
            calls.append(kwargs)
            raise RolledBackLockTimeout(LockNotAvailable('synthetic timeout'))
            yield
        with patch.object(s,'locked',always_timeout),self.assertRaises(LockNotAvailable):s.check_owner()
        self.assertEqual(len(calls),3)
