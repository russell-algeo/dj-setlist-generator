"""Finite, persistent backpressure policy for the fixed private Jackson queue.

No network or storage code. Callers supply database time and persist the returned
state transactionally before another provider request can be reserved.
"""
from __future__ import annotations

WORKFLOW_REQUEST_LIMIT = 24
WORKFLOW_SECONDS = 60 * 60
CONTINUATION_LIMIT = 32
TOTAL_REQUEST_LIMIT = WORKFLOW_REQUEST_LIMIT * CONTINUATION_LIMIT
WINDOW_ATTEMPT_LIMIT = 8
MAX_AGE_SECONDS = 7 * 24 * 60 * 60
INITIAL_SPACING = 30
MAX_SPACING = 180
COOLDOWN_FLOOR = 300
COOLDOWN_CEILING = 3600


def initial_state(now):
    return dict(version=1, created_at=now, continuations=0, requests=0,
                spacing_seconds=INITIAL_SPACING, next_allowed_at=now,
                consecutive_limits=0)


def may_reserve(state, *, now, session_started, session_requests, window_attempts):
    if now - state['created_at'] >= MAX_AGE_SECONDS:
        return 'lifetime_time_budget'
    if state['requests'] >= TOTAL_REQUEST_LIMIT:
        return 'lifetime_request_budget'
    if state['continuations'] > CONTINUATION_LIMIT:
        return 'continuation_budget'
    if now - session_started >= WORKFLOW_SECONDS:
        return 'workflow_time_budget'
    if session_requests >= WORKFLOW_REQUEST_LIMIT:
        return 'workflow_request_budget'
    if window_attempts >= WINDOW_ATTEMPT_LIMIT:
        return 'window_attempt_budget'
    if now < state['next_allowed_at']:
        return 'cooldown'
    return None


def after_response(state, *, now, rate_limited, valid, retry_seconds=None,
                   retry_format='absent'):
    updated = dict(state)
    reason = None
    if rate_limited:
        updated['consecutive_limits'] += 1
        updated['spacing_seconds'] = min(MAX_SPACING, state['spacing_seconds'] * 2)
        delay = min(COOLDOWN_CEILING,
                    COOLDOWN_FLOOR * 2 ** min(updated['consecutive_limits'] - 1, 4))
        updated['next_allowed_at'] = now + delay
        if updated['consecutive_limits'] >= 4:
            reason = reason or 'sustained_rate_limit_pause'
    elif valid:
        updated['consecutive_limits'] = 0
        # Successful calls do not undo the learned slower request spacing.
        updated['next_allowed_at'] = now + updated['spacing_seconds']
    else:
        updated['next_allowed_at'] = now + max(COOLDOWN_FLOOR, updated['spacing_seconds'])
        reason = 'provider_error_pause'
    # Retry-After also applies to e.g. HTTP 503, not just 429. Never shorten it.
    if retry_seconds is not None:
        updated['next_allowed_at'] = max(updated['next_allowed_at'], now+retry_seconds)
    if retry_format == 'invalid':
        reason = 'retry_after_needs_review'
    return updated, reason
