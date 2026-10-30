import copy
import tempfile
import unittest
from pathlib import Path
from benchmark.common import dataset, save
from benchmark.__main__ import inputs
from benchmark.quality import evaluate
from benchmark.audit import stats
from benchmark.scoring import score


class Tests(unittest.TestCase):
    def setUp(self):
        self.r={'positive':[dict(id='P1',weight=100)],'negative':[]}
        self.raw={'status':'complete','missing_requirements':[],
            'positive':[dict(id='P1',verdict=True,reason='satisfied',quotes=['text'],unresolved_contradictions=[])],
            'negative':[],'fact_reviews':[],'fact_errors':[]}

    def test_dataset(self):
        q,r=dataset();self.assertEqual(len(q),230);self.assertEqual(q.keys(),r.keys())

    def test_saved_audit_recovery_checks_frozen_inputs(self):
        from benchmark.audit import recover
        from benchmark.common import sha
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td);work=folder/'workspace';work.mkdir()
            save(work/'case.json',{'case_id':'q'})
            save(folder/'frozen-inputs.json',{'case.json':sha((work/'case.json').read_bytes())})
            save(work/'result.json',{'case_id':'q','items':[],'summary':'no facts','limitations':[]})
            self.assertIsNotNone(recover(work,'q',[]))
            save(work/'case.json',{'case_id':'other'})
            self.assertIsNone(recover(work,'q',[]))

    def test_duplicate_input(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'a.json';save(p,[{'id':'q','answer':'x'}]*2)
            with self.assertRaisesRegex(ValueError,'duplicate'):inputs(p,{'q':{'question':'?'}})

    def test_full_predicate_contradiction_cannot_pass(self):
        self.raw['positive'][0]['unresolved_contradictions']=['text']
        with self.assertRaisesRegex(ValueError,'contradiction'):evaluate(self.raw,self.r,'text',{'items':[]})

    def test_trace_support_does_not_skip_fact_conflict(self):
        audit={'items':[dict(claim_id='c1',trace_verdict='supported',factual_verdict='contradicted')]}
        with self.assertRaisesRegex(ValueError,'Every factual'):evaluate(self.raw,self.r,'text',audit)
        s=stats(audit);self.assertEqual(s['evidence_support_rate'],1);self.assertEqual(s['factual_contradiction_rate'],1)

    def test_scorer_dedup_and_positive_credit(self):
        r={'positive':[dict(id='P1',weight=10),dict(id='P2',weight=90)],'negative':[
            dict(id='N1',penalty_points=12,score_cap=None,dedup_group='same',overlap_positive_ids=['P1'],invalidates_positive_ids=['P1']),
            dict(id='N2',penalty_points=25,score_cap=60,dedup_group='same',overlap_positive_ids=['P1'],invalidates_positive_ids=['P1'])]}
        j={'positive':[dict(id='P1',verdict=False),dict(id='P2',verdict=True)],'negative':[dict(id='N1',verdict=True),dict(id='N2',verdict=True)]}
        result=score(j,r);self.assertEqual(result['penalty'],15);self.assertEqual(result['score'],60)

    def test_missing_facts_are_not_false(self):
        s=stats({'items':[dict(trace_verdict='incomplete',factual_verdict='unresolved')]})
        self.assertEqual(s['factual_contradiction_rate'],0);self.assertEqual(s['policy_pass_rate'],1);self.assertEqual(s['evidence_support_rate'],0)

    def test_independent_score(self):
        v=evaluate(self.raw,self.r,'text',{'items':[]});self.assertEqual(v['independent_score'],100)

    def test_invented_threshold_and_severity(self):
        raw=copy.deepcopy(self.raw);raw['positive'][0]['verdict']=False
        raw['fact_reviews']=[dict(claim_id='c',actionable=True,error_id='E1',reason='refuted',quotes=['text'])]
        e=dict(id='E1',claim_ids=['c'],original_negative_id=None,severity='CORE',reason='refuted',correction_unit='one',quotes=['text'],scope_positive_ids=['P1'],affected_positive_ids=['P1'],causal_credit_positive_ids=[],causal_credit_reason='no credit',dependency_chain='source to conclusion',counterfactual='changes conclusion',unaffected_conclusions=['none'],role='decision_threshold',threshold_proof=dict(original_threshold=10,corrected_threshold=20,test_value=15,operator='gt',unit='%',source_value='10'))
        raw['fact_errors']=[e]
        a={'items':[dict(claim_id='c',factual_verdict='contradicted')]}
        with self.assertRaisesRegex(ValueError,'grounded'):evaluate(raw,self.r,'text',a)
        e.update(role='supporting_detail',threshold_proof=None,severity='MINOR')
        with self.assertRaisesRegex(ValueError,'Severity'):evaluate(raw,self.r,'text',a)

if __name__=='__main__':unittest.main()
