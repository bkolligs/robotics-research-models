import unittest
from mentions.lifecycle import summarize


class LifecycleTests(unittest.TestCase):
    def test_release_day_and_introducing_paper_are_excluded(self):
        registry = {'date_basis': 'test', 'verified_on': '2026-10-27', 'models': [
            {'model_id':'pi0','released':'2024-10-31','source':'https://example.com/pi0','intro_paper_ids':['intro']}]}
        rows = [dict(paper_id=pid, model_id=mid, month=month, outcome=outcome) for pid,mid,month,outcome in [
            ('early','pi0','2024-10','beaten'), ('intro','pi0','2024-10','beaten'),
            ('later','pi0','2024-11','beaten'), ('later','rt2','2024-11','beaten'),
            ('other','rt2','2024-11','beaten'), ('uncertain','pi0','2024-11','uncertain_baseline')]]
        dates = {'early':'2024-10-01','intro':'2024-10-31','later':'2024-11-02','other':'2024-11-03'}
        summary = summarize(rows, registry, dates, {'2024-10':10,'2024-11':10})
        self.assertEqual(summary['eligible_post_release_pairs'], 1)
        self.assertEqual(summary['excluded_pre_release_pairs'], 1)
        self.assertEqual(summary['excluded_introduction_pairs'], 1)
        november = summary['monthly'][-1]
        self.assertEqual(november['evaluation_papers'], 2)  # distinct papers, not three model comparisons
        self.assertEqual(november['share'], .5)

    def test_weighted_trailing_share_and_no_future_padding(self):
        registry = {'date_basis':'test','verified_on':'2026-10-27','models':[
            {'model_id':'pi0','released':'2024-10-31','source':'https://example.com/pi0','intro_paper_ids':[]}]}
        rows = [dict(paper_id='a',model_id='pi0',month='2024-11',outcome='beaten')]
        for n in range(9):
            rows.append(dict(paper_id=str(n),model_id='rt2',month='2024-12',outcome='beaten'))
        dates = {'a':'2024-11-02', **{str(n):'2024-12-03' for n in range(9)}}
        summary = summarize(rows,registry,dates,{'2024-11':10,'2024-12':10})
        self.assertEqual(summary['monthly'][-1]['window_share'], .1)  # pooled 1/10, not mean(100%,0%)
        self.assertEqual(summary['monthly'][-1]['months_since_release'], 2)
        self.assertEqual(summary['models'][0]['last_use_month'], '2024-11')
        self.assertEqual(summary['models'][0]['observation_end'], '2024-12')
        self.assertTrue(summary['models'][0]['missing_early_history'])
        self.assertEqual(len(summary['monthly']), 2)

    def test_unscanned_months_are_missing_not_zero(self):
        registry = {'date_basis':'test','verified_on':'2026-10-27','models':[
            {'model_id':'pi0','released':'2024-10-31','source':'https://example.com/pi0','intro_paper_ids':[]}]}
        summary = summarize([],registry,{}, {'2025-01':10,'2025-03':10})
        february = summary['monthly'][1]
        self.assertIsNone(february['papers'])
        self.assertIsNone(february['share'])
        self.assertIsNone(summary['monthly'][-1]['window_share'])
        self.assertIsNone(summary['models'][0]['last_use_month'])
