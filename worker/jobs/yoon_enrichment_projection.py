"""Consumer-specific evidence projection; no durable JSON or validator changes.

Only the ten registered corrected fresh runs use it. Legacy origin validation
compares complete responses and must use the full query. Exact absent/null and
malformed shapes are retained. Provider match arrays remain exact; track objects
retain their type/presence, the only aspects this validator consumes. This is
not an audit/recovery reader and not a generic checkpoint representation.
"""
import sys
from worker.jobs.yoon_version_sources import VERSION_ENRICHMENT_RUNS

FULL_SQL = ('SELECT segment_index,raw_data FROM ops.segment_hits '
            'WHERE set_run_id=%s ORDER BY segment_index FOR SHARE')


def _object(expression, alias, replacements=None, keys=None):
    key,value=f'{alias}.k',f'{alias}.v'
    clauses=' '.join(f"WHEN {key}='{k}' THEN {v}" for k,v in (replacements or {}).items())
    selected=f'CASE {clauses} ELSE {value} END' if clauses else value
    where=' WHERE '+key+' IN ('+','.join(repr(k) for k in keys)+')' if keys else ''
    return f"""CASE WHEN jsonb_typeof({expression})='object' THEN
      (SELECT coalesce(jsonb_object_agg({key},{selected}),'{{}}'::jsonb)
       FROM jsonb_each({expression}) AS {alias}(k,v){where})
      ELSE {expression} END"""

_PROVIDER=_object('response_fields.v','provider_fields',{
    'track':"CASE WHEN jsonb_typeof(provider_fields.v)='object' THEN '{}'::jsonb ELSE provider_fields.v END",
},('matches','track'))
_RESPONSE=_object('evidence_fields.v','response_fields',{'raw_data':_PROVIDER})
_EVIDENCE=_object('root_fields.v','evidence_fields',{'response':_RESPONSE})
_RAW=_object('raw_data','root_fields',{'private_jackson_v2':_EVIDENCE})
# Removing an unused field must not bypass known baseline JSON decoder failures.
# Conservative guards include digits/brackets inside strings: false positives
# only retain the full original row.255 digits is below CPython's minimum640
# configured integer-digit limit.128 opening braces/brackets is below ordinary
# JSON recursion limits. Nonstandard low interpreter recursion disables this.
_BODY_TEXT="(raw_data#>'{private_jackson_v2,response,raw_data}')::text"
_HAZARD=f"({_BODY_TEXT} ~ '[0-9]{{255}}' OR length({_BODY_TEXT})-length(translate({_BODY_TEXT},'{{[',''))>=128)"
_SAFE_RAW=f"CASE WHEN {_HAZARD} THEN raw_data ELSE {_RAW} END"
PROJECTED_SQL=f'''SELECT segment_index,{_SAFE_RAW} AS raw_data FROM ops.segment_hits
    WHERE set_run_id=%s ORDER BY segment_index FOR SHARE'''


def evidence_sql(run_id):
    # Keep the same bound WHERE and FOR SHARE. Registration does not bypass the
    # existing independent identity, scope, source, audience or evidence checks.
    return PROJECTED_SQL if run_id in VERSION_ENRICHMENT_RUNS and sys.getrecursionlimit()>=512 else FULL_SQL
