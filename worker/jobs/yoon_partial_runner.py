"""Recognition and staging for the six sealed partial Yoon families.

Everything private (performer names, source links, recognitions) lives in the
development database behind narrow worker functions. This module prints only
counts, because the repository and its workflow logs are public.

  python -m worker.jobs.yoon_partial_runner recognize   # one contiguous shard
  python -m worker.jobs.yoon_partial_runner stage       # cluster + enrich + stage

Environment: DATABASE_URL_DIRECT, WORKER_DEPLOYMENT_TARGET=development,
YOON_PARTIAL_SET_ID, and for recognize SHARD_INDEX / SHARD_COUNT.

Windows are 30 s every 15 s inside each continuous fragment, full windows only,
so no window ever spans a modeled gap and no silence is ever synthesized.
"""
from __future__ import annotations

import asyncio
import contextlib
from hashlib import sha256
import io
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import uuid

RATE, CHANNELS, WIDTH = 44100, 2, 3
ALIGN = CHANNELS * WIDTH
WINDOW_FRAMES = 30 * RATE
HOP_FRAMES = 15 * RATE
DATA_OFFSET = 5548  # Pinned RIFF data offset of every reviewed master.
SET_IDS = frozenset({
    '68a6bf67-8151-5381-8e0c-dcc106d978c3', '6fce4eb8-27f5-5966-9185-dfc9622fcb35',
    '9ed06b2e-738a-5444-aea1-76efefa9a41e', '0c7bdc16-d885-5d3b-b759-aafab912ee32',
    'bcb95699-4a9c-536b-a1a6-589090680c5b', 'c24afb76-a453-5c85-9a4f-e6de2e151a68'})


def say(message: str) -> None:
    """Counts and stage names only; never names, links or recognitions."""
    print(message, file=sys.__stdout__, flush=True)


