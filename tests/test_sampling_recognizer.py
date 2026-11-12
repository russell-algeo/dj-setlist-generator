"""Actual common recognizer/transport, fake SDK and HTTP; no sockets."""
import hashlib
import unittest
from unittest.mock import patch
from track_recognizer import TrackRecognizer
from recognition_transport import RequestAuthorizationError
from tests.test_sampling_study import fixture

class Response:
    status=200;headers={}
    async def __aenter__(self):return self
    async def __aexit__(self,*a):pass
    async def json(self):return {'matches':[]}
class Session:
    def __init__(self,events):self.events=events
    def request(self,*a,**k):self.events.append('wire');return Response()
    async def close(self):pass
class CommonRecognizerTests(unittest.IsolatedAsyncioTestCase):
    async def test_bytes_reach_sdk_before_committed_hook_and_wire(self):
        m,audio=fixture();events=[]
        r=TrackRecognizer(single_attempt=True,quiet=True,before_attempt=lambda s:events.append('reserve') or 'ticket',on_attempt=lambda *a:events.append('finish'))
        async def sdk(value):
            self.assertIs(value,audio);events.append('fingerprint');return await r.transport.request('POST','https://synthetic.invalid',json={})
        r.shazam.recognize=sdk;r.transport.session_factory=lambda **k:Session(events)
        try:
            with patch('socket.socket.connect',side_effect=AssertionError('offline')),patch('socket.getaddrinfo',side_effect=AssertionError('offline')):
                result=await r.recognize_segment_with_backoff({'index':0,'timestamp':0,'audio_bytes':audio,'audio_sha256':hashlib.sha256(audio).hexdigest()})
            self.assertTrue(result.is_valid);self.assertEqual(events,['fingerprint','reserve','wire','finish'])
        finally:await r.close()
    async def test_bad_bytes_refuse_before_sdk_or_wire(self):
        r=TrackRecognizer(single_attempt=True,quiet=True)
        try:
            with self.assertRaises(RequestAuthorizationError):await r.recognize_segment_with_backoff({'index':0,'timestamp':0,'audio_bytes':b'bad','audio_sha256':'a'*64})
        finally:await r.close()
    def test_file_path_default_unchanged(self):self.assertEqual(TrackRecognizer._audio_input({'file':'path.mp3'}),'path.mp3')
