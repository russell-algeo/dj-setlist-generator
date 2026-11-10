"""One shared durable HTTP-429 policy; no transport or provider access here.

Only a completed, verified HTTP 429 earns a throttle credit. Unknown attempts,
transport failures, and other statuses still consume the ordinary safety budget.
"""
from dataclasses import dataclass

POLICY_VERSION = 3
THROTTLE_BASE_SECONDS = 60
THROTTLE_MAX_SECONDS = 3600


@dataclass(frozen=True)
class RetryDirective:
    delay_seconds: float


def actual_throttle(attempt):
    return (attempt.get('state') == 'finished' or attempt.get('outcome') in ('failed', 'valid')) and \
        type((attempt.get('diagnostic') or {}).get('http_status')) is int and \
        attempt['diagnostic']['http_status'] == 429


def non_throttle_attempts(attempts):
    return sum(not actual_throttle(a) for a in attempts)


def throttle_streak(attempts):
    count = 0
    for attempt in reversed(attempts):
        if not actual_throttle(attempt):
            break
        count += 1
    return count


def throttle_delay(count, retry_after=0):
    # Bound the exponent, not Retry-After: a provider's longer wait is binding.
    return max(min(THROTTLE_MAX_SECONDS,
                   THROTTLE_BASE_SECONDS * 2 ** min(max(0, count - 1), 6)),
               retry_after or 0)


def effective_requests(state):
    total, throttles = state['requests'], state.get('throttle_requests', 0)
    if (type(total) is not int or type(throttles) is not int or
            not 0 <= throttles <= total):
        raise RuntimeError('recognition_request_accounting_invalid')
    return total - throttles
