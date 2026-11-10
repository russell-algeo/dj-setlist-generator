"""One reviewed four-request extension, not a general retry policy.

The private operator grants this once against an exact released snapshot. The
first eight attempts remain in place and count toward the fixed cap of twelve.
No continuation, metadata replay, or renewed grant can replenish that cap.
"""
import json
import math
import re

from worker.jobs.yoon_sources import CATALOG

RUN_ID = '5a8e6b9f-5aaf-58fa-a8c1-dff7d2723da1'
SOURCE_ID = 'hunter-foshee-saturday'
SEGMENT_INDEX = 353
GRANT_ID = 'hunter-353-four-extra-v1'
# Prepared-audio pin from the independently reviewed released Hunter snapshot.
AUDIO_SHA256 = 'f2fd18f4e9fa4095cf1bf9afdf67ef73a9c61ea50a31a78802ed2bb6562fc1a7'
GRANT_KEY = 'hunter_window_allowance'


def window_attempt_limit(state, *, run_id, index, attempts):
    """Return eight normally; twelve only for the single explicitly granted window."""
    if GRANT_KEY not in state:
        return 8
    grant = state[GRANT_KEY]
    fixed = dict(version=1, grant_id=GRANT_ID, run_id=RUN_ID,
                 source_id=SOURCE_ID, segment_index=SEGMENT_INDEX,
                 base_attempts=8, additional_attempts=4, max_attempts=12,
                 audio_sha256=AUDIO_SHA256)
    fields = set(fixed) | {'prior_attempts', 'reviewed_snapshot_sha256',
                           'terminal_evidence_sha256', 'granted_at'}
    def reject():
        raise RuntimeError('private_window_allowance_invalid')
    if (type(grant) is not dict or set(grant) != fields
            or any(type(grant.get(k)) is not type(v) or grant[k] != v
                   for k, v in fixed.items())
            or run_id != RUN_ID or state.get('source_id') != SOURCE_ID
            or state.get('source_pins') != CATALOG[SOURCE_ID].pins()
            or not re.fullmatch('[0-9a-f]{64}', AUDIO_SHA256)
            or state.get('audio_sha256') != AUDIO_SHA256
            or state.get('expected_audio_sha256') != AUDIO_SHA256):
        reject()
    for key in ('reviewed_snapshot_sha256', 'terminal_evidence_sha256'):
        if type(grant[key]) is not str or not re.fullmatch('[0-9a-f]{64}', grant[key]):
            reject()
    when = grant['granted_at']
    if type(when) not in (int, float) or not math.isfinite(when) or when <= 0:
        reject()
    prior = grant['prior_attempts']
    if (type(prior) is not list or len(prior) != 8
            or any(type(a) is not dict or a.get('state') != 'finished'
                   or type(a.get('diagnostic')) is not dict
                   or type(a['diagnostic'].get('http_status')) is not int
                   or a['diagnostic']['http_status'] != 429
                   or a['diagnostic'].get('retry_after_format') == 'invalid'
                   for a in prior)):
        reject()
    if type(index) is not int:
        reject()
    if index != SEGMENT_INDEX:
        return 8
    if (type(attempts) is not list or not 8 <= len(attempts) <= 12
            or json.dumps(attempts[:8], sort_keys=True, allow_nan=False)
               != json.dumps(prior, sort_keys=True, allow_nan=False)):
        reject()
    return 12
