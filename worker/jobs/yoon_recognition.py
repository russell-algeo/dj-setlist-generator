"""Bounded transport/session for the fixed private pilot only.

No shared recognizer changes, provider rotation, implicit HTTP retries, or logs.
Diagnostics are allowlisted and travel only with the private run checkpoint.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timezone
from email.utils import parsedate_to_datetime
from importlib.metadata import PackageNotFoundError, version
import math
import platform
import time

from worker.pipeline.models import Recognition


@dataclass(frozen=True)
class Policy:
    mode: str
    window_limit: int
    request_limit: int
    seconds_limit: int
    spacing_seconds: int = 8
    retry_limit: int = 1  # Entire run, not per window.
    retry_floor_seconds: int = 120
    retry_wait_limit_seconds: int = 300
    attempt_timeout_seconds: int = 60


def policy_for(mode):
    if mode == 'probe':
        return Policy('probe', 5, 6, 600)
    if mode == 'full':
        return Policy('full', 479, 480, 80 * 60)
    raise RuntimeError('invalid_private_recognition_mode')


def retry_after(value, now):
    """Return parsed seconds + format, never a raw header. Never shorten a wait."""
    if value is None:
        return None, 'absent'
    if not isinstance(value, str) or len(value) > 128:
        return None, 'invalid'
    value = value.strip()
    if value.isascii() and value.isdigit():
        seconds = int(value)
        # Oversized positive values must cause a stop, not fall back to 120s.
        return min(seconds, 10**12), 'delta_seconds'
    try:
        date = parsedate_to_datetime(value)
        if date.tzinfo is None:
            return None, 'invalid'
        seconds = max(0, math.ceil(date.astimezone(timezone.utc).timestamp() - now))
        return min(seconds, 10**12), 'http_date'
    except (ValueError, TypeError, OverflowError):
        return None, 'invalid'


class PrivateHTTPError(Exception):
    def __init__(self, status):
        self.status = status
        super().__init__('private_provider_http_error')


class PrivateStop(Exception):
    pass


def classify_error(error):
    """Class identity/status, including wrapped exceptions, without message sniffing."""
    from shazamio.exceptions import RateLimited
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, RateLimited) or getattr(current, 'status', None) == 429:
            return 'RateLimited', True
        current = current.__cause__ or current.__context__
    if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
        return 'RequestTimeout', False
    if isinstance(error, PrivateStop):
        return 'PrivateBudgetStop', False
    if isinstance(error, PrivateHTTPError):
        return 'ProviderHTTPError', False
    return 'RecognitionError', False


class SingleAttemptHTTP:
    """Shazam's injected HTTP interface: exactly one nonredirecting POST per attempt."""
    def __init__(self, policy, *, before_request, clock=time.monotonic,
                 wall_clock=time.time, sleep=asyncio.sleep, session_factory=None):
        self.policy = policy
        self.before_request = before_request
        self.clock, self.wall_clock, self.sleep = clock, wall_clock, sleep
        self.session_factory = session_factory
        self.client = None
        self.started = clock()
        self.last_finished = None
        self.requests = 0
        self.record = None
        self.used = False

    def begin(self, record):
        self.record = record
        self.used = False

    async def request(self, method, url, **kwargs):
        import aiohttp
        if self.used or method.upper() != 'POST' or self.requests >= self.policy.request_limit:
            raise PrivateStop('request_budget')
        self.used = True
        if self.last_finished is not None:
            delay = max(0, self.policy.spacing_seconds - (self.clock() - self.last_finished))
            self.record['spacing_wait_seconds'] = round(delay, 3)
            if delay:
                await self.sleep(delay)
        self.before_request()  # Recheck owner/cancellation after any pause, before transmission.
        if self.client is None:
            factory = self.session_factory or aiohttp.ClientSession
            self.client = factory(timeout=aiohttp.ClientTimeout(total=30), trust_env=False)
        self.requests += 1
        self.record['http_request_number'] = self.requests
        self.record['started_after_seconds'] = round(self.clock() - self.started, 3)
        start = self.clock()
        try:
            # These override any downstream defaults. No HTTP redirects or retry client.
            kwargs['allow_redirects'] = False
            kwargs['timeout'] = aiohttp.ClientTimeout(total=30)
            async with self.client.request('POST', url, **kwargs) as response:
                self.record['http_status'] = response.status
                seconds, kind = retry_after(response.headers.get('Retry-After'), self.wall_clock())
                self.record['retry_after_seconds'] = seconds
                self.record['retry_after_format'] = kind
                if response.status != 200:
                    raise PrivateHTTPError(response.status)
                value = await response.json()
                # A 200 error object is not a valid no-match response.
                if not isinstance(value, dict) or not isinstance(value.get('matches'), list):
                    raise ValueError('invalid_recognition_response')
                if 'track' in value and not isinstance(value['track'], dict):
                    raise ValueError('invalid_recognition_track')
                if value['matches'] and 'track' not in value:
                    raise ValueError('missing_recognition_track')
                return value
        finally:
            self.last_finished = self.clock()
            self.record['http_elapsed_seconds'] = round(self.last_finished - start, 3)

    async def request_text(self, *args, **kwargs):
        raise PrivateStop('unexpected_transport_operation')

    async def close(self):
        if self.client is not None:
            await self.client.close()


