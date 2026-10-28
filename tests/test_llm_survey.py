from __future__ import annotations

import unittest

from mentions.llm_survey import (
    QUESTION_SET_SHA256,
    candidate_rows,
    classify_candidate,
    find_llm_mentions,
    summarize,
)


class LlmSurveyTests(unittest.TestCase):
    def test_qualified_aliases_and_version_boundaries(self):
        self.assertEqual(set(find_llm_mentions("GPT-6 Astra controls the robot")), {"gpt6_astra"})
        self.assertEqual(set(find_llm_mentions("GPT-6-Astra controls the robot")), {"gpt6_astra"})
        self.assertEqual(set(find_llm_mentions("Claude Fable 5.1 is evaluated")), {"claude_fable_51"})
        self.assertEqual(set(find_llm_mentions("Fable 5 and Fable 5.1")), {
            "claude_fable_5", "claude_fable_51",
        })
        self.assertEqual(find_llm_mentions("Astra is a mobile robot architecture"), {})
        self.assertEqual(find_llm_mentions("the introduction tells a fable"), {})

    def test_candidate_rows_include_sampled_context(self):
        record = {
            "id": "2609.00001",
            "published": "2026-09-10T00:00:00Z",
            "title": "Robot agents",
            "summary": "We evaluate a frontier model.",
        }
        rows = candidate_rows(record, "Methods: we directly run GPT-6 Astra on the robot.")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["model_id"], "gpt6_astra")
        self.assertIn("directly run GPT-6 Astra", rows[0]["contexts"][0])

    def test_classification_is_auditable_and_typed(self):
        candidate = candidate_rows({
            "id": "2609.00001",
            "published": "2026-09-10T00:00:00Z",
            "title": "Robot agents",
            "summary": "We evaluate GPT-6 Astra.",
        }, "We run GPT-6 Astra as the policy.")[0]

        def fake_request(payload, key, timeout):
            self.assertEqual(payload["state"]["named_model"], "GPT-6 Astra")
            return {
                "model": "jev-test",
                "answers": {
                    "used_in_study": {"noul": 0.98},
                    "usage_role": {"choice": "robot_system_component"},
                },
                "usage": {"input_tokens": 12, "output_tokens": 3},
            }

        row = classify_candidate(candidate, "jev-test", "secret", request_json=fake_request)
        self.assertEqual(row["question_set_sha256"], QUESTION_SET_SHA256)
        self.assertEqual(row["model_id"], "gpt6_astra")

    def test_summary_keeps_mentions_and_usage_separate(self):
        base = {
            "paper_id": "2609.00001", "month": "2026-09", "title": "Robot agents",
            "model_id": "gpt6_astra", "model_label": "GPT-6 Astra",
        }
        candidates = [{**base, "abstract": "", "contexts": [], "matched_aliases": []}]
        decisions = [{
            **base,
            "model_returned": "jev-test",
            "answers": {
                "used_in_study": {"noul": 0.9},
                "usage_role": {"choice": "direct_evaluation_target"},
            },
            "usage": {},
        }]
        result, monthly = summarize(candidates, decisions, {"2026-09": 100}, 0.5, "dbhash")
        self.assertEqual(result["papers_mentioning_tracked_llm"], 1)
        self.assertEqual(result["papers_using_tracked_llm"], 1)
        astra = next(row for row in monthly if row["model_id"] == "gpt6_astra")
        self.assertEqual(astra["mention_rate_scanned"], 0.01)
        self.assertEqual(astra["usage_share_of_mentions"], 1.0)


if __name__ == "__main__":
    unittest.main()
