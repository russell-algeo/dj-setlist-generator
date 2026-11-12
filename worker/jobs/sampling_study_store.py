"""Isolated PostgreSQL experiment ledger; never creates/changes ordinary runs.

Exclusive operational window is an explicit prerequisite, not inferred from a
single idle query. Grant creation/activation belongs to a reviewed administrator.
Use the same live connection for session advisory ownership and all transactions.
A missing/unknown finish stays charged and blocks continuation without takeover.
"""
from contextlib import contextmanager
import json
import math
import uuid
from recognition_transport import RequestDeferred
from recognition_retry_policy import RetryDirective,throttle_delay
from worker.jobs.sampling_study_manifest import validate,digest

class StudyPause(RequestDeferred):pass
class StudyFence(RuntimeError):pass

def require_idle_autocommit(connection):
    if getattr(connection,'autocommit',None) is not True or getattr(getattr(connection,'info',None),'transaction_status',None)!=0:
        raise StudyFence('study_outer_commit_required')

class StudyStore:
    def __init__(self,connection,study_id,owner,source_ref,*,guard_check=None):
        require_idle_autocommit(connection)
        self.conn=connection;self.id=str(uuid.UUID(study_id));self.owner=owner;self.source_ref=source_ref
        if not isinstance(owner,str) or len(owner.split(':'))!=2 or not all(x.isdecimal() for x in owner.split(':')):raise StudyFence('study_owner_required')
        if not isinstance(source_ref,str) or len(source_ref)!=40 or any(x not in '0123456789abcdef' for x in source_ref):raise StudyFence('study_source_ref_required')
        self.guard_check=guard_check or self._guard
        self.manifest=None;self.windows=None

    @staticmethod
    def _guard(cur):
        cur.execute("""SELECT EXISTS(SELECT 1 FROM pg_locks WHERE locktype='advisory' AND pid=pg_backend_pid()
          AND classid=183601 AND objid=2 AND objsubid=2 AND granted) AS held""")
        if cur.fetchone()['held'] is not True:raise StudyFence('study_exclusive_session_lost')

    @contextmanager
    def locked(self,*,owner=True,grant=True):
        require_idle_autocommit(self.conn)
        with self.conn.transaction(),self.conn.cursor() as cur:
            cur.execute("SHOW transaction_isolation")
            if cur.fetchone()["transaction_isolation"]!="read committed":raise StudyFence("study_read_committed_required")
            cur.execute("SET LOCAL lock_timeout='5s'");cur.execute("SET LOCAL statement_timeout='15s'")
            self.guard_check(cur)
            cur.execute('''SELECT s.*,extract(epoch FROM clock_timestamp())::float8 AS db_now,
              g.enabled,g.reviewed_source_ref,extract(epoch FROM g.not_before)::float8 AS grant_start,
              extract(epoch FROM g.expires_at)::float8 AS grant_end
              FROM ops.sampling_studies_v1 s JOIN ops.sampling_exclusive_grants_v1 g ON g.id=s.grant_id
              WHERE s.id=%s FOR UPDATE OF s''',(self.id,))
            row=cur.fetchone()
            if not row:raise StudyFence('study_not_precreated')
            if owner and (row['status']!='running' or row['owner']!=self.owner):raise StudyFence('study_owner_changed')
            if grant and (not row['enabled'] or row['reviewed_source_ref']!=self.source_ref or not row['grant_start']<=row['db_now']<row['grant_end']-65):raise StudyPause('study_exclusive_grant_inactive')
            windows=validate(row['manifest'])
            if digest(row['manifest'])!=row['manifest_sha256'] or row['reference_sha256']!=row['manifest']['reference_sha256']:raise StudyFence('study_manifest_changed')
            if self.manifest is not None and self.manifest!=row['manifest']:raise StudyFence('study_manifest_changed')
            yield cur,row,windows

    @staticmethod
    def demand(cur):
        from worker.jobs.yoon_admission import ROWS_SQL,occupied
        cur.execute(ROWS_SQL)
        for row in cur.fetchall():
            if occupied(row) or (row['source_metadata'].get('yoon_queue_v1') or {}).get('status')=='queued':
                raise StudyPause('study_yoon_priority')
        # Ordinary work is not in the private admission cap. Exclusive experiment
        # also refuses active ordinary recognition, not just private Yoon work.
        cur.execute("SELECT EXISTS(SELECT 1 FROM ops.set_runs WHERE publication_visibility='public' AND status IN ('dispatched','resolving','recognizing','aggregating','enriching','publishing','cancelling')) AS busy")
        if cur.fetchone()['busy']:raise StudyPause('study_ordinary_work_active')

    @staticmethod
    def inherited_cooldown(cur):
        cur.execute("""SELECT greatest(
          coalesce(max((source_metadata->'yoon_resume'->>'next_allowed_at')::double precision),0),
          coalesce(max((source_metadata->'yoon_resume'->>'provider_next_allowed_at')::double precision),0),
          coalesce(max((source_metadata->'shared_recognition'->>'next_allowed_at')::double precision),0),
          coalesce(max((source_metadata->'shared_recognition'->>'provider_next_allowed_at')::double precision),0)) AS until
          FROM ops.set_runs""")
        value=cur.fetchone()['until']
        if not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:raise StudyFence('study_inherited_cooldown_invalid')
        return value

    def claim(self):
        with self.locked(owner=False) as (cur,row,windows):
            if row['status'] not in ('ready','paused') or row['cancelled'] or self.owner in row['used_owners']:raise StudyFence('study_claim_not_released')
            self.demand(cur)
            cur.execute("SELECT EXISTS(SELECT 1 FROM ops.sampling_attempts_v1 WHERE study_id=%s AND outcome IN ('reserved','unknown')) AS pending",(self.id,))
            if cur.fetchone()['pending']:raise StudyPause('study_unknown_outcome')
            if row['db_now']<max(row['next_allowed_at'],self.inherited_cooldown(cur)):raise StudyPause('study_cooldown')
            cur.execute("UPDATE ops.sampling_studies_v1 SET status='running',owner=%s,used_owners=used_owners||%s::jsonb,reason=NULL,updated_at=now() WHERE id=%s",(self.owner,json.dumps([self.owner]),self.id))
            self.manifest=row['manifest'];self.windows=windows
        return self.manifest

    def reserve(self,window_id,input_hash):
        ticket=str(uuid.uuid4())
        with self.locked() as (cur,row,windows):
            if row['cancelled']:raise StudyPause('study_cancelled')
            self.demand(cur)
            if row['db_now']<max(row['next_allowed_at'],self.inherited_cooldown(cur)):raise StudyPause('study_cooldown')
            w=windows.get(window_id)
            if not w or w['input_sha256']!=input_hash:raise StudyFence('study_consumed_input_changed')
            if row['requests']>=row['request_limit']:raise StudyPause('study_all_attempt_cap')
            cur.execute("SELECT window_id,outcome FROM ops.sampling_attempts_v1 WHERE study_id=%s",(self.id,));attempts=cur.fetchall()
            if len(attempts)!=row['requests']:raise StudyFence('study_attempt_accounting_mismatch')
            if any(a['outcome'] in ('reserved','unknown') for a in attempts):raise StudyPause('study_unknown_outcome')
            prior=[a for a in attempts if a['window_id']==window_id]
            if any(a['outcome'] in ('matched','no_match') for a in prior):raise StudyFence('study_terminal_window_replay')
            if sum(a['outcome']!='throttled' for a in prior)>=8:raise StudyPause('study_window_attempt_cap')
            cur.execute("INSERT INTO ops.sampling_attempts_v1(ticket,study_id,number,window_id,input_sha256,owner) VALUES(%s,%s,%s,%s,%s,%s)",(ticket,self.id,row['requests']+1,window_id,input_hash,self.owner))
            cur.execute("UPDATE ops.sampling_studies_v1 SET requests=requests+1,updated_at=now() WHERE id=%s",(self.id,))
        # Transaction commit precedes the caller's provider transmission.
        return ticket

    def finish(self,ticket,receipt,proposed_delay=0):
        if type(proposed_delay) not in (int,float) or not math.isfinite(proposed_delay) or proposed_delay<0:raise StudyFence('study_delay_invalid')
        if not isinstance(receipt,dict) or set(receipt)!={'outcome','http_status','candidate','response_sha256','error_type','retry_after_seconds','retry_after_format','raw_response'}:raise StudyFence('study_receipt_shape')
        outcome=receipt['outcome'];status=receipt['http_status'];wait=receipt['retry_after_seconds'] or 0
        if outcome not in ('matched','no_match','throttled','failed','unknown') or (status is not None and (type(status) is not int or not 100<=status<=599)):raise StudyFence('study_receipt_outcome')
        if type(wait) not in (int,float) or not math.isfinite(wait) or wait<0:raise StudyFence('study_retry_after_invalid')
        from worker.jobs.sampling_study_manifest import valid_hash
        if outcome in ('matched','no_match') and (status!=200 or receipt['error_type'] is not None or not valid_hash(receipt['response_sha256'])):raise StudyFence('study_terminal_evidence_required')
        if outcome=='matched' and (not isinstance(receipt['candidate'],dict) or set(receipt['candidate'])!={'id','artist','title'} or any(not isinstance(x,str) or not 0<len(x)<=512 for x in receipt['candidate'].values())):raise StudyFence('study_candidate_required')
        if outcome!='matched' and receipt['candidate'] is not None:raise StudyFence('study_unexpected_candidate')
        if (outcome=='throttled')!=(status==429):raise StudyFence('study_throttle_identity')
        raw=receipt['raw_response']
        if outcome in ('matched','no_match'):
            if not isinstance(raw,dict) or len(json.dumps(raw).encode())>131072 or digest(raw)!=receipt['response_sha256']:raise StudyFence('study_raw_evidence_binding')
            from recognition_transport import validate_response
            validate_response(raw)
            if outcome=='matched' and (not isinstance(raw.get('track'),dict) or receipt['candidate']!={'id':raw['track'].get('key'),'artist':raw['track'].get('subtitle'),'title':raw['track'].get('title')}):raise StudyFence('study_raw_candidate_binding')
            if outcome=='no_match' and 'track' in raw:raise StudyFence('study_raw_no_match_binding')
        elif raw is not None:raise StudyFence('study_unexpected_raw_response')
        h=digest(receipt)
        with self.locked(grant=False) as (cur,row,_):
            cur.execute("SELECT * FROM ops.sampling_attempts_v1 WHERE ticket=%s AND study_id=%s FOR UPDATE",(ticket,self.id));attempt=cur.fetchone()
            if not attempt or attempt['owner']!=self.owner:raise StudyFence('study_ticket_fence')
            if attempt['outcome']!='reserved':
                if attempt['receipt_sha256']==h:return RetryDirective(attempt['delay_seconds'])
                raise StudyFence('study_receipt_changed')
            streak=row['throttle_streak']+1 if outcome=='throttled' else 0
            delay=max(proposed_delay,wait,throttle_delay(streak,wait) if outcome=='throttled' else 0)
            cur.execute("UPDATE ops.sampling_attempts_v1 SET outcome=%s,receipt=%s::jsonb,receipt_sha256=%s,delay_seconds=%s,finished_at=now() WHERE ticket=%s",(outcome,json.dumps(receipt),h,delay,ticket))
            cur.execute("UPDATE ops.sampling_studies_v1 SET next_allowed_at=greatest(next_allowed_at,%s),throttle_streak=%s,updated_at=now() WHERE id=%s",(row['db_now']+delay,streak,self.id))
        return RetryDirective(delay)

    def completed_ids(self):
        with self.locked() as (cur,_,__):
            cur.execute("SELECT window_id FROM ops.sampling_attempts_v1 WHERE study_id=%s AND outcome IN ('matched','no_match')",(self.id,))
            return {r['window_id'] for r in cur.fetchall()}

    def release(self,reason,*,transport_drained):
        if transport_drained is not True:raise StudyFence('study_transport_not_drained')
        if reason not in ('complete','paused','cancelled','error'):raise StudyFence('study_release_reason')
        with self.locked(grant=False) as (cur,row,windows):
            cur.execute("SELECT window_id,outcome FROM ops.sampling_attempts_v1 WHERE study_id=%s",(self.id,));rows=cur.fetchall()
            pending=any(r['outcome'] in ('reserved','unknown') for r in rows)
            done={r['window_id'] for r in rows if r['outcome'] in ('matched','no_match')}
            if reason=='complete' and done!=set(windows):raise StudyFence('study_incomplete')
            status='uncertain' if pending else 'cancelled' if row['cancelled'] or reason=='cancelled' else 'completed' if done==set(windows) else 'paused'
            cur.execute("UPDATE ops.sampling_studies_v1 SET status=%s,owner=NULL,reason=%s,updated_at=now() WHERE id=%s",(status,reason,self.id))
        return status
