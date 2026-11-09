"""Offline shared transport and CLI resume regressions. No provider/DB calls."""
import asyncio
import importlib
import sys
from contextlib import ExitStack, redirect_stdout
from dataclasses import asdict
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from recognition_transport import (SingleAttemptHTTP, ProviderHTTPError, RequestBudgetExceeded, RequestAuthorizationError,
                                   classify_error, retry_after)
from track_recognizer import TrackRecognizer, RecognitionIncomplete
from worker.pipeline.models import Recognition
from config import Config


class Response:
    def __init__(self, status=200, headers=None, value=None):
        self.status, self.headers = status, headers or {}
        self.value = {'matches': []} if value is None else value
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def json(self): return self.value


class HTTP:
    def __init__(self, responses): self.responses, self.calls = list(responses), []
    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.responses.pop(0)
    async def close(self): pass


def segment(i=0):
    return {'file': Path('/tmp/synthetic-not-created'), 'index': i, 'timestamp': i * 15}


def valid(i):
    return Recognition(i * 15, None, None, None, {'matches': []}, False, i)


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stubs = {}
        for name in ('aiohttp_retry', 'shazamio'):
            if name in sys.modules and not getattr(sys.modules[name], '__file__', None):
                cls.stubs[name] = sys.modules.pop(name)
            importlib.import_module(name)

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.stubs)

    def setUp(self):
        stack = ExitStack(); self.addCleanup(stack.close)
        stack.enter_context(patch('socket.socket.connect', side_effect=AssertionError('NETWORK FORBIDDEN')))
        stack.enter_context(patch('socket.getaddrinfo', side_effect=AssertionError('DNS FORBIDDEN')))
        stack.enter_context(patch('worker.db.connect', side_effect=AssertionError('DB FORBIDDEN')))

    def recognizer(self, responses, **kwargs):
        rec = TrackRecognizer(**kwargs)
        http = HTTP(responses)
        rec.transport = SingleAttemptHTTP(session_factory=lambda **kw: http, wall_clock=lambda: 0,
                                          before_request=rec.before_request)
        async def recognize(_):
            return await rec.transport.request('POST', 'https://provider.invalid/SECRET')
        rec.shazam = SimpleNamespace(recognize=recognize)
        return rec, http

    def test_classifier_both_links_cycles_and_no_message_sniff(self):
        from shazamio.exceptions import RateLimited
        root = ValueError('SECRET 429'); wrapper = RuntimeError('SECRET')
        root.__cause__ = wrapper; wrapper.__cause__ = root
        root.__context__ = RateLimited('rate limited')
        self.assertTrue(classify_error(root).was_rate_limited)
        self.assertEqual(classify_error(ValueError('429')).error_type, 'RecognitionError')
        for error, kind in [(ProviderHTTPError(503), 'ProviderServerError'),
                            (ProviderHTTPError(403), 'ProviderHTTPError'),
                            (ConnectionError('SECRET'), 'TransportError'),
                            (TimeoutError('SECRET'), 'RequestTimeout')]:
            wrapper = RuntimeError('SECRET'); wrapper.__context__ = error
            self.assertEqual(classify_error(wrapper).error_type, kind)

    def test_retry_after_never_clamped(self):
        self.assertEqual(retry_after('9' * 100, 0), (int('9' * 100), 'delta_seconds'))
        self.assertEqual(retry_after('Thu, 01 Jan 1970 00:02:00 GMT', 0), (120, 'http_date'))
        self.assertEqual(retry_after('-1', 0), (None, 'invalid'))

    def test_one_request_metadata_and_sanitized_logs(self):
        rec, http = self.recognizer([Response(429, {'Retry-After': '600'})], single_attempt=True)
        output = StringIO()
        with redirect_stdout(output): result = asyncio.run(rec.recognize_segment_with_backoff(segment()))
        self.assertEqual((result.error_type, result.http_status, result.retry_after_seconds), ('RateLimited', 429, 600))
        self.assertFalse(result.is_valid)
        self.assertIsNone(result.error_details)
        self.assertNotIn('SECRET', output.getvalue())
        self.assertEqual(len(http.calls), 1)
        self.assertIs(http.calls[0][1]['allow_redirects'], False)

    def test_sdk_cannot_issue_second_request_or_redirect(self):
        rec, http = self.recognizer([Response(), Response()], single_attempt=True)
        async def recognize(_):
            await rec.transport.request('POST', 'https://provider.invalid/SECRET')
            return await rec.transport.request('POST', 'https://provider.invalid/SECRET')
        rec.shazam.recognize = recognize
        result = asyncio.run(rec.recognize_segment(segment()))
        self.assertEqual(result.error_type, 'RequestBudgetExceeded')
        self.assertEqual(len(http.calls), 1)

    def test_cli_attempt_cap(self):
        rec, http = self.recognizer([Response(503)] * 5, max_attempts=2)
        with patch.object(Config, 'BASE_DELAY', 0):
            result = asyncio.run(rec.recognize_segment_with_backoff(segment()))
        self.assertEqual(len(http.calls), 2)
        self.assertEqual(result.error_type, 'ProviderServerError')

    def test_long_retry_after_stops_without_shortening(self):
        rec, http = self.recognizer([Response(429, {'Retry-After': '600'})], max_retry_seconds=1)
        with patch.object(Config, 'BASE_DELAY', 0):
            result = asyncio.run(rec.recognize_segment_with_backoff(segment()))
        self.assertEqual(result.retry_after_seconds, 600)
        self.assertEqual(len(http.calls), 1)

    def test_malformed_response_is_not_no_match(self):
        rec, http = self.recognizer([Response(value={'error': 'SECRET'})], single_attempt=True)
        result = asyncio.run(rec.recognize_segment(segment()))
        self.assertEqual(result.error_type, 'InvalidRecognitionResponse')
        self.assertIsNone(result.raw_data)

    def test_cancellation_propagates(self):
        rec, _ = self.recognizer([], single_attempt=True)
        rec.shazam.recognize = AsyncMock(side_effect=asyncio.CancelledError())
        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(rec.recognize_batch([segment()], cleanup_files=False))

    def test_concurrent_windows_have_independent_one_request_budgets(self):
        rec, http = self.recognizer([Response(), Response()], single_attempt=True)
        results = asyncio.run(rec.recognize_batch([segment(0), segment(1)], cleanup_files=False))
        self.assertEqual(len(http.calls), 2)
        self.assertTrue(all(result.is_valid for result in results))

    def test_transient_recovers_with_bounded_retry(self):
        rec, http = self.recognizer([Response(503), Response()], max_attempts=2)
        with patch.object(Config, 'BASE_DELAY', 0):
            result = asyncio.run(rec.recognize_segment_with_backoff(segment()))
        self.assertTrue(result.is_valid)
        self.assertEqual(len(http.calls), 2)

    def test_total_elapsed_budget_includes_inflight_attempt(self):
        rec, http = self.recognizer([], max_retry_seconds=0.01)
        async def stalled(_):
            await asyncio.sleep(100)
        rec.shazam.recognize = stalled
        with patch.object(Config, 'BASE_DELAY', 0):
            result = asyncio.run(rec.recognize_segment_with_backoff(segment()))
        self.assertEqual(result.error_type, 'RequestTimeout')
        self.assertFalse(result.is_valid)

    def test_http_date_metadata_and_invalid_header_stop(self):
        rec, http = self.recognizer([Response(503, {'Retry-After': 'Thu, 01 Jan 1970 00:02:00 GMT'})], single_attempt=True)
        result = asyncio.run(rec.recognize_segment(segment()))
        self.assertEqual((result.retry_after_seconds, result.retry_after_format), (120, 'http_date'))
        rec, http = self.recognizer([Response(429, {'Retry-After': 'SECRET'})])
        with patch.object(Config, 'BASE_DELAY', 0):
            result = asyncio.run(rec.recognize_segment_with_backoff(segment()))
        self.assertEqual(result.retry_after_format, 'invalid')
        self.assertEqual(len(http.calls), 1)

    def test_fence_runs_after_signature_and_refusal_propagates_without_http(self):
        order = []
        allowed = True
        def authorize():
            order.append('authorize')
            if not allowed:
                raise RuntimeError('PRIVATE_OWNER_DETAILS')
        rec, http = self.recognizer([Response()], single_attempt=True, before_request=authorize)
        async def recognize(_):
            nonlocal allowed
            order.append('signature')
            await asyncio.sleep(0)
            allowed = False  # Owner/cancellation/deadline changes during SDK work.
            return await rec.transport.request('POST', 'https://provider.invalid/SECRET')
        rec.shazam.recognize = recognize
        output = StringIO()
        with redirect_stdout(output), self.assertRaisesRegex(RequestAuthorizationError, '^recognition_request_not_authorized$'):
            asyncio.run(rec.recognize_batch([segment()], cleanup_files=False))
        self.assertEqual(order, ['signature', 'authorize'])
        self.assertEqual(http.calls, [])
        self.assertNotIn('PRIVATE', output.getvalue())

    def test_expired_reservation_after_extraction_never_transmits(self):
        now, expiry = [0], 65
        def authorize():
            if now[0] >= expiry:
                raise RuntimeError('expired')
        rec, http = self.recognizer([Response()], single_attempt=True, before_request=authorize)
        async def extract_then_recognize():
            now[0] = 4000  # Synthetic delayed extraction exceeds global gate expiry.
            return await rec.recognize_batch([segment()], cleanup_files=False)
        with self.assertRaises(RequestAuthorizationError):
            asyncio.run(extract_then_recognize())
        self.assertEqual(http.calls, [])

    def test_authorized_hook_precedes_exactly_one_http_request(self):
        calls = []
        rec, http = self.recognizer([Response()], single_attempt=True,
                                   before_request=lambda: calls.append('authorized'))
        result = asyncio.run(rec.recognize_segment(segment()))
        self.assertTrue(result.is_valid)
        self.assertEqual(calls, ['authorized'])
        self.assertEqual(len(http.calls), 1)

    def test_single_attempt_timeout_bounded_for_durable_quarantine(self):
        for configured, expected in ((0, 1), (15, 15), (300, 30)):
            with patch.object(Config, 'RECOGNITION_TIMEOUT', configured):
                rec = TrackRecognizer(single_attempt=True)
                self.assertEqual(rec.attempt_timeout, expected)
                self.assertEqual(rec.transport.timeout, expected)
                default = TrackRecognizer()
                self.assertEqual(default.transport.timeout, configured)

    def test_range_closes_only_owned_recognizer_including_extraction_failure(self):
        from worker.pipeline import recognize as pipeline
        context = SimpleNamespace(checkpoint_manager=object(), audio_file=Path('synthetic'), total_segments=1)
        for injected in (False, True):
            for extraction_fails in (False, True):
                with self.subTest(injected=injected, extraction_fails=extraction_fails):
                    recognizer = SimpleNamespace(recognize_batch=AsyncMock(return_value=[valid(0)]), close=AsyncMock())
                    extraction = AsyncMock(side_effect=RuntimeError('extract') if extraction_fails else None,
                                           return_value=[segment()])
                    async def run():
                        with patch.object(pipeline, 'AudioSegmenter', return_value=SimpleNamespace(create_segments_batch=extraction)), \
                             patch('track_recognizer.TrackRecognizer', return_value=recognizer):
                            await pipeline.recognize_segment_range(context, start_index=0, end_index=0,
                                                                  recognizer=recognizer if injected else None)
                    if extraction_fails:
                        with self.assertRaises(RuntimeError):
                            asyncio.run(run())
                    else:
                        asyncio.run(run())
                    self.assertEqual(recognizer.close.await_count, 0 if injected else 1)

    def test_resume_gaps_and_duplicates_not_list_length(self):
        saved = [asdict(valid(2)), asdict(valid(0)), asdict(valid(2)),
                 asdict(Recognition(15, None, None, None, None, False, 1)), asdict(valid(99))]
        writes = []
        checkpoint = SimpleNamespace(load_checkpoint=lambda: {'stage': 'recognizing', 'data': {'recognitions': saved}},
            save_recognition_checkpoint=lambda rows, stage: writes.append((list(rows), stage)))
        rec, _ = self.recognizer([], checkpoint_manager=checkpoint)
        extracted = []
        async def extract(audio, start, end, executor):
            extracted.append((start, end)); return [segment(i) for i in range(start, end)]
        segmenter = SimpleNamespace(calculate_total_segments=lambda duration: 3, create_segments_batch=extract)
        rec.recognize_batch = AsyncMock(return_value=[valid(1)])
        results = asyncio.run(rec.recognize_segments_streaming(Path('synthetic'), 45, segmenter, True))
        self.assertEqual(extracted, [(1, 2)])
        self.assertEqual([r.segment_index for r in results], [0, 1, 2])
        self.assertEqual(writes[-1][1], 'recognized')

    def test_failure_never_completes_checkpoint(self):
        writes = []
        checkpoint = SimpleNamespace(save_recognition_checkpoint=lambda rows, stage: writes.append((list(rows), stage)))
        rec, _ = self.recognizer([], checkpoint_manager=checkpoint)
        segmenter = SimpleNamespace(calculate_total_segments=lambda duration: 2,
            create_segments_batch=AsyncMock(return_value=[segment(0), segment(1)]))
        rec.recognize_batch = AsyncMock(return_value=[valid(0), Recognition(15, None, None, None, None, False, 1, error_type='TransportError')])
        with self.assertRaises(RecognitionIncomplete):
            asyncio.run(rec.recognize_segments_streaming(Path('synthetic'), 30, segmenter))
        self.assertEqual(writes[-1][1], 'recognizing')
        self.assertEqual([r.segment_index for r in writes[-1][0]], [0])


if __name__ == '__main__': unittest.main()
