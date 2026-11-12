import asyncio
import copy
import hashlib
import io
import unittest
import wave
from types import SimpleNamespace
from worker.jobs.sampling_study_manifest import validate,validate_audio,SOURCES,ARMS,digest
from worker.jobs.sampling_study import run_prepared,receipt_for
from worker.jobs.sampling_study_store import StudyFence
from worker.pipeline.models import Recognition


def fixture():
    f=io.BytesIO()
    with wave.open(f,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0'*960000)
    data=f.getvalue();h=hashlib.sha256(data).hexdigest()
    manifest={'version':1,'reference_sha256':'a'*64,'recognizer':{'sdk':'0.9.0','core':'2.0.0','country':'US','input_seconds':30,'fingerprint_seconds':12},
       'sources':{n:{'platform_id':p,'start_seconds':s,'duration_seconds':600,'pcm_sha256':'b'*64} for n,(p,s) in SOURCES.items()},
       'windows':[{'id':f'{n}_{t}','source':n,'start_seconds':t,'input_sha256':h,'replicate':False} for n in SOURCES for t in sorted({x for stride in ARMS.values() for x in range(0,571,stride)})]}
    return manifest,data

class ManifestTests(unittest.TestCase):
    def setUp(self):self.m,self.audio=fixture()
    def test_geometry(self):self.assertEqual(len(validate(self.m)),345);validate_audio(self.audio,self.m['windows'][0]['input_sha256'])
    def test_bad_source(self):self.m['sources']['shanti']['start_seconds']=0;self.assertRaises(ValueError,validate,self.m)
    def test_changed_core(self):self.m['recognizer']['fingerprint_seconds']=30;self.assertRaises(ValueError,validate,self.m)
    def test_duplicate(self):self.m['windows'][1]=copy.deepcopy(self.m['windows'][0]);self.assertRaises(ValueError,validate,self.m)
    def test_missing(self):self.m['windows'].pop();self.assertRaises(ValueError,validate,self.m)
    def test_repeat(self):r=dict(self.m['windows'][0],id='repeat1',replicate=True);self.m['windows'].append(r);self.assertEqual(len(validate(self.m)),346);r['input_sha256']='c'*64;self.assertRaises(ValueError,validate,self.m)
    def test_audio_drift(self):self.assertRaises(ValueError,validate_audio,self.audio+b'1',self.m['windows'][0]['input_sha256'])
    def test_audio_wrong_geometry(self):self.assertRaises(ValueError,validate_audio,b'abcd',hashlib.sha256(b'abcd').hexdigest())
    def test_timeout_unknown(self):r=Recognition(0,None,None,None,None,False,0,error_type='RequestTimeout');self.assertEqual(receipt_for(r)['outcome'],'unknown')
    def test_429_not_nomatch(self):r=Recognition(0,None,None,None,None,False,0,error_type='RateLimited',http_status=429);self.assertEqual(receipt_for(r)['outcome'],'throttled')
    def test_no_match_requires_valid(self):r=Recognition(0,None,None,None,{'matches':[]},False,0,http_status=200);self.assertEqual(receipt_for(r)['outcome'],'no_match')

class FakeStore:
    def __init__(self):
        self.manifest,self.audio=fixture();self.windows=validate(self.manifest);self.calls=[];self.done=set();self.released=None
    def completed_ids(self):return self.done
    def reserve(self,id,h):self.calls.append(id);return 'ticket'
    def finish(self,t,r,d):
        if r['outcome'] in ('matched','no_match'):self.done.add(self.calls[-1])
    def release(self,r,transport_drained):self.released=(r,transport_drained)

class MockRecognizer:
    outcome='no_match';closed=False
    def __init__(self,**kw):self.kw=kw;self.closed=False
    async def recognize_segment_with_backoff(self,s):
        t=self.kw['before_attempt'](s)
        r=Recognition(s['timestamp'],None,None,None,{'matches':[]},False,s['index'],http_status=200)
        if self.outcome=='timeout':r.raw_data=None;r.http_status=None;r.error_type='RequestTimeout'
        self.kw['on_attempt'](r,t,0);return r
    async def close(self):self.closed=True

class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_complete_capture_only(self):
        s=FakeStore();r=await run_prepared(s,lambda w:s.audio,recognizer_factory=MockRecognizer,check_versions=False)
        self.assertEqual(r,'complete');self.assertEqual(len(s.calls),345);self.assertEqual(s.released,('complete',True))
    async def test_unknown_stops(self):
        class Timeout(MockRecognizer):outcome='timeout'
        s=FakeStore();r=await run_prepared(s,lambda w:s.audio,recognizer_factory=Timeout,check_versions=False)
        self.assertEqual(r,'paused');self.assertEqual(len(s.calls),1);self.assertFalse(s.done)
    async def test_mutation_never_reserves(self):
        s=FakeStore()
        with self.assertRaises(ValueError):await run_prepared(s,lambda w:b'bad',recognizer_factory=MockRecognizer,check_versions=False)
        self.assertFalse(s.calls);self.assertEqual(s.released,('error',True))
    async def test_lost_commit_ack_never_sends(self):
        s=FakeStore()
        def bad(*a):s.calls.append('possibly committed');raise RuntimeError('lost_ack')
        s.reserve=bad
        with self.assertRaises(RuntimeError):await run_prepared(s,lambda w:s.audio,recognizer_factory=MockRecognizer,check_versions=False)
        self.assertFalse(s.done);self.assertEqual(len(s.calls),1)
    async def test_cancel_drains(self):
        class Cancel(MockRecognizer):
            async def recognize_segment_with_backoff(self,s):self.kw['before_attempt'](s);raise asyncio.CancelledError
        s=FakeStore()
        with self.assertRaises(asyncio.CancelledError):await run_prepared(s,lambda w:s.audio,recognizer_factory=Cancel,check_versions=False)
        self.assertEqual(s.released,('cancelled',True));self.assertFalse(s.done)

if __name__=='__main__':unittest.main()

class ProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_release_waits_for_exit(self):
        import tempfile,sys,time
        from worker.jobs.sampling_study_process import run_supervised
        script="import sys,json,time;json.loads(sys.stdin.readline());print(json.dumps({'op':'release','args':['paused']}),flush=True);sys.stdin.readline();time.sleep(.2)"
        s=FakeStore();s.release=lambda reason,transport_drained:(reason,transport_drained)
        with tempfile.TemporaryDirectory() as d:
            start=time.monotonic();result=await run_supervised(s,d,seconds=1,command=[sys.executable,'-c',script])
        self.assertGreaterEqual(time.monotonic()-start,.2);self.assertEqual(result,('paused',True))
    async def test_hung_native_child_killed_before_release(self):
        import tempfile,sys,os
        from worker.jobs.sampling_study_process import run_supervised
        script="import sys,json,time,os;json.loads(sys.stdin.readline());print(json.dumps({'op':'reserve','args':['x','y']}),flush=True);sys.stdin.readline();time.sleep(100)"
        s=FakeStore();s.reserve=lambda *a:'ticket';released=[];s.release=lambda *a,**k:released.append(k['transport_drained'])
        with tempfile.TemporaryDirectory() as d:
            task=asyncio.create_task(run_supervised(s,d,seconds=1,command=[sys.executable,'-c',script]));await asyncio.sleep(.1);task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(released,[True])
    async def test_false_complete_child_exit_not_success(self):
        import tempfile,sys
        from worker.jobs.sampling_study_process import run_supervised
        script="import sys,json;json.loads(sys.stdin.readline());sys.exit(1)"
        s=FakeStore();s.release=lambda r,transport_drained:setattr(s,'released',(r,transport_drained))
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(StudyFence):await run_supervised(s,d,seconds=1,command=[sys.executable,'-c',script])
        self.assertEqual(s.released,('error',True))

class TransactionEntryTests(unittest.TestCase):
    def test_implicit_transaction_refused(self):
        from worker.jobs.sampling_study_store import StudyStore
        for autocommit,status in [(False,0),(True,2),(None,0)]:
            c=SimpleNamespace(autocommit=autocommit,info=SimpleNamespace(transaction_status=status))
            with self.assertRaisesRegex(StudyFence,'outer_commit'):
                StudyStore(c,'80000000-0000-4000-8000-000000000001','1:1','f'*40)

class MediaParserTests(unittest.TestCase):
    def test_host_boundaries(self):
        from worker.jobs.sampling_study_media import BoundedMedia,MediaFence
        BoundedMedia.host('https://playback.media-streaming.soundcloud.cloud/media')
        for u in ('http://a.sndcdn.com/x','https://sndcdn.com.evil.invalid/x','https://localhost/x','file:///tmp/x'):
            with self.assertRaises(MediaFence):BoundedMedia.host(u)
    def test_plain_finite_playlist(self):
        from worker.jobs.sampling_study_media import BoundedMedia
        b=BoundedMedia();b.get=lambda *a:b'#EXTM3U\n#EXT-X-MAP:URI="init"\n#EXTINF:10,\na\n#EXTINF:9.5,\nb\n#EXT-X-ENDLIST\n'
        parts,init=b.playlist('https://a.sndcdn.com/path/list');self.assertEqual(len(parts),2);self.assertEqual(parts[1][:2],(10,9.5));self.assertEqual(init,'https://a.sndcdn.com/path/init')
    def test_encryption_and_master_rejected(self):
        from worker.jobs.sampling_study_media import BoundedMedia,MediaFence
        for extra in ('#EXT-X-KEY:METHOD=AES-128','#EXT-X-BYTERANGE:1234','#EXT-X-STREAM-INF:x'):
            b=BoundedMedia();b.get=lambda *a,extra=extra:('#EXTM3U\n'+extra+'\n#EXT-X-ENDLIST').encode()
            with self.assertRaises(MediaFence):b.playlist('https://a.sndcdn.com/list')
