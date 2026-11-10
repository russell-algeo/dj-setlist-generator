import copy
import unittest
from tests import test_yoon_spotify_enrich as legacy
from worker.jobs.yoon_spotify_enrich import validate, digest, HIGHKIN_RUN, HIGHKIN_SCOPE, DONALD_MEMBERS, Store
from worker.jobs.yoon_sources import HIGHKIN

class HighkinEnrichmentTests(unittest.TestCase):
    def fixture(self):
        row,state,hits,expected=legacy.PrivateEnrichmentTests().fixture()
        descriptor=dict(HIGHKIN.pins(),source_id=HIGHKIN.id,recognition_mode='resumable')
        row.update(HIGHKIN_SCOPE,id=HIGHKIN_RUN,source_metadata={'yoon_fixed_input':descriptor})
        state.update(initialization_mode='fresh',fresh_source_initialized=True,source_id=HIGHKIN.id,
            source_pins=HIGHKIN.pins(),members=copy.deepcopy(DONALD_MEMBERS),audio_sha256='a'*64,expected_audio_sha256='a'*64)
        state['clustered_setlist']=state['clustered_setlist'][:3]
        expected.update(HIGHKIN_SCOPE,source_digest=digest(descriptor),cluster_digest=digest(state['clustered_setlist']))
        return row,state,hits,expected

    def test_uses_finite_fresh_run(self):
        self.assertEqual(len(validate(*self.fixture())),3)
        with self.assertRaises(RuntimeError):Store({},'1','1','arbitrary-run')

    def test_rejects_malformed_fresh_evidence(self):
        mutations=[lambda r,s,h,e:r.update(id='arbitrary-run'),lambda r,s,h,e:r.update(target_set_id='other'),
          lambda r,s,h,e:s.update(origin={'valid_windows':0}),lambda r,s,h,e:s.update(provenance_seeded=True),
          lambda r,s,h,e:s.update(fresh_source_initialized=False),lambda r,s,h,e:s.update(audio_sha256='b'*64),
          lambda r,s,h,e:s.update(members=[]),lambda r,s,h,e:s.update(source_pins={}),
          lambda r,s,h,e:s['source_pins']['source_parts'][0].update(start_frame=535148353),
          lambda r,s,h,e:r['source_metadata']['yoon_fixed_input'].pop('source_parts'),
          lambda r,s,h,e:h[0]['raw_data']['private_jackson_v2']['response'].update(http_status=None),
          lambda r,s,h,e:h[0]['raw_data']['private_jackson_v2']['attempts'][-1]['diagnostic'].update(http_status=429),
          lambda r,s,h,e:h[0]['raw_data']['private_jackson_v2']['attempts'][-1]['diagnostic'].update(outcome='failed'),
          lambda r,s,h,e:h.pop()]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                args=self.fixture();mutate(*args)
                with self.assertRaises(RuntimeError):validate(*args)

    def test_prior_rate_limit_is_retained_not_counted(self):
        args=self.fixture();attempts=args[2][0]['raw_data']['private_jackson_v2']['attempts']
        old=copy.deepcopy(attempts[0]);old['diagnostic'].update(http_status=429,outcome='rate_limited');attempts.insert(0,old)
        self.assertEqual(len(validate(*args)),3);self.assertEqual(len(attempts),2)
