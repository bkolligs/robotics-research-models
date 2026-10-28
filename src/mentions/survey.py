"""Classify architectural trends in robotics papers with TypeSafe Jev.

This is deliberately separate from the full-text name-matching study. The
survey asks Jev about the primary contribution described by each title and
abstract; it does not alter model mentions, matching, or their denominators.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import http.client
import json
import os
import random
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Callable, Iterable


API_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-1.14.0"
SCHEMA_VERSION = 1

# These are multi-label hypotheses. The primary_trend Choice below uses the
# same definitions, plus non-architecture and catch-all options.
TRENDS = {
    "vision_language_action": (
        "A vision-language-action (VLA) or closely related multimodal policy "
        "maps visual observations and language instructions to robot actions."
    ),
    "world_action_model": (
        "A world-action model predicts future observations, states, or consequences "
        "conditioned on candidate robot actions for planning or action selection, or "
        "jointly models future dynamics and actions."
    ),
    "agentic_robotics": (
        "An agentic robot architecture performs autonomous long-horizon reasoning, "
        "planning, tool or skill use, reflection, self-improvement, or recovery."
    ),
    "world_model": (
        "A learned world or dynamics model predicts future observations, states, "
        "outcomes, or latent dynamics for planning or control, without necessarily "
        "being a coupled world-action model."
    ),
    "generative_action_policy": (
        "The robot policy generates actions or trajectories with diffusion, flow "
        "matching, autoregressive generation, or another generative process."
    ),
    "action_expert_modularity": (
        "The architecture separates or composes a semantic vision-language backbone "
        "with an action expert, mixture of experts, dual stream, or other specialized "
        "policy module."
    ),
    "action_representation_tokenization": (
        "The main architecture contribution changes action representations, action "
        "tokenization, chunking, discretization, trajectory parameterization, or "
        "the prediction horizon."
    ),
    "hierarchical_planning_control": (
        "The architecture explicitly separates high-level task reasoning or planning "
        "from low-level skills, motion generation, or control."
    ),
    "spatial_3d_reasoning": (
        "The architecture makes explicit 3D, geometric, spatial, point-cloud, depth, "
        "scene-graph, or spatial-token reasoning central to action generation."
    ),
    "cross_embodiment_generalist": (
        "The abstract explicitly trains, shares, transfers, or evaluates one learned policy "
        "across at least two distinct robot embodiments, morphologies, or platforms. Multiple "
        "objects, scenes, tasks, or copies of the same robot platform are not enough."
    ),
    "memory_retrieval": (
        "Persistent memory, episodic experience, retrieval, reusable skills, or a "
        "failure bank is a central model component."
    ),
    "multisensory_tactile": (
        "The model architecture fuses tactile, force, audio, proprioceptive, event, "
        "or other non-visual sensing with robot decision-making."
    ),
    "critics_verifiers": (
        "A dedicated learned critic, verifier, reward/value model, uncertainty estimator, "
        "outcome scorer, or failure predictor evaluates proposed or executed behavior."
    ),
    "runtime_adaptation_recovery": (
        "The architecture explicitly learns or adapts online from execution feedback, "
        "corrects actions at runtime, recovers from failure, or self-improves after rollout."
    ),
    "safety_alignment": (
        "A dedicated architecture component explicitly enforces safety constraints, filters "
        "unsafe actions, monitors hazards, or aligns behavior for physical safety. Merely "
        "claiming robustness, reliability, or adaptation is not enough."
    ),
    "data_scaling_pretraining": (
        "The main model contribution explicitly scales or pretrains across large or diverse "
        "robot data, human video, simulation, synthetic data, or web data. Ordinary training, "
        "one-shot learning, or a small task-specific dataset is not enough."
    ),
    "data_efficient_adaptation": (
        "The architecture is designed for few-shot, one-demonstration, parameter-efficient, "
        "rapid post-training, transfer, or other data-efficient adaptation to new tasks."
    ),
    "efficient_deployment": (
        "The main architecture contribution targets real-time inference, on-device or "
        "edge deployment, compression, sparsity, fewer denoising steps, or lower latency."
    ),
}

TREND_LABELS = {
    "vision_language_action": "Vision-language-action",
    "world_action_model": "World-action models",
    "agentic_robotics": "Agentic robotics",
    "world_model": "World models",
    "generative_action_policy": "Generative action policies",
    "action_expert_modularity": "Action experts and modularity",
    "action_representation_tokenization": "Action representations and tokenization",
    "hierarchical_planning_control": "Hierarchical planning and control",
    "spatial_3d_reasoning": "Spatial and 3D reasoning",
    "cross_embodiment_generalist": "Cross-embodiment generalists",
    "memory_retrieval": "Memory and retrieval",
    "multisensory_tactile": "Multisensory and tactile",
    "critics_verifiers": "Critics and verifiers",
    "runtime_adaptation_recovery": "Runtime adaptation and recovery",
    "safety_alignment": "Safety and alignment",
    "data_scaling_pretraining": "Data scaling and pretraining",
    "data_efficient_adaptation": "Data-efficient adaptation",
    "efficient_deployment": "Efficient deployment",
    "other_architecture": "Other architecture",
}

PRIMARY_CRITERIA = {
    **TRENDS,
    "dataset_benchmark_evaluation": (
        "The primary contribution is a dataset, benchmark, survey, evaluation, analysis, "
        "or diagnostic rather than a new or materially changed model architecture."
    ),
    "application_control_hardware": (
        "The primary contribution applies existing methods, develops classical planning "
        "or control, or focuses on hardware/system integration rather than model architecture."
    ),
    "other_architecture": (
        "The primary contribution is a model architecture, but its main architectural "
        "trend is not described by any other option."
    ),
    "not_architecture": (
        "The title and abstract do not establish a model-architecture contribution."
    ),
}


def questions() -> dict:
    result = {
        "architecture_relevant": {
            "type": "noul",
            "instructions": (
                "The paper's primary contribution introduces, analyzes, or materially changes "
                "a learned robot model, policy, agent architecture, action-generation mechanism, "
                "or learned planning component, or makes one of these the central object of "
                "evaluation. Merely citing a model or contributing only a general dataset, "
                "benchmark, hardware system, or classical controller is false."
            ),
        },
        "primary_trend": {
            "type": "choice",
            "instructions": (
                "Which single option best describes the paper's primary learned-model, policy, "
                "agent, or action-generation contribution from its title and abstract? Choose a "
                "non-architecture option when the abstract does not establish such a contribution."
            ),
            "criteria": PRIMARY_CRITERIA,
        },
        "other_architecture": {
            "type": "noul",
            "instructions": (
                "The paper has a substantive model-architecture contribution whose central "
                "trend is not covered by the named architectural trend questions."
            ),
        },
    }
    for trend, description in TRENDS.items():
        result[trend] = {
            "type": "noul",
            "instructions": (
                f"This trend is a substantive subject of the paper's proposed, analyzed, "
                f"evaluated, or applied architecture, not merely background or related work: "
                f"{description}"
            ),
        }
    return result


QUESTIONS = questions()
QUESTION_SET_SHA256 = hashlib.sha256(
    json.dumps(QUESTIONS, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()


def database_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_papers(database: Path, population: str, since: str | None = None) -> list[dict]:
    db = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    where = []
    params: list[str] = []
    if population == "model-papers":
        where.append("EXISTS (SELECT 1 FROM mentions m WHERE m.paper_id = p.id)")
    if since:
        where.append("p.month >= ?")
        params.append(since)
    query = "SELECT p.id,p.month,p.title,p.abstract FROM papers p"
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY p.month,p.id"
    rows = [dict(row) for row in db.execute(query, params)]
    db.close()
    return rows


def build_request(paper: dict, model: str) -> dict:
    return {
        "state": {
            "document_type": "robotics research paper title and abstract",
            "title": paper["title"],
            "abstract": paper["abstract"],
            "guidance": (
                "Judge the paper's own primary contribution. Do not infer claims absent from "
                "the abstract, and do not count architecture names that appear only as context "
                "or related work. Multiple trend questions may be true."
            ),
        },
        "model": model,
        "questions": QUESTIONS,
    }


def _request_json(payload: dict, api_key: str, timeout: float) -> dict:
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "robotics-research-models/architecture-survey",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def classify_paper(
    paper: dict,
    model: str,
    api_key: str,
    timeout: float = 60,
    retries: int = 5,
    request_json: Callable[[dict, str, float], dict] = _request_json,
) -> dict:
    payload = build_request(paper, model)
    for attempt in range(retries):
        try:
            response = request_json(payload, api_key, timeout)
            answers = response.get("answers")
            if not isinstance(answers, dict) or set(answers) != set(QUESTIONS):
                raise ValueError("Jev response does not contain the expected answers")
            return {
                "schema": SCHEMA_VERSION,
                "paper_id": paper["id"],
                "month": paper["month"],
                "title": paper["title"],
                "abstract_sha256": hashlib.sha256(paper["abstract"].encode()).hexdigest(),
                "question_set_sha256": QUESTION_SET_SHA256,
                "model_requested": model,
                "model_returned": response.get("model"),
                "classified_at": datetime.now(timezone.utc).isoformat(),
                "answers": answers,
                "usage": response.get("usage", {}),
            }
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")[:500]
            if exc.code not in {408, 409, 429, 500, 502, 503, 504} or attempt + 1 == retries:
                raise RuntimeError(f"TypeSafe API HTTP {exc.code}: {body}") from exc
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            http.client.HTTPException,
            json.JSONDecodeError,
        ) as exc:
            if attempt + 1 == retries:
                raise RuntimeError(f"TypeSafe API request failed: {exc}") from exc
        except ValueError as exc:
            if attempt + 1 == retries:
                raise RuntimeError(f"TypeSafe API returned an invalid response: {exc}") from exc
        time.sleep(min(16, 2**attempt) + random.random())
    raise AssertionError("retry loop exhausted")


def read_completed(path: Path, model: str) -> dict[str, dict]:
    completed = {}
    if not path.exists():
        return completed
    with path.open() as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on {path}:{number}") from exc
            if row.get("question_set_sha256") == QUESTION_SET_SHA256 and row.get("model_requested") == model:
                completed[row["paper_id"]] = row
    return completed


def _noul(row: dict, question: str) -> float:
    return float(row["answers"][question]["noul"])


def _is_relevant(row: dict, threshold: float) -> bool:
    return any(
        _noul(row, trend) >= threshold for trend in [*TRENDS, "other_architecture"]
    )


def summarize(
    rows: Iterable[dict],
    threshold: float,
    population: str,
    source_database_sha256: str,
) -> tuple[dict, list[dict]]:
    rows = list(rows)
    relevant = [row for row in rows if _is_relevant(row, threshold)]
    monthly_population = Counter(row["month"] for row in rows)
    monthly_relevant = Counter(row["month"] for row in relevant)
    primary = Counter(row["answers"]["primary_trend"]["choice"] for row in relevant)
    multi = {
        trend: [row for row in relevant if _noul(row, trend) >= threshold]
        for trend in [*TRENDS, "other_architecture"]
    }
    monthly_multi: dict[str, Counter] = defaultdict(Counter)
    for trend, trend_rows in multi.items():
        for row in trend_rows:
            monthly_multi[row["month"]][trend] += 1
    usage = Counter()
    for row in rows:
        for key, value in row.get("usage", {}).items():
            if isinstance(value, int):
                usage[key] += value
    trend_totals = []
    for trend, trend_rows in multi.items():
        examples = sorted(trend_rows, key=lambda row: (-_noul(row, trend), row["paper_id"]))[:5]
        trend_totals.append({
            "trend": trend,
            "label": TREND_LABELS[trend],
            "papers": len(trend_rows),
            "share_of_population": len(trend_rows) / len(rows) if rows else None,
            "share_of_trend_positive": len(trend_rows) / len(relevant) if relevant else None,
            "examples": [
                {"id": row["paper_id"], "title": row["title"], "probability": _noul(row, trend)}
                for row in examples
            ],
        })
    trend_totals.sort(key=lambda row: (-row["papers"], row["trend"]))
    monthly = []
    for month in sorted(monthly_population):
        for trend in [*TRENDS, "other_architecture"]:
            count = monthly_multi[month][trend]
            monthly.append({
                "month": month,
                "trend": trend,
                "papers": count,
                "population": monthly_population[month],
                "trend_positive": monthly_relevant[month],
                "share_of_population": count / monthly_population[month],
                "share_of_trend_positive": (
                    count / monthly_relevant[month] if monthly_relevant[month] else None
                ),
            })
    result = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_database_sha256": source_database_sha256,
        "question_set_sha256": QUESTION_SET_SHA256,
        "population": population,
        "evidence": "paper title and abstract",
        "threshold": threshold,
        "papers_classified": len(rows),
        "trend_positive": len(relevant),
        "share_trend_positive": len(relevant) / len(rows) if rows else None,
        "trend_gate": (
            "at least one named trend or other-architecture Noul at or above threshold"
        ),
        "models_returned": dict(Counter(row.get("model_returned") for row in rows)),
        "usage": dict(usage),
        "trend_definitions": {
            trend: {
                "label": TREND_LABELS[trend],
                "description": (
                    TRENDS[trend]
                    if trend in TRENDS
                    else "A substantive model-architecture trend not covered by the named hypotheses."
                ),
            }
            for trend in [*TRENDS, "other_architecture"]
        },
        "primary_trends": [
            {
                "trend": trend,
                "papers": count,
                "share_of_trend_positive": count / len(relevant) if relevant else None,
            }
            for trend, count in primary.most_common()
        ],
        "multi_label_trends": trend_totals,
        "monthly": monthly,
        "limitations": [
            "Jev judged titles and abstracts, not full paper text.",
            "Trend labels describe substantive topics in the title and abstract, not whether a named model was used as a backbone.",
            "Multi-label trend shares overlap and need not sum to 100%.",
            "The default population is scanned papers naming at least one tracked robotics model, so it is not all cs.RO papers.",
            "Other-architecture results require human review because Jev makes typed decisions and does not generate new taxonomy labels.",
        ],
    }
    return result, monthly


def write_outputs(
    rows: Iterable[dict],
    output_dir: Path,
    threshold: float,
    population: str,
    source_database_sha256: str,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary, monthly = summarize(rows, threshold, population, source_database_sha256)
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    fields = [
        "month", "trend", "papers", "population", "trend_positive",
        "share_of_population", "share_of_trend_positive",
    ]
    with (output_dir / "monthly.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(monthly)
    return summary


def run(args: argparse.Namespace) -> dict:
    if not 0 <= args.threshold <= 1:
        raise ValueError("--threshold must be between 0 and 1")
    if args.concurrency < 1:
        raise ValueError("--concurrency must be at least 1")
    papers = load_papers(args.database, args.population, args.since)
    if args.limit is not None:
        papers = papers[: args.limit]
    if args.dry_run:
        if not papers:
            raise ValueError("No papers match the requested population")
        print(json.dumps(build_request(papers[0], args.model), indent=2, ensure_ascii=False))
        return {"dry_run": True, "papers": len(papers)}
    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        raise RuntimeError("Set TYPESAFE_API_KEY before calling Jev")
    raw_path = args.raw
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    completed = read_completed(raw_path, args.model)

    def is_current(paper: dict) -> bool:
        row = completed.get(paper["id"])
        return bool(
            row
            and row.get("abstract_sha256")
            == hashlib.sha256(paper["abstract"].encode()).hexdigest()
        )

    pending = [paper for paper in papers if not is_current(paper)]
    lock = Lock()
    done = sum(is_current(paper) for paper in papers)

    def classify(paper: dict) -> dict:
        return classify_paper(paper, args.model, api_key, args.timeout, args.retries)

    with raw_path.open("a") as handle, ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(classify, paper): paper for paper in pending}
        for future in as_completed(futures):
            paper = futures[future]
            try:
                row = future.result()
            except Exception as exc:
                for other in futures:
                    other.cancel()
                raise RuntimeError(f"Jev classification failed for {paper['id']}") from exc
            with lock:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                completed[row["paper_id"]] = row
                done += 1
                if done == len(papers) or done % 100 == 0:
                    print(f"classified {done}/{len(papers)}", file=sys.stderr)
    selected = [completed[paper["id"]] for paper in papers]
    return write_outputs(
        selected,
        args.output,
        args.threshold,
        args.population,
        database_sha256(args.database),
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/analysis-papers.sqlite"))
    parser.add_argument("--raw", type=Path, default=Path("data/architecture-survey/jev.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("output/architecture-survey"))
    parser.add_argument("--population", choices=("model-papers", "all-scanned"), default="model-papers")
    parser.add_argument("--since", help="Earliest YYYY-MM to include")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    try:
        result = run(args)
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    if args.dry_run:
        return
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
