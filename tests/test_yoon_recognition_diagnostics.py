import asyncio
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from worker.jobs import yoon_recognition_diagnostics as diag
from worker.jobs.yoon_resume import recognize_resumable
from worker.jobs.yoon_resume_store import QueuePause
from test_yoon_resume_runner import FakeStore, Session

SECRET = 'SENSITIVE_TRACK_SOURCE_AUTH_CREDENTIAL_PAYLOAD'


class DiagnosticTests(unittest.TestCase):
    def test_allowlists_all_classes_and_sqlstates(self):
        for name in diag._CLASSES:
            error = type(name, (Exception,), {})(SECRET)
            for state in diag._SQLSTATES:
                error.sqlstate = state
                line = diag.diagnostic_line('finish', error)
                self.assertEqual(line, f'private_recognition phase=finish exception={name} sqlstate={state}\n')
                self.assertNotIn(SECRET, line)

    def test_untrusted_names_phase_sqlstate_and_message_never_escape(self):
        error = type(SECRET, (Exception,), {'sqlstate': SECRET})(SECRET)
        error.__cause__ = RuntimeError(SECRET)
        self.assertEqual(diag.diagnostic_line(SECRET, error),
            'private_recognition phase=entry exception=OtherError sqlstate=none\n')
        class HostileError(Exception):
            @property
            def sqlstate(self): raise RuntimeError(SECRET)
            def __str__(self): raise AssertionError('must not format')
        self.assertEqual(diag.diagnostic_line('finish', HostileError()),
            'private_recognition phase=finish exception=OtherError sqlstate=none\n')

    def test_phase_keeps_exact_exception_and_does_not_report_pause(self):
        with patch.object(diag, 'report') as report:
            error = ValueError(SECRET)
            with self.assertRaises(ValueError) as caught:
                with diag.phase('finish'): raise error
            self.assertIs(caught.exception, error)
            report.assert_called_once_with('finish', error)
            report.reset_mock()
            with self.assertRaises(QueuePause):
                with diag.phase('reserve'): raise QueuePause(SECRET)
            report.assert_not_called()

    def test_sink_failures_and_output_limit_do_not_raise(self):
        with patch.object(diag, '_fd', 99), patch.object(diag, '_emitted', 0), patch.object(diag.os, 'write', side_effect=OSError(SECRET)):
            diag.report('finish', RuntimeError(SECRET))
        with patch.object(diag, '_fd', 99), patch.object(diag, '_emitted', 0), patch.object(diag.os, 'write') as write:
            for _ in range(100): diag.report('finish', RuntimeError(SECRET))
            self.assertEqual(write.call_count, 32)

    def test_entry_suppresses_raw_stdout_stderr_and_traceback(self):
        code = '''
import os, sys, types
from worker.jobs import yoon_recognition_diagnostics as d
m=types.ModuleType('worker.jobs.yoon_once')
def main():
    os.write(1, b'SENSITIVE_TRACK_SOURCE_AUTH_CREDENTIAL_PAYLOAD')
    os.write(2, b'SENSITIVE_TRACK_SOURCE_AUTH_CREDENTIAL_PAYLOAD')
    raise ValueError('SENSITIVE_TRACK_SOURCE_AUTH_CREDENTIAL_PAYLOAD')
m.main=main
sys.modules[m.__name__]=m
sys.argv=['diagnostics','recognize']
raise SystemExit(d.run())
'''
        for operation in ('recognize', 'prepare', 'release'):
            with self.subTest(operation=operation):
                result = subprocess.run([sys.executable, '-c', code.replace("'recognize'", repr(operation))], capture_output=True)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, b'')
                from worker.jobs.yoon_db_accounting import Meter
                self.assertEqual(result.stderr, Meter().line().encode('ascii')
                    + b'private_recognition phase=entry exception=ValueError sqlstate=none\n')

    def test_entry_bootstrap_and_close_fail_without_traceback(self):
        for operation in ('dup', 'dup2', 'close'):
            with self.subTest(operation=operation):
                code = """
import sys, types
from unittest.mock import patch
from worker.jobs import yoon_recognition_diagnostics as d
m=types.ModuleType('worker.jobs.yoon_once'); m.main=lambda: 0
sys.modules[m.__name__]=m
sys.argv=['diagnostics','recognize']
with patch.object(d.os, OPERATION, side_effect=OSError('SENSITIVE_TRACK_SOURCE_AUTH_CREDENTIAL_PAYLOAD')):
    result=d.run()
raise SystemExit(result)
""".replace('OPERATION', repr(operation))
                result = subprocess.run([sys.executable, '-c', code], capture_output=True)
                self.assertEqual(result.returncode, 0 if operation == 'close' else 1)
                self.assertNotIn(SECRET.encode(), result.stdout + result.stderr)
                self.assertNotIn(b'Traceback', result.stderr)

    def test_cancellation_preserves_control_flow(self):
        with patch.object(diag, 'report') as report:
            with self.assertRaises(asyncio.CancelledError):
                with diag.phase('batch'): raise asyncio.CancelledError()
            report.assert_not_called()

    def test_workflow_exposes_only_sanitized_recognition_entry(self):
        workflow = Path('.github/workflows/process-set.yml').read_text()
        self.assertIn('python -m worker.jobs.yoon_recognition_diagnostics recognize', workflow)
        self.assertIn('python -m worker.jobs.yoon_recognition_diagnostics prepare', workflow)
        self.assertIn('python -m worker.jobs.yoon_recognition_diagnostics release', workflow)
        self.assertNotIn('python -m worker.jobs.yoon_once release', workflow)


