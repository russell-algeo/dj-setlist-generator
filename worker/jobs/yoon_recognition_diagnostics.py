"""Allowlisted recognition diagnostics; never format exception messages or data."""
from contextlib import contextmanager
import os
import sys

_PHASES = frozenset({
    'entry', 'imports', 'owner', 'audio_validation', 'initialization', 'clock',
    'select_windows', 'reserve', 'finish', 'extract', 'batch', 'cleanup', 'close',
})
_CLASSES = frozenset({
    'RuntimeError', 'ValueError', 'TypeError', 'KeyError', 'IndexError',
    'AttributeError', 'AssertionError', 'OSError', 'FileNotFoundError',
    'PermissionError', 'TimeoutError', 'CalledProcessError', 'TimeoutExpired',
    'OperationalError', 'InterfaceError', 'DatabaseError', 'ProgrammingError',
    'IntegrityError', 'InternalError', 'DataError', 'NotSupportedError',
    'DeadlockDetected', 'SerializationFailure', 'LockNotAvailable',
    'QueryCanceled', 'InsufficientPrivilege', 'ConnectionFailure',
    'AdminShutdown', 'IdleInTransactionSessionTimeout', 'InFailedSqlTransaction',
    'ModuleNotFoundError', 'ImportError',
})
_SQLSTATES = frozenset({
    '08000', '08001', '08003', '08004', '08006', '08007', '08P01',
    '40001', '40P01', '42501', '53300', '53400', '55P03', '57014',
    '57P01', '57P02', '57P03', '25P02', '25P03', '23505', '23503',
})
_fd = None
_emitted = 0


def diagnostic_line(phase, error):
    # Names and SQLSTATE are untrusted too: emit only fixed known tokens.
    name = type(error).__name__
    try:
        sqlstate = getattr(error, 'sqlstate', None)
    except Exception:
        sqlstate = None
    return ('private_recognition phase=' + (phase if phase in _PHASES else 'entry')
            + ' exception=' + (name if name in _CLASSES else 'OtherError')
            + ' sqlstate=' + (sqlstate if type(sqlstate) is str and sqlstate in _SQLSTATES else 'none')
            + '\n')


def report(phase, error):
    global _emitted
    if _fd is None or _emitted >= 32:
        return
    try:
        os.write(_fd, diagnostic_line(phase, error).encode('ascii'))
        _emitted += 1
    except Exception:
        # Diagnostics must never change the original exception or task outcome.
        pass


@contextmanager
def phase(name):
    try:
        yield
    except Exception as error:
        # QueuePause is intentional flow control, not a worker failure.
        from worker.jobs.yoon_resume_store import QueuePause
        if not isinstance(error, QueuePause):
            report(name, error)
        raise


def run():
    global _fd, _emitted
    if sys.argv[1:] != ['recognize']:
        return 2
    # Preserve only the original diagnostic destination; suppress all library,
    # import, subprocess and traceback output before importing the private job.
    try:
        _fd = os.dup(2)
        _emitted = 0
        with open(os.devnull, 'w') as sink:
            os.dup2(sink.fileno(), 1)
            os.dup2(sink.fileno(), 2)
        from worker.jobs.yoon_once import main
        return main()
    except Exception as error:
        report('entry', error)
        return 1
    finally:
        if _fd is not None:
            try:
                os.close(_fd)
            except OSError:
                pass
        _fd = None


if __name__ == '__main__':
    # Import the canonical module so adapter hooks share this exact sink.
    from worker.jobs.yoon_recognition_diagnostics import run
    raise SystemExit(run())
