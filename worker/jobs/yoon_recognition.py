"""Private pilot limits and diagnostics around the common DJ recognizer.

The provider transport, response classification, retry timing and concurrency
are implemented only by TrackRecognizer. This adapter owns no Shazam policy.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
import platform
import time

from config import Config
from recognition_transport import RequestAuthorizationError, classify_error, retry_after


@dataclass(frozen=True)
class Policy:
    mode: str
    window_limit: int
    request_limit: int
    seconds_limit: int
    retry_limit: int = 1  # Historical pilot cap, not a private retry strategy.


def policy_for(mode):
    if mode == 'probe':
        return Policy('probe',5,6,600)
    if mode == 'full':
        return Policy('full',479,480,80*60)
    raise RuntimeError('invalid_private_recognition_mode')


class PrivateStop(Exception):
    pass


class PrivateRecognitionSession:
    def __init__(self, policy=None, *, before_request=lambda: None, clock=time.monotonic,
                 wall_clock=time.time, sleep=None, session_factory=None):
        from track_recognizer import TrackRecognizer
        self.policy = policy or policy_for('probe')
        self.clock = clock
        self.started = clock()
        self.before_request = before_request
        self.stopped = False
        self.reason = None
        self.requests = 0
        self.retries = 0
        self.seen = set()
        self.attempts = []
        self.callbacks = {}
        self.recognizer = TrackRecognizer(before_attempt=self._before_attempt,
            on_attempt=self._on_attempt,max_retry_seconds=self.policy.seconds_limit,
            continuation_deadline=time.monotonic()+self.policy.seconds_limit,quiet=True)
        self.transport = self.recognizer.transport
        if session_factory is not None:
            self.transport.session_factory = session_factory
        self.transport.wall_clock = wall_clock
        packages = {}
        for package in ('shazamio','shazamio-core','aiohttp','aiohttp-retry'):
            try:
                packages[package] = version(package)
            except PackageNotFoundError:
                packages[package] = 'unavailable'
        self.versions = {'python':platform.python_version(),**packages}

    def _stop(self,reason):
        self.stopped = True
        self.reason = reason
        raise PrivateStop(reason)

    def _before_attempt(self, segment):
        if self.stopped:
            self._stop(self.reason or 'private_budget')
        index = segment['index']
        if self.requests >= self.policy.request_limit:
            self._stop('request_budget')
        if self.clock()-self.started >= self.policy.seconds_limit:
            self._stop('workflow_time_budget')
        if index not in self.seen and len(self.seen) >= self.policy.window_limit:
            self._stop('window_budget')
        if index in self.seen:
            if self.retries >= self.policy.retry_limit:
                self._stop('retry_budget')
            self.retries += 1
        self.before_request()
        self.seen.add(index)
        self.requests += 1
        record = dict(segment_index=index,http_request_number=self.requests,
                      started_after_seconds=round(self.clock()-self.started,3))
        self.attempts.append(record)
        return record

    def _on_attempt(self,result,ticket,delay_seconds):
        # A pre-transmission refusal is not a Shazam response and is never saved
        # as no-match. Only allowlisted status data enters the private checkpoint.
        ticket.update(http_status=result.http_status,retry_after_seconds=result.retry_after_seconds,
            retry_after_format=result.retry_after_format,
            outcome=result.error_type or ('recognized' if result.recognized else 'no_match'),
            planned_retry_wait_seconds=delay_seconds)
        callback = self.callbacks.get(result.segment_index)
        if callback:
            try:
                callback(result)
            except BaseException:
                self.stopped = True
                raise

    def diagnostics(self):
        return dict(versions=self.versions,mode=self.policy.mode,
                    concurrency=Config.CONCURRENT_RECOGNITIONS,engine='shared-track-recognizer',
                    request_limit=self.policy.request_limit,requests=self.requests,
                    retry_limit=self.policy.retry_limit,retries=self.retries,
                    attempts=[dict(row) for row in self.attempts])

    async def one(self, segment, on_result):
        if self.stopped:
            return
        self.callbacks[segment['index']] = on_result
        try:
            return await self.recognizer.recognize_segment_with_backoff(segment)
        except (PrivateStop,RequestAuthorizationError):
            self.stopped = True
            self.reason = self.reason or 'owner_or_budget_changed'
        finally:
            self.callbacks.pop(segment['index'],None)

    async def recognize_batch(self, batch_segments, *, total_segments=None, batch_start=0,
                              on_result=None, cleanup_files=True):
        rows = {}
        def persist(result):
            rows[result.segment_index] = result
            if on_result:
                on_result(result)
        for segment in batch_segments:
            self.callbacks[segment['index']] = persist
        try:
            await self.recognizer.recognize_batch(batch_segments,total_segments=total_segments,
                batch_start=batch_start,cleanup_files=cleanup_files)
        except (PrivateStop,RequestAuthorizationError):
            self.stopped = True
            self.reason = self.reason or 'owner_or_budget_changed'
        finally:
            for segment in batch_segments:
                self.callbacks.pop(segment['index'],None)
                if cleanup_files:
                    segment['file'].unlink(missing_ok=True)
        return [rows[index] for index in sorted(rows)]

    async def close(self):
        await self.recognizer.close()
