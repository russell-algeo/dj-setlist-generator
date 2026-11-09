import unittest
from worker.jobs.yoon_resume_policy import *


class ResumePolicyTests(unittest.TestCase):
    def test_limits_are_finite(self):
        state = initial_state(0)
        base = dict(now=0, session_started=0, session_requests=0, window_attempts=0)
        self.assertIsNone(may_reserve(state, **base))
        for key, value, reason in [
            ('session_requests', 24, 'workflow_request_budget'),
            ('window_attempts', 8, 'window_attempt_budget'),
            ('now', 3600, 'workflow_time_budget'),
        ]:
            self.assertEqual(may_reserve(state, **(base | {key: value})), reason)
        self.assertEqual(may_reserve(state | {'requests': TOTAL_REQUEST_LIMIT}, **base), 'lifetime_request_budget')
        self.assertEqual(may_reserve(state | {'continuations': CONTINUATION_LIMIT + 1}, **base), 'continuation_budget')
        self.assertEqual(may_reserve(state, **(base | {'now': MAX_AGE_SECONDS})), 'lifetime_time_budget')

    def test_cooldown_survives_new_session(self):
        state, reason = after_response(initial_state(0), now=10, rate_limited=True, valid=False)
        self.assertEqual(state['spacing_seconds'], 60)
        self.assertEqual(state['next_allowed_at'], 310)
        self.assertIsNone(reason)
        self.assertEqual(may_reserve(state, now=100, session_started=100,
                                   session_requests=0, window_attempts=1), 'cooldown')
        self.assertIsNone(may_reserve(state, now=310, session_started=100,
                                    session_requests=0, window_attempts=1))

    def test_repeated_limits_back_off_and_pause(self):
        state = initial_state(0)
        for index, delay in enumerate([300, 600, 1200, 2400, 3600]):
            state, reason = after_response(state, now=100, rate_limited=True, valid=False)
            self.assertEqual(state['next_allowed_at'], 100 + delay)
            self.assertLessEqual(state['spacing_seconds'], 180)
            self.assertEqual(reason, 'sustained_rate_limit_pause' if index >= 3 else None)

    def test_provider_wait_is_never_shortened(self):
        state, reason = after_response(initial_state(0), now=10, rate_limited=True,
                                       valid=False, retry_seconds=90000, retry_format='delta_seconds')
        self.assertEqual(state['next_allowed_at'], 90010)
        self.assertIsNone(reason)
        _, reason = after_response(state, now=10, rate_limited=True, valid=False,
                                   retry_format='invalid')
        self.assertEqual(reason, 'retry_after_needs_review')

    def test_success_keeps_learned_spacing_and_errors_never_complete(self):
        state, _ = after_response(initial_state(0), now=0, rate_limited=True, valid=False)
        state, reason = after_response(state, now=300, rate_limited=False, valid=True)
        self.assertEqual(state['spacing_seconds'], 60)
        self.assertEqual(state['consecutive_limits'], 0)
        self.assertEqual(state['next_allowed_at'], 360)
        self.assertIsNone(reason)
        state, reason = after_response(state, now=360, rate_limited=False, valid=False)
        self.assertEqual(reason, 'provider_error_pause')
        self.assertEqual(state['next_allowed_at'], 660)

    def test_non429_retry_after_is_respected(self):
        state,reason = after_response(initial_state(0),now=10,rate_limited=False,
            valid=False,retry_seconds=7200,retry_format='delta_seconds')
        self.assertEqual(state['next_allowed_at'],7210)
        self.assertEqual(reason,'provider_error_pause')
        _,reason = after_response(state,now=10,rate_limited=False,valid=False,retry_format='invalid')
        self.assertEqual(reason,'retry_after_needs_review')


if __name__ == '__main__': unittest.main()
