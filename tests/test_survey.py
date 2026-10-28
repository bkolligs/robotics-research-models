import json
import tempfile
import unittest
from pathlib import Path

from mentions.survey import (
    QUESTION_SET_SHA256,
    QUESTIONS,
    TRENDS,
    build_request,
    classify_paper,
    read_completed,
    summarize,
)


def answer_row(paper_id, month, primary, relevance, **trend_scores):
    answers = {
        "architecture_relevant": {"type": "noul", "noul": relevance},
        "primary_trend": {"type": "choice", "choice": primary, "confidence": 0.9},
        "other_architecture": {"type": "noul", "noul": trend_scores.get("other_architecture", 0)},
    }
    for trend in TRENDS:
        answers[trend] = {"type": "noul", "noul": trend_scores.get(trend, 0)}
    return {
        "paper_id": paper_id,
        "month": month,
        "title": f"Paper {paper_id}",
        "question_set_sha256": QUESTION_SET_SHA256,
        "model_requested": "jev-test",
        "model_returned": "jev-test",
        "answers": answers,
        "usage": {"input_tokens": 10, "output_tokens": 2},
    }


class SurveyTests(unittest.TestCase):
    def test_request_asks_independent_questions(self):
        request = build_request(
            {"id": "1", "month": "2026-01", "title": "A VLA", "abstract": "Maps images to actions."},
            "jev-test",
        )
        self.assertEqual(request["model"], "jev-test")
        self.assertEqual(request["questions"]["primary_trend"]["type"], "choice")
        self.assertEqual(request["questions"]["vision_language_action"]["type"], "noul")
        self.assertIn("abstract", request["state"])

    def test_summary_uses_relevant_denominator_and_allows_overlap(self):
        rows = [
            answer_row("1", "2026-01", "vision_language_action", 0.9,
                       vision_language_action=0.95, generative_action_policy=0.8),
            answer_row("2", "2026-01", "not_architecture", 0.2,
                       vision_language_action=0.8),
            answer_row("3", "2026-02", "world_action_model", 0.7,
                       world_action_model=0.9, world_model=0.85),
        ]
        result, monthly = summarize(rows, 0.5, "model-papers", "db-hash")
        self.assertEqual(result["papers_classified"], 3)
        self.assertEqual(result["trend_positive"], 3)
        self.assertEqual(len(result["monthly"]), len(monthly))
        self.assertEqual(result["trend_definitions"]["world_action_model"]["label"], "World-action models")
        totals = {row["trend"]: row["papers"] for row in result["multi_label_trends"]}
        self.assertEqual(totals["vision_language_action"], 2)
        self.assertEqual(totals["generative_action_policy"], 1)
        self.assertEqual(totals["world_action_model"], 1)
        self.assertEqual(totals["world_model"], 1)
        jan_vla = next(row for row in monthly if row["month"] == "2026-01" and row["trend"] == "vision_language_action")
        self.assertEqual(jan_vla["trend_positive"], 2)
        self.assertEqual(jan_vla["share_of_trend_positive"], 1)

    def test_resume_ignores_other_question_sets_and_models(self):
        current = answer_row("1", "2026-01", "vision_language_action", 0.9)
        wrong_model = {**answer_row("2", "2026-01", "vision_language_action", 0.9), "model_requested": "other"}
        wrong_questions = {**answer_row("3", "2026-01", "vision_language_action", 0.9), "question_set_sha256": "old"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "raw.jsonl"
            path.write_text("\n".join(json.dumps(row) for row in (current, wrong_model, wrong_questions)) + "\n")
            completed = read_completed(path, "jev-test")
        self.assertEqual(set(completed), {"1"})

    def test_classification_retries_connection_errors(self):
        calls = []

        def request_json(payload, api_key, timeout):
            calls.append(payload)
            if len(calls) == 1:
                raise OSError("connection reset")
            answers = {
                key: ({"type": "choice", "choice": "not_architecture", "confidence": 1}
                      if question["type"] == "choice" else {"type": "noul", "noul": 0})
                for key, question in QUESTIONS.items()
            }
            return {"model": "jev-test", "answers": answers, "usage": {}}

        result = classify_paper(
            {"id": "1", "month": "2026-01", "title": "Test", "abstract": "Test"},
            "jev-test", "secret", retries=2, request_json=request_json,
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["model_returned"], "jev-test")


if __name__ == "__main__":
    unittest.main()
