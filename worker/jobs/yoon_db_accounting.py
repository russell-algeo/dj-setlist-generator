"""Process-local numeric DB observations for the private recognition entry.

These counters measure buffered PostgreSQL result values, not Neon billing.
They do not trace SQL, parameters, credentials, row values or error messages.
No budget enforcement or retry decision may depend on this observer.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock


_active = ContextVar('private_db_accounting', default=None)
_FIELDS = (
    'connection_attempts', 'connections_opened', 'execute_calls',
    'execute_failures', 'result_sets', 'result_rows', 'result_cells',
    'result_payload_bytes', 'data_row_frame_bytes', 'unmeasured_results',
    'measurement_failures',
)
_MAX_CELLS = 1_000_000


class Meter:
    def __init__(self):
        self._counts = dict.fromkeys(_FIELDS, 0)
        self._lock = Lock()

    def add(self, **values):
        with self._lock:
            for key, value in values.items():
                if key not in self._counts or type(value) is not int or value < 0:
                    raise ValueError('invalid_private_db_counter')
            for key, value in values.items():
                self._counts[key] += value

    def snapshot(self):
        with self._lock:
            return dict(self._counts)

    def line(self):
        counts = self.snapshot()
        return ('private_db_io version=1 scope=process metric=libpq_result_values '
                + ' '.join(f'{key}={counts[key]}' for key in _FIELDS) + '\n')

    def observe(self, cursor):
        try:
            result = getattr(cursor, 'pgresult', None)
            if result is None:
                self.add(unmeasured_results=1)
                return
            rows, fields = result.ntuples, result.nfields
            if (type(rows) is not int or type(fields) is not int
                    or rows < 0 or fields < 0 or rows > _MAX_CELLS
                    or rows * fields > _MAX_CELLS):
                self.add(unmeasured_results=1)
                return
            size = 0
            for row in range(rows):
                for column in range(fields):
                    # The driver already holds this result in memory. Retain no
                    # value, and never decode, serialize, format or log it.
                    value = result.get_value(row, column)
                    if value is not None:
                        if type(value) not in (bytes, bytearray, memoryview):
                            raise TypeError('unsupported_private_db_value')
                        size += value.nbytes if type(value) is memoryview else len(value)
            self.add(result_sets=1, result_rows=rows, result_cells=rows * fields,
                     result_payload_bytes=size,
                     data_row_frame_bytes=rows * (7 + 4 * fields) + size)
        except Exception:
            # Observation cannot change database/commit/provider outcomes.
            self.add(measurement_failures=1)


@contextmanager
def session():
    meter = Meter()
    token = _active.set(meter)
    try:
        yield meter
    finally:
        _active.reset(token)


class _Cursor:
    def __init__(self, cursor, meter):
        self._cursor, self._meter = cursor, meter

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def __enter__(self):
        self._cursor.__enter__()
        return self

    def __exit__(self, *args):
        return self._cursor.__exit__(*args)

    def execute(self, *args, **kwargs):
        self._meter.add(execute_calls=1)
        try:
            result = self._cursor.execute(*args, **kwargs)
        except BaseException:
            self._meter.add(execute_failures=1)
            raise
        self._meter.observe(self._cursor)
        return self if result is self._cursor else result

    def nextset(self):
        result = self._cursor.nextset()
        if result:
            self._meter.observe(self._cursor)
        return result


class _Connection:
    def __init__(self, connection, meter):
        self._connection, self._meter = connection, meter

    def __getattr__(self, name):
        # Transaction context and status evidence remain the actual connection's.
        return getattr(self._connection, name)

    def cursor(self, *args, **kwargs):
        return _Cursor(self._connection.cursor(*args, **kwargs), self._meter)


def measured_connect(connect):
    """Leave ordinary callers entirely unchanged outside an enabled session."""
    meter = _active.get()
    if meter is None:
        return connect

    @contextmanager
    def observed():
        meter.add(connection_attempts=1)
        with connect() as connection:
            meter.add(connections_opened=1)
            yield _Connection(connection, meter)
    return observed
