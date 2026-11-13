"""Bounded D07 sampling comparison on one sealed partial Yoon family.

Arm A is the evidence already recorded by the yoon-partial run: 30 s windows
every 15 s. The SDK fingerprints only the centred 12 s of each window, so arm A
leaves 3 s interior gaps. Arm B re-recognizes the same master audio with 30 s
windows every 12 s, which tiles those centred 12 s analyses contiguously.

Both arms use the identical encoding and recognizer path as the production
yoon-partial runner (24-bit stereo 44.1 kHz WAV cut from the pinned master,
same TrackRecognizer and SDK pins) and the same clustering. Only the hop differs.

Safety bounds:
  * Read-only on the database. Arm B results stay in process memory and are
    never written anywhere; the public log carries counts only.
  * Arm B uses the production throttle-aware retry path unchanged (exponential
    429 backoff, Retry-After, shared cooldown). Throttling is expected and is
    survived, not treated as failure; unresolved windows are retried in further
    passes until STUDY_DEADLINE_SECONDS. Arm B is capped by MAX_STUDY_WINDOWS.
  * Released families keep their progress/evidence readable but seal source
    links, so the master link map may come from the SAMPLING_SOURCE_LINKS secret.

  python -m worker.jobs.yoon_sampling_compare
Environment: DATABASE_URL_DIRECT, WORKER_DEPLOYMENT_TARGET=development,
YOON_PARTIAL_SET_ID, optional SAMPLING_SOURCE_LINKS.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time

from recognition_retry_policy import throttle_delay
from worker.jobs import yoon_partial_runner as base

STUDY_HOP_FRAMES = 12 * base.RATE
MAX_STUDY_WINDOWS = int(os.getenv('MAX_STUDY_WINDOWS', '600'))
STUDY_DEADLINE_SECONDS = int(os.getenv('STUDY_DEADLINE_SECONDS', '7800'))
MAX_RETRY_SECONDS = int(os.getenv('MAX_RETRY_SECONDS', '1800'))


class Inconclusive(RuntimeError):
    pass


def study_windows(fragments: list[dict], hop: int) -> list[dict]:
    """base.windows with a different hop: same fragment rules, full windows only."""
    saved = base.HOP_FRAMES
    base.HOP_FRAMES = hop
    try:
        return base.windows(fragments)
    finally:
        base.HOP_FRAMES = saved


def source_links(sid: str, progress: dict) -> dict:
    """DB links while the family is open; after release the DB seals them, so the
    owner's master link map comes from the SAMPLING_SOURCE_LINKS secret instead."""
    if not progress['released']:
        return base.call('yoon_partial_sources_for', sid)
    raw = os.environ.get('SAMPLING_SOURCE_LINKS') or ''
    if not raw:
        raise SystemExit('family released and SAMPLING_SOURCE_LINKS not configured')
    supplied = {v['name']: v['href'] for v in json.loads(raw)['links']}
    needed = {part['file'] for f in progress['fragments'] for part in f['parts']}
    missing = needed - supplied.keys()
    if missing:
        raise SystemExit(f'{len(missing)} master link(s) missing from SAMPLING_SOURCE_LINKS')
    return {name: supplied[name] for name in needed}


def identified(grid: list[dict], hits: list[dict]) -> dict:
    with contextlib.redirect_stdout(io.StringIO()):  # SetlistBuilder prints titles
        entries = base.cluster(grid, hits)
    recognized = [h for h in hits if h['response']['recognized']]
    keys = {h['response']['raw_data']['track']['key'] for h in recognized}
    return {'windows': len(grid), 'recognized_windows': len(recognized),
            'distinct_tracks': len(keys), 'identified_entries': len(entries)}


def shared_window_agreement(grid_a, hits_a, grid_b, hits_b) -> dict:
    """Catalog-drift check, counts only: windows at the same start in both grids."""
    def by_start(grid, hits):
        index = {h['index']: h for h in hits}
        out = {}
        for w in grid:
            r = index[w['index']]['response']
            out[(w['fragment'], w['start_frame'])] = (r['raw_data']['track']['key']
                                                      if r['recognized'] else None)
        return out
    a, b = by_start(grid_a, hits_a), by_start(grid_b, hits_b)
    shared = a.keys() & b.keys()
    return {'shared_windows': len(shared), 'same_result': sum(a[k] == b[k] for k in shared)}


