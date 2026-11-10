"""Finalization must work with the private-release job's base-only install."""
import os
from pathlib import Path
import subprocess
import sys
import unittest


class ReleaseDependenciesTests(unittest.TestCase):
    def test_base_only_import_and_complete_saved_responses(self):
        code = r'''
import contextlib, importlib.abc, io, sys
class BaseOnly(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'aiohttp','aiohttp_retry','shazamio','shazamio_core'}:
            raise ModuleNotFoundError('recognition-only dependency unavailable: '+fullname)
sys.meta_path.insert(0, BaseOnly())
import worker.jobs.yoon_once
from worker.jobs.yoon_resume_store import ResumeStore
class Cursor:
    def execute(self, sql, params): pass
    def fetchall(self):
        return [dict(segment_index=i,raw_data={'private_jackson_v2':dict(
            valid=True,in_flight=False,response=dict(timestamp=i*15,
            track_title=None,artist=None,shazam_track_id=None,
            raw_data={'matches':[]},recognized=False,segment_index=i,http_status=200))})
            for i in range(479)]
store=object.__new__(ResumeStore);store.run_id='synthetic-private-run'
saved=[];store.save_state=lambda cur,state,status:saved.append((dict(state),status))
with contextlib.redirect_stdout(io.StringIO()):
    store.complete_locked(Cursor(),{})
assert len(saved)==1
assert saved[0][1]=='private_resume_complete'
assert saved[0][0]['valid_responses']==479
assert saved[0][0]['status']=='complete'
assert saved[0][0]['clustered_setlist']
'''
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, '-c', code], cwd=root,
            env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),
                 'PYTHONDONTWRITEBYTECODE':'1'}, capture_output=True, text=True)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__ == '__main__':
    unittest.main()
