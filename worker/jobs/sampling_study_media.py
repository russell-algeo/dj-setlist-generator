"""Fixed public pilot excerpts only. No full recording download, auth or provider.

Finite plain HLS AAC fragments; signed locators stay in memory. Decode once to
canonical mono PCM, then serialize exact 30-second WAVs. NOT production MP3
encoding parity. Caller supplies the frozen independent reference hash.
"""
import hashlib,io,json,re,subprocess,time,wave
from pathlib import Path
from urllib.parse import urljoin,urlsplit
from urllib.request import Request,build_opener,HTTPRedirectHandler
from worker.jobs.sampling_study_manifest import SOURCES,ARMS,validate,valid_hash
URLS={'bonobo':'https://soundcloud.com/bonobo/essential-mix','shanti':'https://soundcloud.com/shanticeleste/shanti-celeste-essential-mix-2018-12-08','ben_ufo':'https://soundcloud.com/mixmag-1/the-cover-mix-ben-ufo-1'}

class MediaFence(RuntimeError):pass
class SilentLogger:
    def debug(self,_):pass
    def warning(self,_):pass
    def error(self,_):pass

class BoundedMedia:
    def __init__(self):self.requests=0;self.bytes=0;self.deadline=time.monotonic()+600
    @staticmethod
    def host(url):
        p=urlsplit(url)
        if p.scheme!='https' or not p.hostname or not (p.hostname.endswith('.sndcdn.com') or p.hostname=='playback.media-streaming.soundcloud.cloud'):raise MediaFence('study_media_host')
    def get(self,url,cap):
        self.host(url)
        if self.requests>=210 or time.monotonic()>=self.deadline:raise MediaFence('study_media_budget')
        self.requests+=1
        owner=self
        class SafeRedirect(HTTPRedirectHandler):
            def redirect_request(self,req,fp,code,msg,headers,newurl):
                owner.host(newurl)
                return super().redirect_request(req,fp,code,msg,headers,newurl)
        with build_opener(SafeRedirect()).open(Request(url),timeout=10) as r:
            self.host(r.url);data=r.read(min(cap,64*1024*1024-self.bytes)+1)
        self.bytes+=len(data)
        if len(data)>cap or self.bytes>64*1024*1024:raise MediaFence('study_media_bytes')
        return data
    def playlist(self,url):
        text=self.get(url,1024*1024).decode()
        if not text.startswith('#EXTM3U') or '#EXT-X-ENDLIST' not in text or any(x in text for x in ('#EXT-X-KEY','#EXT-X-BYTERANGE','#EXT-X-STREAM-INF','#EXT-X-DISCONTINUITY')):raise MediaFence('study_media_playlist')
        init=None;items=[];t=0;duration=None
        for line in text.splitlines():
            if line.startswith('#EXT-X-MAP:'):
                m=re.fullmatch(r'#EXT-X-MAP:URI="([^"]+)"',line)
                if init or not m:raise MediaFence('study_media_map')
                init=urljoin(url,m.group(1))
            elif line.startswith('#EXTINF:'):
                duration=float(line.split(':',1)[1].split(',')[0])
                if not 0<duration<=60:raise MediaFence('study_media_duration')
            elif line and not line.startswith('#'):
                if duration is None:raise MediaFence('study_media_duration')
                items.append((t,duration,urljoin(url,line)));t+=duration;duration=None
        return items,init

def prepare(root,reference_sha256,*,expected=None):
    if not valid_hash(reference_sha256):raise MediaFence('study_reference_hash')
    root=Path(root);root.mkdir(exist_ok=False)
    import yt_dlp
    from importlib.metadata import version
    if version('yt-dlp')!='2026.10.26':raise MediaFence('study_extractor_version')
    metadata_calls=0
    class Extractor(yt_dlp.YoutubeDL):
        def urlopen(self,*a,**k):
            nonlocal metadata_calls
            metadata_calls+=1
            if metadata_calls>40 or time.monotonic()>=client.deadline:raise MediaFence('study_metadata_budget')
            return super().urlopen(*a,**k)
    client=BoundedMedia()
    opts={'quiet':True,'no_warnings':True,'logger':SilentLogger(),'cachedir':False,'socket_timeout':10,'retries':0,'extractor_retries':0,'skip_download':True,'noplaylist':True,'extract_flat':True,'usenetrc':False,'cookiefile':None,'extractor_args':{'soundcloud':{'formats':['hls_aac']}}}
    m={'version':1,'reference_sha256':reference_sha256,'recognizer':{'sdk':'0.9.0','core':'2.0.0','country':'US','input_seconds':30,'fingerprint_seconds':12},'sources':{},'windows':[]}
    with Extractor(opts) as ydl:
        for name,(platform,start) in SOURCES.items():
            info=ydl.extract_info(URLS[name],download=False,process=False)
            if str(info['id'])!=platform:raise MediaFence('study_source_identity')
            choices=[f for f in info.get('formats',[]) if f.get('format_id')=='hls_aac_160k' and f.get('ext')=='m4a' and str(f.get('protocol','')).startswith('m3u8')]
            if len(choices)!=1:raise MediaFence('study_source_format')
            parts,init=client.playlist(choices[0]['url']);parts=[p for p in parts if p[0]<start+600 and p[0]+p[1]>start]
            if not parts or len(parts)>64:raise MediaFence('study_excerpt_bounds')
            encoded=root/(name+'.m4a')
            with encoded.open('xb') as f:
                if init:f.write(client.get(init,1024*1024))
                for _,__,url in parts:f.write(client.get(url,2*1024*1024))
            pcmfile=root/(name+'.pcm')
            p=subprocess.run(['ffmpeg','-v','error','-nostdin','-protocol_whitelist','file,pipe','-i',str(encoded),'-ss',str(start-parts[0][0]),'-t','600','-vn','-sn','-dn','-ac','1','-ar','16000','-f','s16le',str(pcmfile)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=60)
            if p.returncode or pcmfile.stat().st_size!=19200000:raise MediaFence('study_decode_geometry')
            pcm=pcmfile.read_bytes();m['sources'][name]={'platform_id':platform,'start_seconds':start,'duration_seconds':600,'pcm_sha256':hashlib.sha256(pcm).hexdigest()}
            for t in sorted({t for stride in ARMS.values() for t in range(0,571,stride)}):
                out=io.BytesIO()
                with wave.open(out,'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(pcm[t*32000:(t+30)*32000])
                data=out.getvalue();wid=f'{name}_{t}';(root/(wid+'.wav')).write_bytes(data)
                m['windows'].append({'id':wid,'source':name,'start_seconds':t,'input_sha256':hashlib.sha256(data).hexdigest(),'replicate':False})
    # Fixed seeded order, chosen before any provider result. Byte-identical shared
    # grid inputs remain one physical request. No repeats added automatically.
    import random
    random.Random(20261112).shuffle(m['windows']);validate(m)
    if expected is not None and m!=expected:raise MediaFence('study_prepared_source_changed')
    (root/'manifest.json').write_text(json.dumps(m,sort_keys=True)+'\n')
    receipt={'metadata_request_entries':metadata_calls,'media_request_entries':client.requests,'media_bytes':client.bytes,'provider_calls':0,
       'decoder':subprocess.check_output(['ffmpeg','-version'],text=True).splitlines()[0],'encoding':'canonical mono16k PCM WAV, not production MP3'}
    (root/'preparation.json').write_text(json.dumps(receipt)+'\n')
    return m