class AdapterTests(unittest.TestCase):
    def run_failure(self, target):
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory)/'input'; audio.write_bytes(b'synthetic')
            store = FakeStore(hashlib.sha256(b'synthetic').hexdigest())
            error = RuntimeError(SECRET)
            if target in ('require_owner', 'clock_state', 'next_windows', 'reserve', 'finish'):
                setattr(store, target, lambda *args: (_ for _ in ()).throw(error))
            async def extract(_self, _audio, start, end, executor):
                if target == 'extract': raise error
                return [dict(index=start, timestamp=start*15, file=Path(directory)/'segment')]
            class FailingSession(Session):
                async def recognize_batch(self, *args, **kwargs):
                    if target == 'batch': raise error
                    return await super().recognize_batch(*args, **kwargs)
                async def close(self):
                    if target == 'close': raise error
                    await super().close()
            with patch('socket.socket', side_effect=AssertionError('network forbidden')), \
                 patch('track_recognizer.TrackRecognizer', FailingSession), \
                 patch('audio_segmenter.AudioSegmenter.create_segments_batch', extract), \
                 patch('audio_segmenter.AudioSegmenter.get_audio_duration_ffprobe', return_value=7200), \
                 patch.object(diag, 'report') as report:
                # A standard asyncio loop uses a local socketpair, so provide the
                # loop before network denial and use it without new loop creation.
                with self.assertRaises(RuntimeError) as caught:
                    self.loop.run_until_complete(recognize_resumable(store, audio))
                self.assertIs(caught.exception, error)
                return [call.args[0] for call in report.call_args_list]

    def setUp(self): self.loop = asyncio.new_event_loop()
    def tearDown(self): self.loop.close()

    def test_adapter_failure_phase_coverage(self):
        cases = {'require_owner':'owner', 'clock_state':'clock', 'next_windows':'select_windows',
                 'reserve':'reserve', 'finish':'finish', 'extract':'extract', 'batch':'batch', 'close':'close'}
        for target, expected in cases.items():
            with self.subTest(target=target):
                self.assertIn(expected, self.run_failure(target))

    def test_shared_engine_swallowed_finish_error_still_reports_without_network(self):
        from track_recognizer import TrackRecognizer
        engine = TrackRecognizer(quiet=True)
        error = RuntimeError(SECRET)
        def finish(*args):
            with diag.phase('finish'): raise error
        async def synthetic(segment):
            finish()
        engine.recognize_segment_with_backoff = synthetic
        with patch.object(diag, 'report') as report, patch('socket.socket', side_effect=AssertionError('network forbidden')):
            rows = self.loop.run_until_complete(engine.recognize_batch(
                [dict(index=0, timestamp=0, file=Path('synthetic'))], cleanup_files=False))
            self.assertEqual(len(rows), 1)
            self.assertFalse(rows[0].is_valid)
            report.assert_called_once_with('finish', error)
        self.loop.run_until_complete(engine.close())
