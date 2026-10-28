import unittest
from mentions.evaluations import adjudicate, build_request, extract_evidence, verified_outcome


class EvaluationTests(unittest.TestCase):
    def test_uncertain_results_do_not_become_wins(self):
        row = {'answers': {'openvla_baseline': {'noul': .95},
                          'openvla_outcome': {'choice': 'beaten', 'probabilities': {'beaten': .55}}}}
        self.assertEqual(adjudicate(row, 'openvla'), 'unclear')
        row['answers']['openvla_baseline']['noul'] = .55
        self.assertEqual(adjudicate(row, 'openvla'), 'uncertain_baseline')
        row['answers']['openvla_baseline']['noul'] = .2
        self.assertEqual(adjudicate(row, 'openvla'), 'not_baseline')

    def test_mixed_and_benchmark_outcomes_survive(self):
        for outcome in ['mixed', 'no_proposed_method', 'baseline_wins', 'tied']:
            row = {'answers': {'openvla_baseline': {'noul': .95},
                              'openvla_outcome': {'choice': outcome, 'probabilities': {outcome: .9}}}}
            self.assertEqual(adjudicate(row, 'openvla'), outcome)

    def test_table_layout_and_release_questions(self):
        models = [{'model_id': 'openvla', 'label': 'OpenVLA'}, {'model_id': 'openvla_oft', 'label': 'OpenVLA-OFT'}]
        text = '4 Experiments\nBaseline          Success\nOpenVLA              40\nOpenVLA-OFT          70\nOurs                 60\n'
        excerpts = extract_evidence(text, models)
        self.assertIn('OpenVLA              40\nOpenVLA-OFT          70', excerpts[0]['text'])
        request = build_request(dict(title='Policy', abstract='', models=models, excerpts=excerpts), 'jev-test')
        self.assertEqual(len(request['questions']), 4)
        self.assertIn('openvla_oft_outcome', request['questions'])

    def test_published_numbers_are_not_active_evaluations(self):
        row = {'answers': {'openvla_baseline': {'noul': .95},
                          'openvla_outcome': {'choice': 'beaten', 'probabilities': {'beaten': .9}}}}
        for source, expected in [('published_scores', 'not_baseline'), ('component_only', 'not_baseline'),
                                 ('unspecified', 'uncertain_baseline'), ('own_runs', 'beaten')]:
            verification = {'answers': {'openvla': {'choice': source, 'probabilities': {source: .9}}}}
            self.assertEqual(verified_outcome(row, 'openvla', verification), expected)
