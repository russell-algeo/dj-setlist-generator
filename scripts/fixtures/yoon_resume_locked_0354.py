"""Frozen locked() oracle from deployed 0354a917252356083417a43fd9b2af318c2d616d.

The method below is copied byte-for-byte, not derived from candidate runtime.
Only initialization is inherited; the selected SQL and Python guards are frozen.
PRIVATE_GUARD is separately frozen and checked by the test before execution.
"""
from contextlib import contextmanager
from worker.recognition_transactions import recognition_transaction
from worker.jobs.yoon_sources import JACKSON, reviewed_source
from worker.jobs.yoon_resume_store import ResumeStore as CandidateStore

FROZEN_PRIVATE_GUARD = "\n    r.id = %s AND r.publication_visibility = 'private'\n    AND r.target_set_id = s.id AND s.visibility = 'private'\n    AND r.collection_id = s.collection_id\n    AND u.id = r.submission_id AND u.visibility = 'private'\n    AND u.collection_id = r.collection_id AND r.cancel_requested_at IS NULL\n    AND r.published_set_id IS NULL AND r.create_playlist = false\n"
LOCKED_SHA256 = '93c5e12b77daf298a04a2dfd881f558e053cb2805bba8c18273e24791bdfd81a'


class ResumeStore(CandidateStore):
    @contextmanager
    def locked(self, *, owner=True, admission=False):
        from worker.jobs.yoon_once import PRIVATE_GUARD, validate_descriptor
        with recognition_transaction(self.connect) as conn, conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout = '5s'")
            cur.execute("SET LOCAL statement_timeout = '15s'")
            if admission:
                from worker.jobs.yoon_admission import lock
                lock(cur)
            cur.execute('''SELECT r.*, extract(epoch from clock_timestamp())::float8 AS db_now
                FROM ops.set_runs r, app.sets s, ops.submissions u, app.archive_collections c WHERE ''' + PRIVATE_GUARD + '''
                AND u.cancel_requested_at IS NULL AND u.create_playlist=false
                AND r.requested_by=u.requested_by AND c.id=r.collection_id
                FOR UPDATE OF r,u''', (self.run_id,))
            row = cur.fetchone()
            if not row:
                raise RuntimeError('private_resume_scope_required')
            descriptor = row['source_metadata'].get('yoon_fixed_input')
            validate_descriptor(descriptor)
            source = reviewed_source(descriptor)
            self.source = source
            state = dict(row['source_metadata'].get('yoon_resume') or {})
            if descriptor.get('recognition_mode') != 'resumable' or state.get('version') != 1:
                raise RuntimeError('private_resume_required')
            if source != JACKSON and (state.get('initialization_mode') != 'fresh'
                    or state.get('origin') or state.get('provenance_seeded')):
                raise RuntimeError('private_fresh_source_required')
            if source != JACKSON or 'source_id' in state:
                if (state.get('source_id') != source.id
                        or state.get('source_pins') != source.pins()):
                    raise RuntimeError('private_resume_source_changed')
            cur.execute('''SELECT user_id,role FROM app.archive_collection_members
                WHERE collection_id=%s ORDER BY user_id''', (row['collection_id'],))
            members = [{'user_id': str(r['user_id']), 'role': r['role']} for r in cur.fetchall()]
            if len(members) != 2 or members != state.get('members'):
                raise RuntimeError('private_resume_audience_changed')
            if owner and (row['status'] != 'private_resume_running' or
                          any(state.get(k) != v for k,v in self.owner.items())):
                raise RuntimeError('private_resume_owner_changed')
            yield cur, row, state

