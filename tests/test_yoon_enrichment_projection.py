import unittest
from unittest.mock import patch
from worker.jobs.yoon_enrichment_projection import FULL_SQL,PROJECTED_SQL,evidence_sql
from worker.jobs.yoon_version_sources import VERSION_ENRICHMENT_RUNS
from worker.jobs.yoon_spotify_enrich import RUN
class EnrichmentProjectionTests(unittest.TestCase):
 def test_finite_corrected_allowlist_and_legacy_fallback(self):
  self.assertEqual(len(VERSION_ENRICHMENT_RUNS),10)
  for run in VERSION_ENRICHMENT_RUNS:self.assertEqual(evidence_sql(run),PROJECTED_SQL)
  for run in (RUN,'unknown',None):self.assertEqual(evidence_sql(run),FULL_SQL)
 def test_low_recursion_retains_original(self):
  with patch('worker.jobs.yoon_enrichment_projection.sys.getrecursionlimit',return_value=511):
   for run in VERSION_ENRICHMENT_RUNS:self.assertEqual(evidence_sql(run),FULL_SQL)
 def test_bound_query_scope_and_read_lock_preserved(self):
  for sql in (FULL_SQL,PROJECTED_SQL):
   self.assertEqual(sql.count('%s'),1);self.assertIn('WHERE set_run_id=%s ORDER BY segment_index FOR SHARE',sql)
  self.assertIn('[0-9]{255}',PROJECTED_SQL);self.assertIn('>=128',PROJECTED_SQL)
if __name__=='__main__':unittest.main()
