"""Two individually approved fixed allowances; no general retry-policy override."""
from worker.jobs import yoon_sydka_allowance as sydka
from worker.jobs import yoon_hunter_allowance as hunter


def window_attempt_limit(state, *, run_id, index, attempts):
    # Each validator fails closed when its own grant is present on a wrong run.
    # Keep the consumed Sydka allowance and its historical attempt accounting.
    return max(sydka.window_attempt_limit(state, run_id=run_id, index=index, attempts=attempts),
               hunter.window_attempt_limit(state, run_id=run_id, index=index, attempts=attempts))
