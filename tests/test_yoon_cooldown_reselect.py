"""Cross-slot cooldown admission races must not retire a healthy private slot."""
import asyncio
import hashlib
import tempfile
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from recognition_transport import RequestAuthorizationError
from track_recognizer import TrackRecognizer
from worker.jobs.yoon_resume import recognize_resumable
from worker.jobs.yoon_resume_store import QueuePause
from worker.jobs.yoon_sources import JACKSON
from worker.pipeline.models import Recognition


class Store:
    def __init__(self):
        self.now = 100
        self.state = dict(session_started=100, requests=0)
        self.pending = {0, 1, 2}
        self.completed = {10: 'existing immutable response'}
        self.calls = []
        self.selections = 0
        self.due = 0
        self.sleeps = []
        self.mode = 'race'
        self.first_authorized = asyncio.Event()
        self.peer_finished = asyncio.Event()
        self.owner_error = None

    def require_owner(self):
        if self.owner_error:
            raise self.owner_error
        return dict(source_id=JACKSON.id, audio_sha256=hashlib.sha256(b'synthetic').hexdigest())

    def clock_state(self):
        return self.now, dict(self.state)

    def next_windows(self, slot, limit):
        self.selections += 1
        return [dict(segment_index=i) for i in sorted(self.pending)], max(0, self.due-self.now)

    async def attempt(self, segment):
        index = segment['index']
        if index == 0:
            self.pending.remove(index)
            self.completed[index] = 'valid response'
            self.calls.append(index)
            self.state['requests'] += 1
            self.first_authorized.set()
        else:
            await self.peer_finished.wait()
            if self.mode == 'mixed' and index == self.stop_index:
                raise self.stop
            if self.mode == 'other_pause':
                raise QueuePause('window_attempt_budget')
            if self.mode == 'authorization':
                raise RequestAuthorizationError('owner changed')
            if self.mode == 'cancel':
                raise asyncio.CancelledError()
            if self.now < self.due:
                raise QueuePause('cooldown')  # no authorization, no HTTP
            self.pending.remove(index)
            self.completed[index] = 'valid response'
            self.calls.append(index)
            self.state['requests'] += 1
        return Recognition(index*15,None,None,None,{'matches':[]},False,index,http_status=200)

    async def peer_slot(self):
        # A distinct concurrent task persists the provider-wide due after this
        # slot selected its batch and authorized its first request.
        await self.first_authorized.wait()
        self.due = self.now+30
        self.peer_finished.set()

    async def sleep(self, seconds):
        assert 0 < seconds <= 15  # existing bounded wait, never busy-spin
        self.sleeps.append(seconds)
        self.now += seconds
        if self.mode == 'extend' and len(self.sleeps) == 1:
            self.due += 30
        if self.mode == 'deadline':
            self.now = self.state['session_started']+3600-64
        if self.mode == 'owner_during_wait':
            self.owner_error = RuntimeError('owner changed')
        if self.mode == 'cancel_during_wait':
            raise asyncio.CancelledError()


class CooldownReselectTests(IsolatedAsyncioTestCase):
    async def run_adapter(self, store):
        with tempfile.TemporaryDirectory() as folder:
            audio = Path(folder)/'audio'
            audio.write_bytes(b'synthetic')
            extracted = []
            async def extract(audio, first, end, executor):
                segments = []
                for index in range(first,end):
                    file = Path(folder)/f'{index}.wav'
                    file.write_bytes(b'synthetic')
                    extracted.append(file)
                    segments.append(dict(index=index,timestamp=index*15,file=file))
                return segments
            recognizer = object.__new__(TrackRecognizer)
            recognizer.quiet = True
            recognizer.recognize_segment_with_backoff = store.attempt
            recognizer.close = AsyncMock()
            with patch('audio_segmenter.AudioSegmenter.get_audio_duration_ffprobe',return_value=JACKSON.duration), \
                 patch('audio_segmenter.AudioSegmenter.calculate_total_segments',return_value=JACKSON.windows), \
                 patch('audio_segmenter.AudioSegmenter.create_segments_batch',new=AsyncMock(side_effect=extract)), \
                 patch('track_recognizer.TrackRecognizer',return_value=recognizer), \
                 patch('worker.jobs.yoon_resume.asyncio.sleep',new=store.sleep):
                peer = asyncio.create_task(store.peer_slot())
                try:
                    return await recognize_resumable(store,audio)
                finally:
                    peer.cancel()
                    await asyncio.gather(peer,return_exceptions=True)
                    recognizer.close.assert_awaited_once()
                    self.assertTrue(all(not f.exists() for f in extracted))
                    self.assertEqual(store.completed[10],'existing immutable response')

    async def test_peer_extension_after_selection_reselects_only_pending(self):
        store = Store()
        self.assertEqual(await self.run_adapter(store),'slot_complete')
        self.assertEqual(store.calls,[0,1,2])
        self.assertEqual(store.pending,set())
        self.assertEqual(store.sleeps,[15,15])
        self.assertEqual(store.state['requests'],3)

    async def test_repeated_extension_honors_latest_due(self):
        store = Store(); store.mode = 'extend'
        self.assertEqual(await self.run_adapter(store),'slot_complete')
        self.assertEqual(store.sleeps,[15]*4)
        self.assertEqual(store.calls,[0,1,2])

    async def test_deadline_still_pauses_without_more_requests(self):
        store = Store(); store.mode = 'deadline'
        self.assertEqual(await self.run_adapter(store),'paused')
        self.assertEqual(store.calls,[0])
        self.assertEqual(store.sleeps,[15])

    async def test_other_pause_not_retried(self):
        store = Store(); store.mode = 'other_pause'
        self.assertEqual(await self.run_adapter(store),'paused')
        self.assertEqual(store.selections,1)
        self.assertEqual(store.sleeps,[])

    async def test_authorization_failure_not_retried(self):
        store = Store(); store.mode = 'authorization'
        with self.assertRaises(RequestAuthorizationError):
            await self.run_adapter(store)
        self.assertEqual(store.selections,1)

    async def test_cancelled_batch_not_retried(self):
        store = Store(); store.mode = 'cancel'
        with self.assertRaises(asyncio.CancelledError):
            await self.run_adapter(store)
        self.assertEqual(store.selections,1)

    async def test_owner_checked_during_wait(self):
        store = Store(); store.mode = 'owner_during_wait'
        with self.assertRaisesRegex(RuntimeError,'owner changed'):
            await self.run_adapter(store)
        self.assertEqual(store.calls,[0])

    async def test_cancellation_during_wait_propagates(self):
        store = Store(); store.mode = 'cancel_during_wait'
        with self.assertRaises(asyncio.CancelledError):
            await self.run_adapter(store)
        self.assertEqual(store.calls,[0])

    async def test_mixed_cooldown_and_stop_never_reselect_in_either_order(self):
        for index in (1,2):
            for stop in (RequestAuthorizationError('owner changed'),
                         QueuePause('window_attempt_budget'),
                         RuntimeError('uncertain storage'),asyncio.CancelledError()):
                with self.subTest(index=index,stop=type(stop).__name__):
                    store = Store(); store.mode = 'mixed'
                    store.stop_index = index; store.stop = stop
                    if isinstance(stop,QueuePause):
                        self.assertEqual(await self.run_adapter(store),'paused')
                    else:
                        with self.assertRaises(type(stop)):
                            await self.run_adapter(store)
                    self.assertEqual(store.selections,1)
                    self.assertEqual(store.calls,[0])
                    self.assertEqual(store.sleeps,[])
