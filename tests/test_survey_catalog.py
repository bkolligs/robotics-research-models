import copy
import unittest
from mentions.survey_catalog import combine


class SurveyCatalogTests(unittest.TestCase):
    def architecture(self,month,papers,positive):
        return dict(schema=1,threshold=.5,question_set_sha256='same',population='model-papers',
                    generated_at='date',papers_classified=papers,trend_positive=positive,
                    usage={'input_tokens':10},models_returned={'jev':papers},
                    monthly=[dict(month=month,trend='vla',papers=positive,population=papers,trend_positive=positive)],
                    primary_trends=[dict(trend='vla',papers=positive)],
                    multi_label_trends=[dict(trend='vla',label='VLA',papers=positive,examples=[])])

    def test_architecture_preserves_monthly_denominators(self):
        old=self.architecture('2026-09',10,4); new=self.architecture('2026-10',20,15)
        merged=combine([old,new],'architecture-survey','current')
        self.assertEqual(merged['papers_classified'],30)
        self.assertEqual(merged['trend_positive'],19)
        self.assertEqual(merged['multi_label_trends'][0]['share_of_population'],19/30)
        self.assertEqual(merged['monthly'][0],old['monthly'][0])
        self.assertEqual(merged['through'],'2026-10')
        self.assertEqual(merged['usage']['input_tokens'],20)

    def test_overlapping_month_or_policy_change_is_rejected(self):
        old=self.architecture('2026-09',10,4)
        with self.assertRaises(ValueError):
            combine([old,old],'architecture-survey','current')
        new=self.architecture('2026-10',20,15); new['threshold']=.7
        with self.assertRaises(ValueError):
            combine([old,new],'architecture-survey','current')

    def test_evaluation_counts_and_uncertain_outcomes_are_preserved(self):
        part=dict(schema=1,threshold=.7,policy_sha256='same',model_requested='jev',generated_at='date',complete=True,
                  monthly_population={'2026-09':10},papers_classified=4,paper_model_pairs=5,papers_scanned=10,
                  monthly=[dict(month='2026-09',model_id='model',evaluations=2,outcomes={'beaten':2,'uncertain_baseline':3})],
                  totals=[dict(model_id='model',label='Model',mentions=5,evaluations=2,outcomes={'beaten':2,'uncertain_baseline':3})],
                  execution_verification={'policy_sha256':'same','papers':2,'release_recheck_pending':1,'source_counts':{'own_runs':2},'usage':{'input_tokens':5}})
        new=copy.deepcopy(part);new['monthly_population']={'2026-10':10};new['monthly'][0]['month']='2026-10'
        merged=combine([part,new],'evaluations','current')
        self.assertEqual(merged['totals'][0]['evaluations'],4)
        self.assertEqual(merged['totals'][0]['outcomes']['uncertain_baseline'],6)
        self.assertEqual(merged['paper_model_pairs'],10)
        self.assertEqual(merged['execution_verification']['usage']['input_tokens'],10)
        new['complete']=False
        with self.assertRaises(ValueError):
            combine([part,new],'evaluations','current')


class PlotCoverageTests(unittest.TestCase):
    def test_any_stale_plot_blocks_publication(self):
        import json
        import tempfile
        from pathlib import Path
        from scripts.build_analysis_site import check_plot_coverage
        summary={'monthly':{'2026-10':{'papers_scanned':10,'any_model_papers':4}},'variants':[{'papers':5}]}
        fixtures={
            'architecture-survey':{'monthly':[{'month':'2026-10','population':4}]},
            'llm-survey':{'monthly':[{'month':'2026-10','papers_scanned':10}]},
            'evaluations':{'monthly_population':{'2026-10':10},'complete':True,'papers_classified':4,'paper_model_pairs':5},
            'baseline-lifecycle':{'monthly_population':[{'month':'2026-10','scanned_papers':10}],'through':'2026-10'}}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'analysis_provenance.json').write_text(json.dumps({'database_sha256':'current'}))
            for kind in ('architecture-survey','llm-survey','evaluations'):
                fixtures[kind]['source_database_sha256']='current'
            def save(items):
                for kind,value in items.items():
                    (root/kind).mkdir(exist_ok=True)
                    (root/kind/'summary.json').write_text(json.dumps(value))
            save(fixtures)
            check_plot_coverage(root,summary)
            for kind in fixtures:
                stale=copy.deepcopy(fixtures)
                if kind in ('architecture-survey','llm-survey'):
                    stale[kind]['monthly'][0]['month']='2026-09'
                elif kind=='evaluations':
                    stale[kind]['monthly_population']={'2026-09':10}
                else:
                    stale[kind]['through']='2026-09'
                save(stale)
                with self.subTest(kind=kind), self.assertRaises(ValueError):
                    check_plot_coverage(root,summary)
