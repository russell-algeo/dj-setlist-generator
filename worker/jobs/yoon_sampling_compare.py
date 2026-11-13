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
  * Exactly one provider attempt per window (single_attempt), so the request
    count equals the arm B window count, capped by MAX_STUDY_WINDOWS.
  * Stops at the first HTTP 429 and treats the result as inconclusive.
  * Before every batch, refuses to continue if any other recognizing workflow
    run in the repository is queued or in progress (SAMPLING_GUARD_* env).

  python -m worker.jobs.yoon_sampling_compare
Environment: DATABASE_URL_DIRECT, WORKER_DEPLOYMENT_TARGET=development,
YOON_PARTIAL_SET_ID, GITHUB_TOKEN, GITHUB_REPOSITORY, GITHUB_RUN_ID.
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
import urllib.request

from worker.jobs import yoon_partial_runner as base

STUDY_HOP_FRAMES = 12 * base.RATE
MAX_STUDY_WINDOWS = int(os.getenv('MAX_STUDY_WINDOWS', '600'))
RECOGNIZING_WORKFLOWS = ('process-set', 'yoon-partial', 'discover-artist', 'sampling-compare')


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


def other_recognizing_runs() -> int:
    """Count other queued/in-progress recognizing runs in this repository."""
    repo, token, me = os.environ['GITHUB_REPOSITORY'], os.environ['GITHUB_TOKEN'], os.environ['GITHUB_RUN_ID']
    total = 0
    for status in ('in_progress', 'queued', 'waiting', 'pending', 'requested'):
        request = urllib.request.Request(
            f'https://api.github.com/repos/{repo}/actions/runs?status={status}&per_page=100',
            headers={'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json'})
        with urllib.request.urlopen(request, timeout=30) as response:
            runs = json.load(response)['workflow_runs']
        total += sum(1 for r in runs if str(r['id']) != me and r['name'] in RECOGNIZING_WORKFLOWS)
    return total


def identified(grid: list[dict], hits: list[dict]) -> dict:
    entries = base.cluster(grid, hits)
    recognized = [h for h in hits if h['response']['recognized']]
    keys = {h['response']['raw_data']['track']['key'] for h in recognized}
    return {'windows': len(grid), 'recognized_windows': len(recognized),
            'distinct_tracks': len(keys), 'identified_entries': len(entries)}


async def recognize_arm_b(grid: list[dict], links: dict) -> list[dict]:
    from track_recognizer import TrackRecognizer
    work = Path(tempfile.mkdtemp(prefix='yoon-sampling-'))
    hits: list[dict] = []
    try:
        spans: dict[str, list[int]] = {}
        for w in grid:
            for part in w['parts']:
                span = spans.setdefault(part['file'], [part['start'], part['end']])
                span[0], span[1] = min(span[0], part['start']), max(span[1], part['end'])
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

        recognizer = TrackRecognizer(quiet=True, single_attempt=True)
        try:
            batch_size = max(1, int(os.getenv('BATCH_SIZE', '10')))
            for start in range(0, len(grid), batch_size):
                if other_recognizing_runs():
                    raise Inconclusive('other_recognizing_run_active')
                segments = []
                for w in grid[start:start + batch_size]:
                    path = work / f'w{w["index"]}.wav'
                    path.write_bytes(base.wav_bytes(window_pcm(w)))
                    segments.append({'file': path, 'index': w['index'], 'window': w,
                                     'timestamp': w['start_frame'] / base.RATE})
                with contextlib.redirect_stdout(io.StringIO()):
                    results = await recognizer.recognize_batch(segments, total_segments=len(grid))
                for segment, result in zip(segments, results):
                    if result.http_status == 429:
                        raise Inconclusive('provider_throttled')
                    if not result.is_valid or not isinstance(result.raw_data, dict):
                        raise Inconclusive('provider_attempt_failed')
                    track = result.raw_data.get('track') or {}
                    if result.recognized and not all(str(track.get(k) or '').strip()
                                                     for k in ('key', 'title', 'subtitle')):
                        raise Inconclusive('provider_identity_incomplete')
                    hits.append({'index': segment['index'], 'response': {
                        'recognized': bool(result.recognized), 'raw_data': result.raw_data}})
                base.say(f'arm B: {len(hits)}/{len(grid)} windows')
                await asyncio.sleep(1)
        finally:
            await recognizer.close()
        return hits
    finally:
        for path in work.iterdir():
            path.unlink(missing_ok=True)
        work.rmdir()


async def compare() -> int:
    sid = base.set_id()
    progress = base.call('yoon_partial_progress', sid)
    if progress is None or progress['released']:
        raise SystemExit('partial family released or unknown; sources are sealed')
    grid_a = base.windows(progress['fragments'])
    evidence = base.call('yoon_partial_hits_for', sid)  # raises unless arm A is complete
    grid_b = study_windows(progress['fragments'], STUDY_HOP_FRAMES)
    if not grid_b or len(grid_b) > MAX_STUDY_WINDOWS:
        raise SystemExit(f'arm B window count {len(grid_b)} outside 1..{MAX_STUDY_WINDOWS}')
    if other_recognizing_runs():
        raise SystemExit('another recognizing run is active; not starting')
    a = identified(grid_a, evidence['hits'])
    base.say('arm A (30s/15s, recorded): ' + json.dumps(a))
    links = base.call('yoon_partial_sources_for', sid)
    try:
        hits_b = await recognize_arm_b(grid_b, links)
    except Inconclusive as exc:
        base.say(f'INCONCLUSIVE: {exc}')
        return 4
    b = identified(grid_b, hits_b)
    base.say('arm B (30s/12s, fresh): ' + json.dumps(b))
    base.say('RESULT ' + json.dumps({'arm_a': a, 'arm_b': b,
             'identified_delta': b['identified_entries'] - a['identified_entries']}))
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(compare()))
