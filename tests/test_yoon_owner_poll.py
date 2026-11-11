"""Offline guard-poll timing, immediate admission and stop/evidence regressions."""
import asyncio
from contextlib import asynccontextmanager
import hashlib
from pathlib import Path
import tempfile
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from track_recognizer import TrackRecognizer
from worker.jobs.yoon_resume import recognize_resumable
from worker.jobs.yoon_resume_store import QueuePause
from worker.jobs.yoon_sources import JACKSON
from worker.pipeline.models import Recognition


class Store:
    def __init__(self):
        self.now = 0
        self.state = dict(session_started=0, requests=0,
                          source_id=JACKSON.id,
                          audio_sha256=hashlib.sha256(b'synthetic').hexdigest())
        self.pending = {0, 1}
        self.evidence = {9: {'state': 'finished', 'response': 'immutable prior response'}}
        self.events = []
        self.owner_error = None
        self.finish_error = None

    def require_owner(self):
        self.events.append(('owner', self.now))
        if self.owner_error:
            raise self.owner_error
        return dict(self.state)

    def check_owner(self):
        self.require_owner()

    def clock_state(self):
        return self.now, dict(self.state)

    def next_windows(self, slot, limit):
        return [dict(segment_index=i) for i in sorted(self.pending)], 0

    def reserve(self, index, slot):
        self.events.append(('reserve', index))
        self.state['requests'] += 1
        ticket = f'synthetic-ticket-{index}'
        self.evidence[index] = dict(state='in_flight', ticket=ticket)
        return ticket

    def finish(self, result, ticket, delay_seconds):
        self.events.append(('finish', result.segment_index))
        if self.finish_error:
            raise self.finish_error
        self.assert_ticket(result.segment_index, ticket)
        self.evidence[result.segment_index].update(state='finished', response=result)
        self.pending.remove(result.segment_index)

    def assert_ticket(self, index, ticket):
        assert self.evidence[index] == dict(state='in_flight', ticket=ticket)


