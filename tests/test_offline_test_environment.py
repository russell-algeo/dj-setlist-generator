"""Offline fixtures must not inherit live workflow dispatch identities."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

SENTINEL = '00000000-0000-4000-8000-000000000001'


class OfflineEnvironmentTests(unittest.TestCase):
    def test_nonempty_generation_is_test_scoped_and_runtime_fence_survives(self):
        root = Path(__file__).resolve().parents[1]
        code = r'''
import importlib.util, os, runpy, sys, unittest
from pathlib import Path
from unittest.mock import patch, Mock
root = Path(sys.argv[1]); sys.path.insert(0,str(root))
ambient = os.environ['SET_LIST_DISPATCH_GENERATION']
assert ambient
spec=importlib.util.spec_from_file_location('highkin_regression',root/'tests/test_yoon_highkin_source.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class ScopeProbe(unittest.TestCase):
    def runTest(self):
        self.assertEqual(os.environ.get('SET_LIST_DISPATCH_GENERATION'),'')
suite=unittest.TestSuite([ScopeProbe(),module.HighkinTests('test_real_claim_returns_legacy_or_ordered_highkin_locators')])
with patch.object(unittest.defaultTestLoader,'discover',return_value=suite):
    try:runpy.run_path(str(root/'scripts/test-recognition-offline.py'),run_name='__main__')
    except SystemExit as exc:assert exc.code in (0,False),exc.code
    else:raise AssertionError('runner must report its outcome')
assert os.environ['SET_LIST_DISPATCH_GENERATION']==ambient
from worker.jobs.yoon_queue import consume
try:consume(Mock(),{'source_metadata':{}},{},{'workflow_run_id':'1','run_attempt':'1'},ambient)
except RuntimeError as exc:assert str(exc)=='private_queue_reservation_required'
else:raise AssertionError('runtime dispatch fence was bypassed')
'''
        env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': '/tmp',
               'PYTHONDONTWRITEBYTECODE': '1', 'SET_LIST_DISPATCH_GENERATION': SENTINEL}
        if 'LD_LIBRARY_PATH' in os.environ:
            env['LD_LIBRARY_PATH'] = os.environ['LD_LIBRARY_PATH']
        result = subprocess.run([sys.executable, '-c', code, str(root)], cwd=root,
                                env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_workflow_limits_synthetic_generation_to_offline_job(self):
        root = Path(__file__).resolve().parents[1]
        text = (root/'.github/workflows/process-set.yml').read_text()
        offline = text.split('  private-offline-tests:', 1)[1].split('  private-prepare:', 1)[0]
        self.assertIn("SET_LIST_DISPATCH_GENERATION: '"+SENTINEL+"'", offline)
        self.assertIn('run: python scripts/test-recognition-offline.py', offline)
        self.assertNotIn('secrets.', offline)
        self.assertIn('SET_LIST_DISPATCH_GENERATION: ${{ github.event.inputs.dispatch_generation }}', text.split('jobs:',1)[0])
        # Only the global real identity and this offline-only synthetic override.
        self.assertEqual(text.count('SET_LIST_DISPATCH_GENERATION:'), 2)


if __name__ == '__main__':
    unittest.main()
