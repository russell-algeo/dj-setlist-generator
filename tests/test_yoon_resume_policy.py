import unittest
from worker.jobs.yoon_resume_policy import *


class ResumePolicyTests(unittest.TestCase):
    def test_limits_are_finite_without_small_continuation_request_cap(self):
        state = initial_state(0)
        base = dict(now=0, session_started=0, session_requests=240, window_attempts=0)
        self.assertIsNone(may_reserve(state, **base))
        for key,value,reason in [('window_attempts',8,'window_attempt_budget'),
                                  ('now',3535,'workflow_time_budget')]:
            self.assertEqual(may_reserve(state,**(base|{key:value})),reason)
        self.assertEqual(may_reserve(state|{'requests':TOTAL_REQUEST_LIMIT},**base),'lifetime_request_budget')
        self.assertEqual(may_reserve(state|{'continuations':CONTINUATION_LIMIT+1},**base),'continuation_budget')
        self.assertEqual(may_reserve(state,**(base|{'now':MAX_AGE_SECONDS})),'lifetime_time_budget')

    def test_only_persisted_provider_wait_blocks_admission(self):
        state=initial_state(0)
        base=dict(now=50,session_started=0,session_requests=100,window_attempts=1)
        self.assertIsNone(may_reserve(state,**base))
        self.assertEqual(may_reserve(state,**base,next_allowed_at=60),'cooldown')
        self.assertEqual(may_reserve(state|{'next_allowed_at':90},**base),'cooldown')
        self.assertIsNone(may_reserve(state,**(base|{'now':60}),next_allowed_at=60))

    def test_no_private_backoff_or_success_spacing(self):
        state=initial_state(10)
        self.assertEqual(state['spacing_seconds'],0)
        self.assertEqual(state['next_allowed_at'],10)
        self.assertEqual(TOTAL_REQUEST_LIMIT,479*WINDOW_ATTEMPT_LIMIT)

if __name__=='__main__':unittest.main()
