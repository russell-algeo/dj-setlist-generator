"""One reviewed, metadata-only recheck; never changes the initial receipt or app links."""
import copy
from contextlib import contextmanager

from worker.jobs.yoon_spotify_enrich import DONALD_RUN, KEY, Store, digest, enrich

INDICES = (0, 2, 6, 9, 12, 16, 23)
PRIOR_DIGEST = '4e76d07796058056133a5e93c37c8ac18d349f61fcafee4175739438d8289498'
RECHECK_KEY = 'yoon_spotify_recheck_v1'


def validate_prior(row, tracks, expected):
    prior = row['source_metadata'].get(KEY) or {}
    results = prior.get('results')
    if (str(row['id']) != DONALD_RUN or prior.get('status') != 'complete'
            or prior.get('input') != expected or not isinstance(results, list)
            or prior.get('results_digest') != PRIOR_DIGEST or digest(results) != PRIOR_DIGEST
            or len(results) != 19
            or tuple(r['index'] for r in results if not r.get('spotify_url')) != INDICES
            or any(i >= len(tracks) or tracks[i]['title'] == 'Unknown Track' for i in INDICES)):
        raise RuntimeError('reviewed_prior_metadata_required')


class RecheckStore(Store):
    key = RECHECK_KEY

    def __init__(self, expected, workflow, attempt, run_id):
        if run_id != DONALD_RUN:
            raise RuntimeError('reviewed_recheck_run_required')
        super().__init__(expected, workflow, attempt, run_id)

    @contextmanager
    def locked(self):
        # Parent validates audience, complete recognition and immutable source pins.
        with super().locked() as (cur, row, tracks):
            validate_prior(row, tracks, self.expected)
            yield cur, row, tracks

    def finish(self, ticket, results):
        if [r.get('index') for r in results] != list(INDICES):
            raise RuntimeError('recheck_result_scope_changed')
        super().finish(ticket, results)


def enrich_selected(tracks, enricher):
    """Same shared matcher, same requests, no recognition or playlist creation."""
    out = []
    for index in INDICES:
        result = enrich([tracks[index]], enricher)
        if len(result) != 1:
            raise RuntimeError('reviewed_track_missing')
        row = result[0]
        row['index'] = index
        row['diagnostic'] = copy.deepcopy(enricher.last_spotify_diagnostic)
        out.append(row)
    return out