class PrivateRecognitionSession:
    def __init__(self, policy=None, *, before_request=lambda: None, clock=time.monotonic,
                 wall_clock=time.time, sleep=asyncio.sleep, session_factory=None):
        from shazamio import Shazam
        from track_recognizer import TrackRecognizer
        self.policy = policy or policy_for('probe')
        self.transport = SingleAttemptHTTP(self.policy, before_request=before_request,
                clock=clock, wall_clock=wall_clock, sleep=sleep, session_factory=session_factory)
        transport = self.transport
        class PrivateTrackRecognizer(TrackRecognizer):
            # Reuse the app's actual segment recognition and result mapping. Only
            # this instance opts into typed classification and a bounded transport.
            def _create_shazam_client(self):
                return Shazam(http_client=transport, endpoint_country='US')

            def _is_rate_limit_error(self, error):
                self.last_error_kind, limited = classify_error(error)
                return limited

        self.recognizer = PrivateTrackRecognizer()
        self.sleep = sleep
        self.stopped = False
        self.reason = None
        self.retries = 0
        self.attempts = []
        self.lock = asyncio.Lock()
        packages = {}
        for package in ('shazamio', 'shazamio-core', 'aiohttp', 'aiohttp-retry'):
            try:
                packages[package] = version(package)
            except PackageNotFoundError:
                packages[package] = 'unavailable'
        self.versions = {'python': platform.python_version(), **packages}

    def diagnostics(self):
        # No URLs, messages, full headers, fingerprints, bodies or source capabilities.
        return {'versions': self.versions, 'mode': self.policy.mode, 'concurrency': 1,
                'spacing_seconds': self.policy.spacing_seconds,
                'request_limit': self.policy.request_limit, 'requests': self.transport.requests,
                'retry_limit': self.policy.retry_limit, 'retries': self.retries,
                'attempts': [dict(row) for row in self.attempts]}

    async def one(self, segment, on_result):
        async with self.lock:
            if self.stopped:
                return
            for attempt in range(1, 3):  # At most two tries for any window.
                record = {'segment_index': segment['index'], 'attempt': attempt,
                          'http_status': None, 'retry_after_seconds': None,
                          'retry_after_format': 'unobserved'}
                self.attempts.append(record)
                self.transport.begin(record)
                try:
                    result = await asyncio.wait_for(self.recognizer.recognize_segment(segment),
                                                  self.policy.attempt_timeout_seconds)
                    if result.error_type:
                        result.error_type = self.recognizer.last_error_kind
                        result.error_details = None  # Shared mapper includes unsafe exception text.
                        record['outcome'] = result.error_type
                    else:
                        record['outcome'] = 'recognized' if result.recognized else 'no_match'
                except asyncio.CancelledError:
                    record['outcome'] = 'cancelled'
                    raise
                except Exception as error:
                    kind, limited = classify_error(error)
                    result = Recognition(segment['timestamp'], None, None, None, None,
                        False, segment['index'], was_rate_limited=limited, error_type=kind)
                    record['outcome'] = kind
                retry_delay = None
                if result.was_rate_limited and self.retries < self.policy.retry_limit:
                    if record['retry_after_format'] == 'invalid':
                        self.reason = 'invalid_retry_after'
                    else:
                        retry_delay = max(self.policy.retry_floor_seconds,
                                          record['retry_after_seconds'] or 0)
                        if retry_delay > self.policy.retry_wait_limit_seconds:
                            self.reason = 'retry_after_exceeds_budget'
                            retry_delay = None
                if retry_delay is not None:
                    record['planned_retry_wait_seconds'] = retry_delay
                try:
                    on_result(result)  # Persist every response BEFORE waiting or proceeding.
                except Exception:
                    self.stopped = True
                    raise
                if not result.error_type and not result.was_rate_limited:
                    return
                if retry_delay is None:
                    self.stopped = True
                    self.reason = self.reason or ('rate_limited' if result.was_rate_limited else 'provider_error')
                    return
                self.retries += 1
                await self.sleep(retry_delay)
            self.stopped = True
            self.reason = 'rate_limited'

    async def recognize_batch(self, batch_segments, *, total_segments=None, batch_start=0,
                              on_result=None, cleanup_files=True):
        """Adapter for the shared range runner, with immediate private checkpoints."""
        rows = {}
        def persist(result):
            rows[result.segment_index] = result
            if on_result:
                on_result(result)
        try:
            for segment in batch_segments:
                if self.stopped:
                    break
                await self.one(segment, persist)
        finally:
            if cleanup_files:
                for segment in batch_segments:
                    segment['file'].unlink(missing_ok=True)
        return [rows[index] for index in sorted(rows)]

    async def close(self):
        await self.transport.close()