async def recognize_arm_b(grid: list[dict], links: dict, stats: dict) -> list[dict]:
    """Recognize every arm B window through the production throttle-aware path.

    The recognizer's own exponential 429 backoff, Retry-After handling and
    shared cooldown are used unchanged. Windows still unresolved when a retry
    budget ends are retried in further passes until the overall deadline.
    """
    from track_recognizer import TrackRecognizer
    deadline = time.monotonic() + STUDY_DEADLINE_SECONDS
    work = Path(tempfile.mkdtemp(prefix='yoon-sampling-'))
    done: dict[int, dict] = {}
    try:
        spans: dict[str, list[int]] = {}
        for w in grid:
            for part in w['parts']:
                span = spans.setdefault(part['file'], [part['start'], part['end']])
                span[0], span[1] = min(span[0], part['start']), max(span[1], part['end'])
        for name in sorted(spans):
            header = work / 'header.bin'
            header.unlink(missing_ok=True)
            base.fetch_range(links[name], base.DATA_OFFSET - 8, base.DATA_OFFSET - 1, header)
            if header.read_bytes()[:4] != b'data':
                raise RuntimeError('source_data_offset_changed')
        local = {}
        for name, (start, end) in sorted(spans.items()):
            path = work / f'{len(local)}.pcm'
            base.fetch_range(links[name], base.DATA_OFFSET + start * base.ALIGN,
                             base.DATA_OFFSET + end * base.ALIGN - 1, path)
            local[name] = (start, path)

        def window_pcm(w):
            pcm = bytearray()
            for part in w['parts']:
                first, path = local[part['file']]
                with path.open('rb') as handle:
                    handle.seek((part['start'] - first) * base.ALIGN)
                    pcm.extend(handle.read((part['end'] - part['start']) * base.ALIGN))
            if len(pcm) != base.WINDOW_FRAMES * base.ALIGN:
                raise RuntimeError('window_size_changed')
            return bytes(pcm)

        def on_attempt(result, ticket, delay):
            stats['attempts'] += 1
            if result.http_status == 429:
                stats['throttled'] += 1
                stats['backoff_seconds'] += delay or 0
            return None

        batch_size = max(1, int(os.getenv('BATCH_SIZE', '10')))
        passes = 0
        # One recognizer for the whole study keeps its shared cooldown across
        # passes; continuation_deadline bounds every retry by the study deadline.
        recognizer = TrackRecognizer(quiet=True, on_attempt=on_attempt,
                                     max_retry_seconds=MAX_RETRY_SECONDS,
                                     continuation_deadline=deadline)
        try:
            while len(done) < len(grid):
                if deadline - time.monotonic() < 1:
                    raise Inconclusive(f'deadline_with_{len(grid) - len(done)}_windows_unresolved')
                if passes:
                    # Unresolved windows are never re-sent at once: back off
                    # exponentially between passes, and respect any cooldown.
                    pause = throttle_delay(passes)
                    pause = max(pause, recognizer._quota_cooldown_until - time.monotonic())
                    await asyncio.sleep(max(0, min(pause, deadline - time.monotonic() - 1)))
                passes += 1
                pending = [w for w in grid if w['index'] not in done]
                for start in range(0, len(pending), batch_size):
                    if time.monotonic() >= deadline:
                        break
                    segments = []
                    for w in pending[start:start + batch_size]:
                        path = work / f'w{w["index"]}.wav'
                        path.write_bytes(base.wav_bytes(window_pcm(w)))
                        segments.append({'file': path, 'index': w['index'],
                                         'timestamp': w['start_frame'] / base.RATE})
                    with contextlib.redirect_stdout(io.StringIO()):
                        results = await recognizer.recognize_batch(segments, total_segments=len(grid))
                    for segment, result in zip(segments, results):
                        if not result.is_valid or not isinstance(result.raw_data, dict):
                            continue  # unresolved; the next pass retries it
                        track = result.raw_data.get('track') or {}
                        if result.recognized and not all(str(track.get(k) or '').strip()
                                                         for k in ('key', 'title', 'subtitle')):
                            raise Inconclusive('provider_identity_incomplete')
                        done[segment['index']] = {'index': segment['index'], 'response': {
                            'recognized': bool(result.recognized), 'raw_data': result.raw_data}}
                    base.say(f'arm B pass {passes}: {len(done)}/{len(grid)} windows, '
                             f'{stats["throttled"]} throttled responses so far')
        finally:
            await recognizer.close()
        stats['passes'] = passes
        return [done[w['index']] for w in grid]
    finally:
        for path in work.iterdir():
            path.unlink(missing_ok=True)
        work.rmdir()


async def compare() -> int:
    sid = base.set_id()
    progress = base.call('yoon_partial_progress', sid)
    if progress is None:
        raise SystemExit('unknown partial family')
    grid_a = base.windows(progress['fragments'])
    if len(grid_a) != progress['expected']:
        raise SystemExit('window_grid_mismatch')
    evidence = base.call('yoon_partial_hits_for', sid)  # raises unless arm A is complete
    grid_b = study_windows(progress['fragments'], STUDY_HOP_FRAMES)
    if not grid_b or len(grid_b) > MAX_STUDY_WINDOWS:
        raise SystemExit(f'arm B window count {len(grid_b)} outside 1..{MAX_STUDY_WINDOWS}')
    a = identified(grid_a, evidence['hits'])
    base.say('arm A (30s/15s, recorded): ' + json.dumps(a))
    links = source_links(sid, progress)
    stats = {'attempts': 0, 'throttled': 0, 'backoff_seconds': 0.0, 'passes': 0}
    started = time.monotonic()
    try:
        hits_b = await recognize_arm_b(grid_b, links, stats)
    except Inconclusive as exc:
        base.say(f'INCONCLUSIVE: {exc} ' + json.dumps(stats))
        return 4
    stats['runtime_seconds'] = round(time.monotonic() - started)
    stats['backoff_seconds'] = round(stats['backoff_seconds'], 1)
    b = identified(grid_b, hits_b)
    base.say('arm B (30s/12s, fresh): ' + json.dumps(b))
    drift = shared_window_agreement(grid_a, evidence['hits'], grid_b, hits_b)
    base.say('RESULT ' + json.dumps({'arm_a': a, 'arm_b': b, 'arm_b_provider': stats,
             'catalog_drift_check': drift,
             'identified_delta': b['identified_entries'] - a['identified_entries']}))
    return 0


def main() -> int:
    base.quiet_process()
    try:
        return asyncio.run(compare())
    except SystemExit:
        raise
    except BaseException as error:  # Only the class name: messages can carry private data.
        base.say(f'failed: {type(error).__name__}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
