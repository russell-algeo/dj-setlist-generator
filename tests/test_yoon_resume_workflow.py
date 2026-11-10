import itertools
from pathlib import Path
import re
import unittest

class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text=(Path(__file__).resolve().parents[1]/'.github/workflows/process-set.yml').read_text()
        pieces=re.split(r'^  ([a-z][a-z-]+):\n',cls.text.split('\njobs:\n',1)[1],flags=re.M)
        cls.jobs=dict(zip(pieces[1::2],pieces[2::2]))
    def test_release_has_only_private_owner_operation(self):
        job=self.jobs['private-release']
        for token in ['worker.callbacks','worker.jobs.process_set','upload-artifact','GH_PAT','PRODUCTION_DATABASE']:
            self.assertNotIn(token,job)
        self.assertIn('python -m worker.jobs.yoon_once release >/dev/null 2>&1',job)
        expr=re.search(r'if: \$\{\{ (.*?) \}\}',job).group(1)
        for enrichment,private,target,ref,tests in itertools.product(['true','false',''],['true','false',''],['development','production'],['refs/heads/preview','refs/heads/remote-deployment'],['success','failure','cancelled','skipped']):
            value=expr
            for key,replacement in {'github.event.inputs.private_enrichment_only':enrichment,'github.event.inputs.private_analysis':private,'github.event.inputs.deployment_target':target,'github.ref':ref,'github.repository':'russell-algeo/dj-setlist-generator','needs.private-offline-tests.result':tests,'github.event.inputs.resume_mode':'full'}.items():
                value=value.replace(key,repr(replacement))
            actual=eval(value.replace('always()','True').replace('&&',' and '),{'__builtins__':{}},{})
            self.assertEqual(actual,enrichment!='true' and private=='true' and target=='development' and ref=='refs/heads/preview' and tests=='success')
    def test_audio_is_attempt_scoped_and_completion_skips_media(self):
        for name in ['private-prepare','private-recognize']:
            self.assertIn('analysis-audio-${{ github.run_id }}-${{ github.run_attempt }}',self.jobs[name])
        prepare=self.jobs['private-prepare'];recognize=self.jobs['private-recognize']
        self.assertIn('retention-days: 1',prepare)
        self.assertIn("steps.private_prepare.outputs.complete != 'true'",prepare)
        self.assertIn("needs.private-prepare.outputs.complete != 'true'",recognize)
        self.assertNotIn('always()',recognize.split('steps:',1)[0])
        self.assertIn('complete: ${{ steps.private_prepare.outputs.complete }}',prepare)
    def test_private_matrix_uses_shared_scheduler_and_two_requests_per_slot(self):
        prepare=self.jobs['private-prepare'];recognize=self.jobs['private-recognize']
        self.assertIn('slot_matrix: ${{ steps.private_prepare.outputs.slot_matrix }}',prepare)
        self.assertIn('fromJson(needs.private-prepare.outputs.slot_matrix)',recognize)
        self.assertIn("CONCURRENT_RECOGNITIONS: '2'",recognize)
        self.assertIn('PRIVATE_SLOT_INDEX: ${{ matrix.slot_index }}',recognize)
        self.assertIn('fail-fast: false',recognize)
        self.assertNotIn('strategy:',self.jobs['private-release'])

    def test_normal_paths_and_permissions_remain_separate(self):
        for name in ['bootstrap','recognize','publish','finalize']:
            self.assertIn("github.event.inputs.private_analysis != 'true'",self.jobs[name].split('runs-on:',1)[0])
            self.assertIn("github.event.inputs.private_enrichment_only != 'true'",self.jobs[name].split('runs-on:',1)[0])
        self.assertIn('permissions:\n  contents: read\n',self.text)
        self.assertNotIn('actions: write',self.text)
        self.assertNotIn('actions: read',self.text)
        offline=self.jobs['private-offline-tests'];self.assertNotIn('secrets.',offline)
        self.assertIn("python-version: '3.11'",offline)

if __name__=='__main__':unittest.main()
