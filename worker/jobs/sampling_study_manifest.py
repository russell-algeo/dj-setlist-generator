"""Fixed, hash-bound study input contract. No provider or database imports."""
import hashlib
import io
import json
import math
import wave

SOURCES = {'bonobo': ('145502026', 180), 'shanti': ('625904337', 5100), 'ben_ufo': ('424168008', 0)}
ARMS = {'stride15': 15, 'stride12': 12, 'stride6': 6}

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def valid_hash(value):
    return isinstance(value,str) and len(value)==64 and all(x in '0123456789abcdef' for x in value)

def validate(manifest):
    if not isinstance(manifest,dict) or set(manifest)!={'version','sources','windows','recognizer','reference_sha256'}:
        raise ValueError('study_manifest_shape')
    if manifest['version']!=1 or not valid_hash(manifest['reference_sha256']):
        raise ValueError('study_manifest_version_or_reference')
    if manifest['recognizer'] != {'sdk':'0.9.0','core':'2.0.0','country':'US','input_seconds':30,'fingerprint_seconds':12}:
        raise ValueError('study_recognizer_changed')
    if set(manifest['sources'])!=set(SOURCES):raise ValueError('study_sources_changed')
    for name,(platform_id,start) in SOURCES.items():
        row=manifest['sources'][name]
        if (set(row)!={'platform_id','start_seconds','duration_seconds','pcm_sha256'} or
            row['platform_id']!=platform_id or type(row['start_seconds']) is not int or row['start_seconds']!=start or
            row['duration_seconds']!=600 or not valid_hash(row['pcm_sha256'])):raise ValueError('study_source_binding')
    windows=manifest['windows']
    if not isinstance(windows,list) or not 345<=len(windows)<=357:raise ValueError('study_window_count')
    expected={(name,t) for name in SOURCES for t in sorted({t for stride in ARMS.values() for t in range(0,571,stride)})}
    seen=set();ids=set();repeats=0
    for w in windows:
        if not isinstance(w,dict) or set(w)!={'id','source','start_seconds','input_sha256','replicate'}:raise ValueError('study_window_shape')
        if not isinstance(w['id'],str) or len(w['id'])>80 or not w['id'].replace('_','').replace('-','').isalnum() or w['id'] in ids:raise ValueError('study_window_identity')
        ids.add(w['id']); key=(w['source'],w['start_seconds'])
        if key not in expected or type(w['start_seconds']) is not int or not valid_hash(w['input_sha256']) or type(w['replicate']) is not bool:raise ValueError('study_window_binding')
        if w['replicate']:repeats+=1
        elif key in seen:raise ValueError('study_duplicate_window')
        else:seen.add(key)
    if seen!=expected or repeats>12:raise ValueError('study_grid_incomplete')
    # Repeats must be the exact same immutable input, never a different crop.
    originals={(w['source'],w['start_seconds']):w['input_sha256'] for w in windows if not w['replicate']}
    if any(w['input_sha256']!=originals[(w['source'],w['start_seconds'])] for w in windows):raise ValueError('study_repeat_input_changed')
    return {w['id']:w for w in windows}

def validate_audio(data,expected_hash):
    if type(data) is not bytes or not 44<=len(data)<=1000000 or hashlib.sha256(data).hexdigest()!=expected_hash:raise ValueError('study_input_digest')
    with wave.open(io.BytesIO(data),'rb') as f:
        if (f.getnchannels(),f.getsampwidth(),f.getframerate(),f.getnframes(),f.getcomptype())!=(1,2,16000,480000,'NONE'):raise ValueError('study_input_geometry')
        if len(f.readframes(480001))!=960000:raise ValueError('study_input_truncated')
