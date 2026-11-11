import unittest
from scripts.yoon_version_registry import COLUMNS, CHECKS, registration, selection_sql, stage_sql


class RegistryOperatorTests(unittest.TestCase):
    def setUp(self):
        self.id='10000000-0000-4000-8000-000000000001'
        self.other='10000000-0000-4000-8000-000000000002'
        self.review=dict(old_set_id=self.id,new_set_id=self.other,
                         old_snapshot_sha256='a'*64,new_snapshot_sha256='b'*64,
                         reviewer='Independent reviewer',checks={k:True for k in CHECKS})

    def test_exact_nonnull_cas(self):
        for rev in (None,False,-1,'0'):
            with self.assertRaises(ValueError):
                selection_sql(self.id,self.id,rev,self.other,self.review)
        sql=selection_sql(self.id,self.id,0,self.other,self.review)
        self.assertIn('ops.yoon_registry_lock()',sql)
        self.assertIn('ops.yoon_release_reviews',sql)
        self.assertTrue(sql.endswith('COMMIT;'))

    def test_no_inferred_review(self):
        self.review['checks']['import_complete']=False
        with self.assertRaises(ValueError):
            selection_sql(self.id,self.id,0,self.other,self.review)

    def test_no_implicit_execution_approval(self):
        row={k:None for k in COLUMNS}
        row.update(staging_approved=True,processing_approved=True,released=False,
                   frozen=False,predecessor_set_id=self.id)
        with self.assertRaises(ValueError):
            stage_sql(row,{})

    def test_no_unrecognized_registry_columns(self):
        with self.assertRaises(ValueError):
            registration({'set_id':self.id,'sql':'anything'})

if __name__=='__main__': unittest.main()
