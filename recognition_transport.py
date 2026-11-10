"""Single-request Shazam transport and allowlisted, credential-free diagnostics."""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import timezone
from email.utils import parsedate_to_datetime
import math
import time


def retry_after(value, now=None):
    """Parse Retry-After without clamping positive waits to a shorter duration."""
    if value is None:
        return None, 'absent'
    if not isinstance(value, str) or len(value) > 128:
        return None, 'invalid'
    value = value.strip()
    if value.isascii() and value.isdigit():
        return int(value), 'delta_seconds'
    try:
        date = parsedate_to_datetime(value)
        if date.tzinfo is None:
            return None, 'invalid'
        return max(0, math.ceil(date.astimezone(timezone.utc).timestamp() -
                               (time.time() if now is None else now))), 'http_date'
    except (ValueError, TypeError, OverflowError):
        return None, 'invalid'


@dataclass(frozen=True)
class Failure:
    error_type: str
    was_rate_limited: bool = False
    http_status: int | None = None
    retry_after_seconds: int | None = None
    retry_after_format: str = 'absent'


class ProviderHTTPError(Exception):
    def __init__(self, status, seconds=None, kind='absent'):
        self.status = status
        self.retry_after_seconds = seconds
        self.retry_after_format = kind
        super().__init__('provider_http_error')


class InvalidRecognitionResponse(Exception):
    pass


class RequestBudgetExceeded(Exception):
    pass


class RequestAuthorizationError(Exception):
    """The pre-transmission fence refused this request; no HTTP call was made."""


class RequestDeferred(RequestAuthorizationError):
    """A deliberate pre-request budget/cooldown stop with a safe constant reason."""


def classify_error(error):
    """Inspect both exception links cycle-safely; never inspect/return exception text."""
    import aiohttp
    from shazamio.exceptions import RateLimited
    stack, seen, errors = [error], set(), []
    while stack:
        current = stack.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        errors.append(current)
        stack.extend((current.__context__, current.__cause__))
    # Rate limiting has priority even when buried under a wrapper/status error.
    for current in errors:
        if getattr(current, 'status', None) == 429:
            return _failure('RateLimited', current, True, 429)
    for current in errors:
        if isinstance(current, RateLimited):
            # An SDK label is not proof of an HTTP response. Do not mint
            # durable unlimited-throttle credit without an actual status.
            return _failure('RateLimited', current, True)
    for current in errors:
        status = getattr(current, 'status', None)
        if isinstance(status, int) and 100 <= status <= 599:
            return _failure('ProviderServerError' if status >= 500 else 'ProviderHTTPError', current, status=status)
    for current in errors:
        if isinstance(current, (TimeoutError, asyncio.TimeoutError)):
            return Failure('RequestTimeout')
        if isinstance(current, (aiohttp.ClientConnectionError, ConnectionError, OSError)):
            return Failure('TransportError')
        if isinstance(current, InvalidRecognitionResponse):
            return Failure('InvalidRecognitionResponse')
        if isinstance(current, RequestBudgetExceeded):
            return Failure('RequestBudgetExceeded')
    return Failure('RecognitionError')


def _failure(kind, error, limited=False, status=None):
    seconds = getattr(error, 'retry_after_seconds', None)
    form = getattr(error, 'retry_after_format', 'absent')
    if hasattr(error, 'headers') and error.headers:
        seconds, form = retry_after(error.headers.get('Retry-After'))
    if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0:
        seconds = None
    if form not in {'absent', 'invalid', 'delta_seconds', 'http_date'}:
        form = 'invalid'
    return Failure(kind, limited, status, seconds, form)


def validate_response(value):
    if not isinstance(value, dict) or not isinstance(value.get('matches'), list):
        raise InvalidRecognitionResponse()
    if 'track' in value and not isinstance(value['track'], dict):
        raise InvalidRecognitionResponse()
    if value['matches'] and 'track' not in value:
        raise InvalidRecognitionResponse()
    return value


class SingleAttemptHTTP:
    """One nonredirecting POST per recognition, including concurrent SDK calls."""
    def __init__(self, *, timeout=30, session_factory=None, wall_clock=time.time, before_request=None):
        # Release/aggregation jobs use the lightweight exception types above
        # without installing the recognition-only HTTP/SDK dependencies.
        import aiohttp
        self.timeout = timeout
        self.before_request = before_request
        self.session_factory = session_factory or aiohttp.ClientSession
        self.wall_clock = wall_clock
        self.client = None
        self._attempt = ContextVar('recognition_http_attempt', default=None)

    def begin(self):
        return self._attempt.set({'used': False})

    def end(self, token):
        self._attempt.reset(token)

    async def request(self, method, url, **kwargs):
        import aiohttp
        attempt = self._attempt.get()
        if attempt is None or attempt['used'] or method.upper() != 'POST':
            raise RequestBudgetExceeded()
        attempt['used'] = True
        if self.client is None:
            self.client = self.session_factory(timeout=aiohttp.ClientTimeout(total=self.timeout), trust_env=False)
        kwargs['allow_redirects'] = False
        kwargs['timeout'] = aiohttp.ClientTimeout(total=self.timeout)
        # Runs after fingerprint/signature construction and immediately before
        # transmission. Refusal is control flow, never a provider response.
        if self.before_request is not None:
            try:
                self.before_request()
            except RequestDeferred:
                raise
            except Exception:
                raise RequestAuthorizationError('recognition_request_not_authorized') from None
        async with self.client.request('POST', url, **kwargs) as response:
            seconds, form = retry_after(response.headers.get('Retry-After'), self.wall_clock())
            if response.status != 200:
                raise ProviderHTTPError(response.status, seconds, form)
            try:
                return validate_response(await response.json())
            except (ValueError, aiohttp.ContentTypeError) as error:
                raise InvalidRecognitionResponse() from error

    async def request_text(self, *args, **kwargs):
        raise RequestBudgetExceeded()

    async def close(self):
        if self.client is not None:
            await self.client.close()
            self.client = None
