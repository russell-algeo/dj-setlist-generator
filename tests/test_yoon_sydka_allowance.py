"""Pure offline checks. Never load live credentials or contact providers."""
import copy
import unittest
from unittest.mock import patch
from worker.jobs import yoon_sydka_allowance as allowance
from worker.jobs.yoon_resume_policy import may_reserve, initial_state, MAX_AGE_SECONDS, CONTINUATION_LIMIT
from worker.jobs.yoon_sources import CATALOG


class SydkaAllowanceTests(unittest.TestCase):
    def setUp(self):
        self.digest = 'a' * 64
        self.pin = patch.object(allowance, 'AUDIO_SHA256', self.digest)
        self.pin.start()
        self.addCleanup(self.pin.stop)
        self.attempts = [dict(state='finished', number=i + 1, ticket=f'ticket-{i}',
                              diagnostic=dict(http_status=429, retry_after_format='absent'))
                         for i in range(8)]
        self.grant = dict(version=1, grant_id=allowance.GRANT_ID, run_id=allowance.RUN_ID,
                          source_id=allowance.SOURCE_ID, segment_index=168,
                          base_attempts=8, additional_attempts=4, max_attempts=12,
                          audio_sha256=self.digest, prior_attempts=copy.deepcopy(self.attempts),
                          reviewed_snapshot_sha256='b'*64, terminal_evidence_sha256='c'*64,
                          granted_at=10)
        self.state = initial_state(0) | dict(source_id=allowance.SOURCE_ID,
                     source_pins=CATALOG[allowance.SOURCE_ID].pins(), audio_sha256=self.digest,
                     expected_audio_sha256=self.digest, sydka_window_allowance=self.grant)
    def limit(self, state=None, attempts=None, **kw):
        return allowance.window_attempt_limit(self.state if state is None else state,
                    **(dict(run_id=allowance.RUN_ID,index=168,
                           attempts=self.attempts if attempts is None else attempts)|kw))
    def test_default_and_other_windows_stay_eight(self):
        self.assertEqual(self.limit(state={}),8)
        self.assertEqual(self.limit(index=167,attempts=[]),8)
        self.assertEqual(self.limit(index=169,attempts=[]),8)
    def test_four_additional_then_stop_without_mutation(self):
        original=copy.deepcopy((self.state,self.attempts))
        for count in range(8,13):
            attempts=self.attempts+[{'state':'finished'}]*(count-8)
            cap=self.limit(attempts=attempts)
            self.assertEqual(cap,12)
            reason=may_reserve(self.state,now=50,session_started=0,session_requests=0,
                windows=359,window_attempts=count,window_attempt_limit=cap)
            self.assertEqual(reason,'window_attempt_budget' if count==12 else None)
        self.assertEqual((self.state,self.attempts),original)
    def test_scope_and_fields_fail_closed(self):
        for key,value in [('version',True),('segment_index',169),('additional_attempts',5),
                          ('max_attempts',13),('base_attempts',0),('run_id','other'),
                          ('source_id','other'),('audio_sha256','b'*64),('grant_id','new'),
                          ('granted_at',float('inf')),('granted_at',True),
                          ('reviewed_snapshot_sha256','invalid'),('terminal_evidence_sha256',None)]:
            with self.subTest(key=key),self.assertRaises(RuntimeError):
                state=copy.deepcopy(self.state);state[allowance.GRANT_KEY][key]=value
                self.limit(state=state)
        for key in self.grant:
            with self.subTest(missing=key),self.assertRaises(RuntimeError):
                state=copy.deepcopy(self.state);del state[allowance.GRANT_KEY][key]
                self.limit(state=state)
        with self.assertRaises(RuntimeError):
            self.limit(state=self.state|{allowance.GRANT_KEY:self.grant|{'refill':True}})
        for key,value in [('source_id','other'),('source_pins',{}),('audio_sha256','b'*64),
                          ('expected_audio_sha256','b'*64)]:
            with self.subTest(state=key),self.assertRaises(RuntimeError):
                self.limit(state=self.state|{key:value})
        with self.assertRaises(RuntimeError):self.limit(run_id='other')
    def test_original_eight_cannot_be_reset_or_changed(self):
        for attempts in [[], self.attempts[:7],self.attempts+[{}]*5,
                         [self.attempts[0]|{'ticket':'new'}]+self.attempts[1:]]:
            with self.assertRaises(RuntimeError):self.limit(attempts=attempts)
        for bad in [None, [], self.attempts[:7], [dict(state='finished',diagnostic={'http_status':200})]*8,
                    [dict(state='in_flight',diagnostic={'http_status':429})]*8,
                    [dict(state='finished',diagnostic={'http_status':429,'retry_after_format':'invalid'})]*8]:
            with self.assertRaises(RuntimeError):
                self.limit(state=self.state|{allowance.GRANT_KEY:self.grant|{'prior_attempts':bad}})
    def test_global_caps_and_cooldown_unchanged(self):
        base=dict(now=50,session_started=0,session_requests=0,windows=359,
                  window_attempts=8,window_attempt_limit=self.limit())
        for changes,reason in [({'requests':359*8},'lifetime_request_budget'),
                               ({'continuations':CONTINUATION_LIMIT+1},'continuation_budget'),
                               ({'next_allowed_at':60},'cooldown')]:
            self.assertEqual(may_reserve(self.state|changes,**base),reason)
        self.assertEqual(may_reserve(self.state,**base,next_allowed_at=60),'cooldown')
        self.assertEqual(may_reserve(self.state,**(base|{'now':MAX_AGE_SECONDS})),'lifetime_time_budget')
        self.assertEqual(may_reserve(self.state,**(base|{'now':3535})),'workflow_time_budget')
        for bad in [True,9,13,'12',0]:
            with self.assertRaises(RuntimeError):
                may_reserve(self.state,**(base|{'window_attempt_limit':bad}))
    def test_replay_cannot_refill_count(self):
        count=12
        for continuation in [2,3,4]:
            state=copy.deepcopy(self.state)|{'continuations':continuation}
            self.assertEqual(may_reserve(state,now=50,session_started=0,session_requests=0,
                windows=359,window_attempts=count,
                window_attempt_limit=self.limit(state=state,attempts=self.attempts+[{}]*4)),
                'window_attempt_budget')

if __name__=='__main__':unittest.main()