class OwnerPollTests(IsolatedAsyncioTestCase):
    @asynccontextmanager
    async def adapter(self, store, provider, prepare=None):
        """Use the real batch/backoff engine with synthetic, socket-free attempts."""
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory)/'audio'
            audio.write_bytes(b'synthetic')
            extracted = []
            engines = []

            async def extract(_self, _audio, first, end, executor):
                segments = []
                for index in range(first, end):
                    file = Path(directory)/f'{index}.wav'
                    file.write_bytes(b'synthetic')
                    extracted.append(file)
                    segments.append(dict(index=index, timestamp=index*15, file=file))
                return segments

            def engine_factory(**options):
                engine = TrackRecognizer(single_attempt=True, **options)

                async def attempt(segment):
                    if prepare:
                        await prepare(segment)
                    # The real before_request path invokes adapter before_attempt.
                    engine.before_request()
                    store.events.append(('provider', segment['index']))
                    await provider(segment)
                    return Recognition(segment['timestamp'], None, None, None,
                                       {'matches': []}, False, segment['index'], http_status=200)

                engine.recognize_segment = attempt
                engine.close = AsyncMock(wraps=engine.close)
                engines.append(engine)
                return engine

            with patch('socket.socket.connect', side_effect=AssertionError('network forbidden')), \
                 patch('socket.getaddrinfo', side_effect=AssertionError('DNS forbidden')), \
                 patch('psycopg.connect', side_effect=AssertionError('live DB forbidden')), \
                 patch('track_recognizer.TrackRecognizer', new=engine_factory), \
                 patch('audio_segmenter.AudioSegmenter.create_segments_batch', new=extract), \
                 patch('audio_segmenter.AudioSegmenter.get_audio_duration_ffprobe', return_value=JACKSON.duration), \
                 patch('audio_segmenter.AudioSegmenter.calculate_total_segments', return_value=JACKSON.windows):
                task = asyncio.create_task(recognize_resumable(store, audio))
                try:
                    yield task, extracted
                finally:
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    self.assertTrue(all(not file.exists() for file in extracted))
                    self.assertEqual(len(engines), 1)
                    engines[0].close.assert_awaited_once()
                    self.assertEqual(store.evidence[9],
                                     {'state': 'finished', 'response': 'immutable prior response'})

    async def test_passive_poll_is_ten_seconds_and_settles_all_active_attempts(self):
        for error in (RuntimeError('private_resume_owner_changed'),
                      RuntimeError('private_resume_scope_required'),
                      RuntimeError('private_resume_audience_changed'),
                      RuntimeError('private_resume_source_changed'),
                      QueuePause('private_resume_review_required')):
            with self.subTest(error=str(error)):
                store = Store()
                started = asyncio.Event()
                settled = set()
                waits = []

                async def provider(segment):
                    if len([event for event in store.events if event[0] == 'provider']) == 2:
                        started.set()
                    try:
                        await asyncio.Event().wait()
                    finally:
                        # Both provider coroutines settle before segment cleanup.
                        self.assertTrue(segment['file'].exists())
                        settled.add(segment['index'])

                async def elapsed_wait(tasks, *, timeout):
                    await started.wait()
                    waits.append(timeout)
                    store.now += timeout
                    if len(waits) == 3:
                        store.owner_error = error
                    return set(), set(tasks)

                with patch('worker.jobs.yoon_resume.asyncio.wait', new=elapsed_wait):
                    async with self.adapter(store, provider) as (task, _):
                        if isinstance(error, QueuePause):
                            self.assertEqual(await asyncio.wait_for(task, 1), 'paused')
                        else:
                            with self.assertRaises(type(error)) as caught:
                                await asyncio.wait_for(task, 1)
                            self.assertIs(caught.exception, error)
                self.assertEqual(waits, [10, 10, 10])
                self.assertEqual([value for name, value in store.events if name == 'owner'],
                                 [0, 0, 0, 10, 20, 30])
                self.assertEqual(settled, {0, 1})
                self.assertEqual(store.state['requests'], 2)
                for index in (0, 1):
                    store.assert_ticket(index, f'synthetic-ticket-{index}')
                self.assertFalse(any(name == 'finish' for name, _ in store.events))

    async def test_completion_wakes_immediately_and_rechecks_owner(self):
        store = Store()
        async def provider(segment):
            return None
        async with self.adapter(store, provider) as (task, _):
            # Real asyncio.wait(timeout=10), not a sleep or a mocked timer.
            self.assertEqual(await asyncio.wait_for(task, 1), 'slot_complete')
        self.assertEqual([event[0] for event in store.events],
                         ['owner', 'owner', 'reserve', 'provider', 'finish',
                          'owner', 'reserve', 'provider', 'finish', 'owner'])
        self.assertTrue(all(store.evidence[index]['state'] == 'finished' for index in (0, 1)))

    async def test_before_attempt_guard_is_immediate_not_cached_until_poll(self):
        store = Store()
        error = RuntimeError('private_resume_owner_changed')
        async def prepare(segment):
            store.owner_error = error
        async def provider(segment):
            self.fail('no provider attempt may follow a refused owner guard')
        async with self.adapter(store, provider, prepare) as (task, _):
            with self.assertRaises(RuntimeError) as caught:
                await asyncio.wait_for(task, 1)
            self.assertIs(caught.exception, error)
        self.assertEqual(store.state['requests'], 0)
        self.assertTrue(all(name == 'owner' for name, _ in store.events))
        self.assertEqual(set(store.evidence), {9})

    async def test_external_cancel_is_immediate_and_preserves_in_flight_evidence(self):
        store = Store()
        started = asyncio.Event()
        settled = set()
        async def provider(segment):
            if len([event for event in store.events if event[0] == 'provider']) == 2:
                started.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.assertTrue(segment['file'].exists())
                settled.add(segment['index'])
        async with self.adapter(store, provider) as (task, _):
            await asyncio.wait_for(started.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 1)
        self.assertEqual(settled, {0, 1})
        for index in (0, 1):
            store.assert_ticket(index, f'synthetic-ticket-{index}')

    async def test_finish_failure_never_fabricates_success_or_erases_evidence(self):
        store = Store()
        error = RuntimeError('uncertain_storage')
        async def provider(segment):
            store.finish_error = error
            # A review guard stops reselection after the attempted durable write.
            store.owner_error = QueuePause('private_resume_review_required')
        async with self.adapter(store, provider) as (task, _):
            self.assertEqual(await asyncio.wait_for(task, 1), 'paused')
        store.assert_ticket(0, 'synthetic-ticket-0')
        self.assertEqual(store.state['requests'], 1)
        self.assertIn(('finish', 0), store.events)
        self.assertNotIn(1, store.evidence)
