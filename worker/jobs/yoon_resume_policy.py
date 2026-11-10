"""Finite storage/continuation budgets for private recognition.

Request pacing and retries belong to TrackRecognizer, shared with ordinary DJ
runs. This module does not implement a private provider retry strategy.
"""
from __future__ import annotations
from worker.jobs.yoon_sources import CATALOG
from recognition_retry_policy import POLICY_VERSION, effective_requests

WORKFLOW_SECONDS = 60 * 60
CONTINUATION_LIMIT = 32
WINDOW_ATTEMPT_LIMIT = 8
TOTAL_REQUEST_LIMIT = 479 * WINDOW_ATTEMPT_LIMIT
MAX_AGE_SECONDS = 7 * 24 * 60 * 60


def initial_state(now):
    return dict(version=1, created_at=now, continuations=0, requests=0,
                spacing_seconds=0, next_allowed_at=now, consecutive_limits=0)


def may_reserve(state, *, now, session_started, session_requests, window_attempts,
                next_allowed_at=0, windows=479, window_attempt_limit=WINDOW_ATTEMPT_LIMIT):
    if type(windows) is not int or windows not in {source.windows for source in CATALOG.values()}:
        raise RuntimeError('private_window_budget_invalid')
    if type(window_attempt_limit) is not int or window_attempt_limit not in (8, 12):
        raise RuntimeError('private_window_attempt_limit_invalid')
    durable = state.get('throttle_policy_version') == POLICY_VERSION
    if not durable and now + 65 >= state['created_at'] + MAX_AGE_SECONDS:
        return 'lifetime_time_budget'
    if (effective_requests(state) if durable else state['requests']) >= windows * WINDOW_ATTEMPT_LIMIT:
        return 'lifetime_request_budget'
    if not durable and state['continuations'] > CONTINUATION_LIMIT:
        return 'continuation_budget'
    if now + 65 >= session_started + WORKFLOW_SECONDS:
        return 'workflow_time_budget'
    if window_attempts >= window_attempt_limit:
        return 'window_attempt_budget'
    # Honor a previously persisted provider wait through the policy transition.
    if now < max(state.get('next_allowed_at', 0), next_allowed_at):
        return 'cooldown'
    return None
