"""Offline exact429 accounting and bounded common-engine continuation cases."""
from unittest import TestCase
from recognition_retry_policy import (actual_throttle, non_throttle_attempts,
    throttle_streak, throttle_delay, effective_requests)
from worker.jobs.shared_recognition import budget_reason
from worker.jobs.yoon_resume_policy import may_reserve
from recognition_transport import classify_error, ProviderHTTPError


def finished(status=429):
    return {'state':'finished','diagnostic':{'http_status':status}}


class PolicyTests(TestCase):
    def test_exponential_and_binding_retry_after(self):
        self.assertEqual([throttle_delay(i) for i in range(1,10)],
                         [60,120,240,480,960,1920,3600,3600,3600])
        self.assertEqual(throttle_delay(999999,72000),72000)
        self.assertEqual(throttle_delay(1,0),60)

    def test_only_finished_exact_429_is_credited(self):
        records=[finished()]*20+[finished(503),{}, {'state':'in_flight','diagnostic':{'http_status':429}}, finished('429')]
        self.assertEqual(non_throttle_attempts(records),4)
        self.assertEqual(throttle_streak(records),0)
        self.assertEqual(throttle_streak(records+[finished()]*7),7)
        self.assertFalse(actual_throttle({'state':'finished','diagnostic':{'was_rate_limited':True}}))
        self.assertEqual(effective_requests({'requests':30,'throttle_requests':20}),10)
        for state in ({'requests':10,'throttle_requests':11},{'requests':True}):
            with self.assertRaises(RuntimeError):effective_requests(state)

    def test_sdk_label_not_actual_status(self):
        from shazamio.exceptions import RateLimited
        error=RateLimited('synthetic')
        self.assertIsNone(classify_error(error).http_status)
        error.__cause__=ProviderHTTPError(429)
        self.assertEqual(classify_error(error).http_status,429)

    def test_long_lived_throttles_not_terminal(self):
        s=dict(policy_version=3,throttle_policy_version=3,requests=90000,throttle_requests=89999,
               continuations=900,created_at=1,session_started=1000000,request_limit=8)
        self.assertIsNone(budget_reason(s,1000001))
        self.assertIsNone(may_reserve(s,now=1000001,session_started=1000000,
            session_requests=0,window_attempts=1))
        self.assertEqual(budget_reason(s,1003600),'workflow_time_budget')
        self.assertEqual(may_reserve(s,now=1000001,session_started=1000000,
            session_requests=0,window_attempts=8),'window_attempt_budget')

    def test_in_flight_budget_is_provisional(self):
        s=dict(policy_version=3,requests=8,throttle_requests=0,in_flight=True,
               continuations=1,created_at=1,session_started=100,request_limit=8)
        self.assertEqual(budget_reason(s,101),'recognition_requests_in_flight')
        s.update(throttle_requests=1,in_flight=False)
        self.assertIsNone(budget_reason(s,101))
        s.update(throttle_requests=0)
        self.assertEqual(budget_reason(s,101),'lifetime_request_budget')