def windows(fragments: list[dict]) -> list[dict]:
    """The same grid as ops.yoon_partial_windows, with exact master spans per window."""
    out = []
    for fragment in sorted(fragments, key=lambda f: f['index']):
        if fragment['frames'] < WINDOW_FRAMES:
            continue
        for k in range((fragment['frames'] - WINDOW_FRAMES) // HOP_FRAMES + 1):
            local = k * HOP_FRAMES
            parts, cursor, need = [], 0, WINDOW_FRAMES
            for part in fragment['parts']:
                length = part['end'] - part['start']
                lo, hi = max(local, cursor), min(local + WINDOW_FRAMES, cursor + length)
                if lo < hi:
                    parts.append({'file': part['file'], 'start': part['start'] + lo - cursor,
                                  'end': part['start'] + hi - cursor})
                    need -= hi - lo
                cursor += length
            if need:
                raise RuntimeError('window_outside_fragment')
            out.append({'index': len(out), 'fragment': fragment['index'],
                        'start_frame': fragment['startFrame'] + local, 'parts': parts})
    return out


def wav_bytes(pcm: bytes) -> bytes:
    return (b'RIFF' + struct.pack('<I', len(pcm) + 36) + b'WAVEfmt '
            + struct.pack('<IHHIIHH', 16, 1, CHANNELS, RATE, RATE * ALIGN, ALIGN, WIDTH * 8)
            + b'data' + struct.pack('<I', len(pcm)) + pcm)


def direct_link(url: str) -> str:
    if 'dl=0' in url:
        return url.replace('dl=0', 'dl=1')
    return url + ('&' if '?' in url else '?') + 'dl=1'


def fetch_range(url: str, first: int, last: int, destination: Path) -> None:
    """Download master bytes [first, last] inclusive, resuming; errors stay silent."""
    expected = last - first + 1
    for attempt in range(8):
        have = destination.stat().st_size if destination.exists() else 0
        if have > expected:
            destination.unlink()
            have = 0
        if have == expected:
            return
        with destination.open('ab') as out:
            result = subprocess.run(
                ['curl', '-sL', '--fail', '-m', '3600', '-r', f'{first + have}-{last}', '-o', '-', direct_link(url)],
                stdout=out, stderr=subprocess.DEVNULL)
        if result.returncode == 0 and destination.stat().st_size == expected:
            return
        time.sleep(min(60, 5 * 2 ** attempt))
    raise RuntimeError('source_range_download_failed')


def connect():
    from worker.db import connect as db_connect
    from worker.isolation import validate_database_target
    validate_database_target(os.environ['DATABASE_URL_DIRECT'])
    return db_connect()


def call(name: str, *args):
    placeholders = ','.join(['%s'] * len(args))
    with connect() as conn, conn.cursor() as cur:
        cur.execute(f'SELECT ops.{name}({placeholders}) AS v', args)
        return cur.fetchone()['v']


def set_id() -> str:
    value = str(uuid.UUID(os.environ['YOON_PARTIAL_SET_ID']))
    if value not in SET_IDS:
        raise RuntimeError('sealed_partial_set_required')
    return value


def plan(sid: str) -> tuple[dict, list[dict]]:
    progress = call('yoon_partial_progress', sid)
    if progress is None or progress['released']:
        raise RuntimeError('partial_family_not_open')
    grid = windows(progress['fragments'])
    if len(grid) != progress['expected']:
        raise RuntimeError('window_grid_mismatch')
    return progress, grid


def shard_bounds(total: int, index: int, count: int) -> tuple[int, int]:
    return total * index // count, total * (index + 1) // count


async def recognize() -> int:
    from track_recognizer import TrackRecognizer
    sid = set_id()
    index, count = int(os.environ['SHARD_INDEX']), int(os.environ['SHARD_COUNT'])
    if not 0 <= index < count <= 64:
        raise RuntimeError('shard_bounds')
    progress, grid = plan(sid)
    lo, hi = shard_bounds(len(grid), index, count)
    done = set(progress['done'])
    pending = [w for w in grid[lo:hi] if w['index'] not in done]
    say(f'shard {index + 1}/{count}: windows {lo}-{hi - 1}, {len(pending)} pending')
    if not pending:
        return 0
    links = call('yoon_partial_sources_for', sid)
    work = Path(tempfile.mkdtemp(prefix='yoon-partial-'))
    try:
        # One contiguous byte range per master covers every pending window in the shard.
        spans: dict[str, list[int]] = {}
        for w in pending:
            for part in w['parts']:
                span = spans.setdefault(part['file'], [part['start'], part['end']])
                span[0], span[1] = min(span[0], part['start']), max(span[1], part['end'])
        local = {}
        for name, (start, end) in sorted(spans.items()):
            path = work / f'{len(local)}.pcm'
            fetch_range(links[name], DATA_OFFSET + start * ALIGN, DATA_OFFSET + end * ALIGN - 1, path)
            local[name] = (start, path)
        say(f'downloaded {len(local)} source range(s)')

        def window_pcm(w):
            pcm = bytearray()
            for part in w['parts']:
                base, path = local[part['file']]
                with path.open('rb') as handle:
                    handle.seek((part['start'] - base) * ALIGN)
                    pcm.extend(handle.read((part['end'] - part['start']) * ALIGN))
            if len(pcm) != WINDOW_FRAMES * ALIGN:
                raise RuntimeError('window_size_changed')
            return bytes(pcm)

        recognizer = TrackRecognizer(quiet=True, max_retry_seconds=int(os.getenv('MAX_RETRY_SECONDS', '1800')))
        recorded = failed = 0
        try:
            batch_size = max(1, int(os.getenv('BATCH_SIZE', '10')))
            for start in range(0, len(pending), batch_size):
                segments = []
                for w in pending[start:start + batch_size]:
                    pcm = window_pcm(w)
                    path = work / f'w{w["index"]}.wav'
                    path.write_bytes(wav_bytes(pcm))
                    segments.append({'file': path, 'index': w['index'], 'window': w,
                                     'pcm_sha256': sha256(pcm).hexdigest(),
                                     'timestamp': w['start_frame'] / RATE})
                with contextlib.redirect_stdout(io.StringIO()):
                    results = await recognizer.recognize_batch(segments, total_segments=len(grid))
                for segment, result in zip(segments, results):
                    if not result.is_valid or not isinstance(result.raw_data, dict):
                        failed += 1
                        continue
                    w = segment['window']
                    hit = {'index': w['index'], 'fragment': w['fragment'],
                           'recorded_start_frame': w['start_frame'],
                           'source_manifest_sha256': progress['manifest_sha256'],
                           'response': {'segment_index': w['index'], 'timestamp': segment['timestamp'],
                                        'recognized': bool(result.recognized), 'http_status': 200,
                                        'raw_data': result.raw_data}}
                    call('yoon_partial_record_hit', sid, w['index'], segment['pcm_sha256'],
                         json.dumps(hit))
                    recorded += 1
                say(f'shard {index + 1}/{count}: {recorded + failed}/{len(pending)} attempted, '
                    f'{recorded} recorded, {failed} to retry')
        finally:
            await recognizer.close()
        return 0 if failed == 0 else 3
    finally:
        for path in work.iterdir():
            path.unlink(missing_ok=True)
        work.rmdir()


def cluster(grid: list[dict], hits: list[dict]) -> list[dict]:
    """Identified clusters only, each built inside one fragment on the set clock."""
    from setlist_builder import SetlistBuilder
    by_index = {h['index']: h for h in hits}
    out = []
    for fragment in sorted({w['fragment'] for w in grid}):
        recs = []
        for w in grid:
            if w['fragment'] != fragment:
                continue
            response = by_index[w['index']]['response']
            raw = response['raw_data']
            track = raw.get('track') or {}
            recs.append(SimpleNamespace(
                recognized=response['recognized'], segment_index=w['index'],
                timestamp=w['start_frame'] / RATE, raw_data=raw,
                artist=track.get('subtitle'), track_title=track.get('title'),
                shazam_track_id=track.get('key')))
        first = min(w['start_frame'] for w in grid if w['fragment'] == fragment)
        last = max(w['start_frame'] + WINDOW_FRAMES for w in grid if w['fragment'] == fragment)
        lo, hi = math.ceil(first / RATE), math.floor(last / RATE)
        for track in sorted(SetlistBuilder().build_setlist(recs), key=lambda t: t.start_time):
            track.segment_indices = sorted(track.segment_indices)
            lead = by_index[track.segment_indices[0]]['response']['raw_data']['track']
            # Evidence must name the same track exactly as Shazam returned it.
            track.title, track.artist = lead['title'], lead['subtitle']
            start = max(lo, math.ceil(track.start_time))
            end = min(hi, math.floor(track.end_time))
            if out and out[-1]['fragment'] == fragment and start < out[-1]['end_seconds']:
                if start > out[-1]['start_seconds']:
                    out[-1]['end_seconds'] = start  # Hand over at the next track's first window.
                else:
                    start = out[-1]['end_seconds']
            if end > start:
                out.append({'fragment': fragment, 'track': track, 'start_seconds': start, 'end_seconds': end})
    return out


def stage() -> int:
    from metadata_enricher import MetadataEnricher
    from output_formatter import serialize_track
    sid = set_id()
    progress, grid = plan(sid)
    evidence = call('yoon_partial_hits_for', sid)
    hits = evidence['hits']
    with contextlib.redirect_stdout(io.StringIO()):
        clustered = cluster(grid, hits)
        enricher = MetadataEnricher()
        enriched = enricher.enrich_all_tracks([c['track'] for c in clustered])
        mix_info = {}
        try:
            genres = MetadataEnricher.infer_genre_profile([e.get('metadata', {}) for e in enriched])
            mix_info.update(enricher.enrich_set_artist_profile(progress['name'], expected_genres=genres))
        except Exception:
            pass
    tracks = []
    for position, (c, item) in enumerate(zip(clustered, enriched), start=1):
        t = c['track']
        t.start_time, t.end_time = c['start_seconds'], c['end_seconds']
        metadata = serialize_track(item, position, '')
        metadata.update({'shazam_track_id': t.shazam_track_id, 'isrc': t.isrc})
        tracks.append({'position': position, 'fragment': c['fragment'], 'artist': t.artist, 'title': t.title,
                       'start_seconds': c['start_seconds'], 'end_seconds': c['end_seconds'],
                       'confidence': t.confidence, 'detection_count': len(t.segment_indices),
                       'cluster_density': t.cluster_density, 'cluster_span': t.cluster_span,
                       'segment_indices': t.segment_indices, 'metadata': metadata})
    payload = {'mix_info': mix_info, 'summary': {'trackCount': len(tracks)}, 'tracks': tracks}
    digest = call('yoon_partial_stage_import', sid, evidence['hits_sha256'], json.dumps(payload))
    say(f'staged {len(tracks)} entries from {len(hits)} windows; payload {digest[:12]}')
    return 0


def main(argv: list[str]) -> int:
    if argv == ['recognize']:
        return asyncio.run(recognize())
    if argv == ['stage']:
        return stage()
    if argv == ['shards']:
        sid = set_id()
        _, grid = plan(sid)
        say(json.dumps({'windows': len(grid)}))
        return 0
    raise SystemExit('usage: recognize | stage')


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
