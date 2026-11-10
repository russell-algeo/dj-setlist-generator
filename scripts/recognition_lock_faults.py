"""Actual store transactions with injected SQL errors, not real lock contention.

PGlite is single-session. A server-side RAISE supplies 55P03 and aborts a real
transaction; acknowledged ROLLBACK supplies this adapter's status evidence.
Native multi-session coverage lives in test-recognition-locks-postgres.py.
"""
from contextlib import contextmanager
import json
from types import SimpleNamespace
from psycopg.errors import LockNotAvailable
from psycopg.pq import ConnStatus, TransactionStatus as TS
from worker.pipeline.models import Recognition


def run_checks(store, query, *, index, lease_id=None, worker_name=None):
    private = lease_id is None
    run = store.run_id
    key = 'yoon_resume' if private else 'shared_recognition'
    hit_key = 'private_jackson_v2' if private else 'shared_recognition'
    before = query('SELECT * FROM ops.set_runs WHERE id=%s', (run,))[0]
    original = before['source_metadata']
    lease = query('SELECT * FROM ops.set_run_leases WHERE set_run_id=%s AND %s BETWEEN segment_start_index AND segment_end_index', (run,index))[0]
    assert not query('SELECT 1 FROM ops.segment_hits WHERE set_run_id=%s AND segment_index=%s', (run,index))
    original_connect = store.connect
    checks = 0

    def state():
        return query('SELECT source_metadata FROM ops.set_runs WHERE id=%s', (run,))[0]['source_metadata'][key]
    def hit():
        rows = query('SELECT raw_data FROM ops.segment_hits WHERE set_run_id=%s AND segment_index=%s', (run,index))
        return rows[0]['raw_data'][hit_key] if rows else None
    def reset():
        store.connect = original_connect
        # Fixture reset only: remove the synthetic retention marker before
        # discarding our test evidence, then restore the complete original row.
        if not private:
            query("UPDATE ops.set_runs SET source_metadata=source_metadata-'shared_recognition' WHERE id=%s", (run,))
        query('DELETE FROM ops.segment_hits WHERE set_run_id=%s AND segment_index=%s', (run,index))
        query('UPDATE ops.set_runs SET source_metadata=%s::jsonb,status=%s,cancel_requested_at=NULL,create_playlist=%s,stage=%s WHERE id=%s',
              (json.dumps(original), before['status'], before['create_playlist'], before['stage'], run))
        query('UPDATE ops.set_run_leases SET status=%s,claimed_by=%s,claimed_at=%s,completed_at=%s WHERE id=%s',
              (lease['status'],lease['claimed_by'],lease['claimed_at'],lease['completed_at'],lease['id']))
    def reserve():
        return store.reserve(index) if private else store.reserve(index,lease_id,worker_name)
    def finish(ticket):
        result = Recognition(index*15,None,None,None,{'matches':[]},False,index,http_status=200)
        return store.finish(result,ticket) if private else store.finish(ticket,result)
    def fault(failures, *, on_retry=None):
        counts = {'connections':0, 'failures':0, 'rollbacks':0}
        class Cursor:
            def __init__(self, raw, conn): self.raw,self.conn=raw,conn
            def __getattr__(self,name): return getattr(self.raw,name)
            def __enter__(self): self.raw.__enter__(); return self
            def __exit__(self,*args): return self.raw.__exit__(*args)
            def execute(self,sql,params=()):
                self.raw.execute(sql,params)
                if 'UPDATE ops.set_runs SET source_metadata' in sql and counts['failures'] < failures:
                    counts['failures'] += 1
                    try:
                        self.raw.execute("DO $$ BEGIN RAISE EXCEPTION 'canceling statement due to lock timeout' USING ERRCODE='55P03'; END $$")
                    except RuntimeError as error:
                        assert str(error) == 'canceling statement due to lock timeout'
                        self.conn.info.transaction_status = TS.INERROR
                        raise LockNotAvailable(str(error),info={ord('C'):b'55P03',ord('M'):str(error).encode()}) from None
                    raise AssertionError('injected SQL error did not abort')
        class Connection:
            closed,broken=False,False
            def __init__(self,raw):
                self.raw=raw
                self.info=SimpleNamespace(status=ConnStatus.OK,transaction_status=TS.IDLE)
            def cursor(self): return Cursor(self.raw.cursor(),self)
            @contextmanager
            def transaction(self):
                cur=self.raw.cursor();cur.execute('BEGIN');self.info.transaction_status=TS.INTRANS
                try: yield
                except BaseException:
                    cur.execute('ROLLBACK');self.info.transaction_status=TS.IDLE
                    counts['rollbacks'] += 1
                    raise
                else:
                    cur.execute('COMMIT');self.info.transaction_status=TS.IDLE
        @contextmanager
        def connect():
            counts['connections'] += 1
            if counts['connections']>1 and on_retry: on_retry()
            with original_connect() as raw: yield Connection(raw)
        store.connect=connect
        return counts
    try:
        def rolled_back():
            assert state()['requests']==original[key]['requests']
            assert hit() is None
        counts=fault(2,on_retry=rolled_back)
        ticket=reserve()
        assert counts==dict(connections=3,failures=2,rollbacks=2)
        assert state()['requests']==original[key]['requests']+1 and len(hit()['attempts'])==1
        checks+=4
        before_hit=hit()
        def retained():
            assert hit()==before_hit
        counts=fault(1,on_retry=retained)
        finish(ticket)
        assert counts==dict(connections=2,failures=1,rollbacks=1)
        assert state()['requests']==original[key]['requests']+1 and len(hit()['attempts'])==1
        assert hit()['valid'] is True and hit()['in_flight'] is False
        checks+=4
        reset()
        counts=fault(4,on_retry=rolled_back)
        try: reserve()
        except (RuntimeError,LockNotAvailable): pass
        else: raise AssertionError('unbounded retry')
        assert counts==dict(connections=3,failures=3,rollbacks=3)
        rolled_back();checks+=3
        reset()
        for fence in ('owner','cancel','scope','deadline'):
            def mutate():
                rolled_back()
                if fence=='cancel':
                    query('UPDATE ops.set_runs SET cancel_requested_at=now() WHERE id=%s',(run,))
                elif fence=='scope':
                    query('UPDATE ops.set_runs SET create_playlist=true WHERE id=%s' if private else "UPDATE ops.set_runs SET stage='publishing_committed' WHERE id=%s",(run,))
                else:
                    field=('workflow_run_id' if private else 'owner') if fence=='owner' else 'session_started'
                    value='"9999"' if fence=='owner' else '1'
                    query(f"UPDATE ops.set_runs SET source_metadata=jsonb_set(source_metadata,'{{{key},{field}}}',%s::jsonb) WHERE id=%s",(value,run))
            counts=fault(1,on_retry=mutate)
            try: reserve()
            except Exception as error:
                # Errors must come from a fresh fence, never retry exhaustion.
                expected = ('private_resume_owner_changed' if private else 'shared_continuation_owner_changed') if fence=='owner' else 'workflow_time_budget' if fence=='deadline' else ('private_resume_scope_required' if private else 'shared_owner_or_scope_changed')
                assert str(error)==expected, (fence,type(error).__name__,str(error))
            else: raise AssertionError('retry bypassed '+fence)
            assert counts['connections']==2
            assert state()['requests']==original[key]['requests'] and hit() is None
            checks+=3
            reset()
        ticket=reserve()
        def change_ticket():
            field='ticket' if private else 'token'
            query(f"UPDATE ops.segment_hits SET raw_data=jsonb_set(raw_data,'{{{hit_key},attempts,0,{field}}}','\"changed\"') WHERE set_run_id=%s AND segment_index=%s",(run,index))
        counts=fault(1,on_retry=change_ticket)
        try: finish(ticket)
        except RuntimeError as error:
            assert str(error)==('private_attempt_owner_changed' if private else 'shared_response_reservation_changed')
        else: raise AssertionError('retry bypassed ticket fence')
        assert counts['connections']==2 and hit()['in_flight'] is True and hit()['valid'] is False
        checks+=2
    finally:
        reset()
    return checks
