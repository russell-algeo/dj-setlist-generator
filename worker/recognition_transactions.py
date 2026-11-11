"""Bounded retries of database-only recognition operations, never provider calls."""
from contextlib import contextmanager
from functools import wraps

from psycopg.errors import LockNotAvailable
from psycopg.pq import ConnStatus, TransactionStatus


class RolledBackLockTimeout(Exception):
    """Internal signal: the failed body is known not to have committed."""
    def __init__(self, error):
        self.error = error
        super().__init__('recognition_lock_timeout_rolled_back')


def retry_lock_timeouts(operation):
    """Replay the entire store method with fresh scope/owner/ticket checks.

    The existing durable session start and provider deadline are never reset.
    No generic OperationalError, failed COMMIT, or uncertain rollback qualifies.
    Keep this on database-only methods: neither HTTP nor a runner is replayable.
    """
    @wraps(operation)
    def retried(*args, **kwargs):
        for attempt in range(3):
            try:
                return operation(*args, **kwargs)
            except RolledBackLockTimeout as error:
                if attempt == 2:
                    raise error.error from None
    return retried


@contextmanager
def recognition_transaction(connect):
    """Mark only a body lock timeout followed by a confirmed outer rollback.

    Psycopg may log and suppress rollback failures. Inspect the still-open
    connection after transaction exit rather than trusting exception type alone.
    A nested/savepoint transaction cannot prove the whole operation rolled back.
    Adapters without connection-status evidence remain usable but cannot retry.
    """
    with connect() as conn:
        info = getattr(conn, 'info', None)
        started_idle = getattr(info, 'transaction_status', None) == TransactionStatus.IDLE
        lock_error = None
        try:
            with conn.transaction():
                try:
                    yield conn
                except LockNotAvailable as error:
                    if (started_idle and error.sqlstate == '55P03'
                            and error.diag.message_primary == 'canceling statement due to lock timeout'
                            and getattr(info, 'transaction_status', None) == TransactionStatus.INERROR):
                        lock_error = error
                    raise
        except LockNotAvailable as error:
            if (error is lock_error and getattr(conn, 'closed', True) is False
                    and getattr(conn, 'broken', True) is False
                    and getattr(info, 'status', None) == ConnStatus.OK
                    and getattr(info, 'transaction_status', None) == TransactionStatus.IDLE):
                raise RolledBackLockTimeout(error) from None
            raise
