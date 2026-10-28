"""Track frontier LLM mentions and Jev-judged usage in robotics papers.

This study is deliberately separate from the robotics-model taxonomy. A
deterministic full-text pass finds qualified model names, including references.
Jev then judges whether each named model is actively used or directly evaluated
by the paper, rather than merely cited or discussed as background.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import http.client
import json
import os
import random
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Callable, Iterable


API_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-1.14.0"
SCHEMA_VERSION = 1

# Each released model remains a separate row. Bare "Astra" is excluded because
# it names several unrelated robotics systems; bare "fable" is ordinary prose.
LLM_MODELS = (
    {
        "model_id": "gpt6_astra",
        "label": "GPT-6 Astra",
        "family": "GPT-6",
        "company": "OpenAI",
        "introduced": 2026,
        "aliases": (
            "gpt-6 astra", "gpt-6-astra", "gpt 6 astra", "gpt6 astra", "gpt6-astra",
        ),
    },
    {
        "model_id": "claude_fable_5",
        "label": "Claude Fable 5",
        "family": "Claude Fable",
        "company": "Anthropic",
        "introduced": 2026,
        "aliases": ("claude fable 5", "claude-fable-5", "fable 5", "fable-5"),
    },
    {
        "model_id": "claude_fable_51",
        "label": "Claude Fable 5.1",
        "family": "Claude Fable",
        "company": "Anthropic",
        "introduced": 2026,
        "aliases": (
            "claude fable 5.1", "claude-fable-5.1", "fable 5.1", "fable-5.1",
        ),
    },
)
MODEL_BY_ID = {row["model_id"]: row for row in LLM_MODELS}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    return text.replace("–", "-").replace("—", "-")


def _pattern(alias: str) -> re.Pattern[str]:
    # Dots belong to version strings, so Fable 5 must not match Fable 5.1.
    return re.compile(rf"(?<![a-z0-9]){re.escape(normalize(alias))}(?![a-z0-9.])")


_RULES = {
    row["model_id"]: [(alias, _pattern(alias)) for alias in row["aliases"]]
    for row in LLM_MODELS
}


def find_llm_mentions(text: str) -> dict[str, list[tuple[int, int, str]]]:
    """Return all qualified alias spans, grouped by released model."""
    folded = normalize(text)
    found: dict[str, list[tuple[int, int, str]]] = {}
    for model_id, rules in _RULES.items():
        spans = []
        seen = set()
        for alias, pattern in rules:
            for match in pattern.finditer(folded):
                key = (match.start(), match.end())
                if key not in seen:
                    spans.append((match.start(), match.end(), alias))
                    seen.add(key)
        if spans:
            found[model_id] = sorted(spans)
    return found


def _sample_spans(spans: list[tuple[int, int, str]], limit: int = 8) -> list[tuple[int, int, str]]:
    if len(spans) <= limit:
        return spans
    # Preserve evidence from the beginning, body, and bibliography instead of
    # taking only the first repeated cluster.
    indices = sorted({round(i * (len(spans) - 1) / (limit - 1)) for i in range(limit)})
    return [spans[index] for index in indices]


def candidate_rows(record: dict, text: str, context_chars: int = 360) -> list[dict]:
    mentions = find_llm_mentions(text)
    rows = []
    for model_id, spans in mentions.items():
        contexts = []
        for start, end, _alias in _sample_spans(spans):
            excerpt = text[max(0, start - context_chars):min(len(text), end + context_chars)]
            contexts.append(" ".join(excerpt.split()))
        rows.append({
            "schema": SCHEMA_VERSION,
            "paper_id": record["id"],
            "month": record["published"][:7],
            "title": record.get("title", ""),
            "abstract": record.get("summary", record.get("abstract", "")),
            "model_id": model_id,
            "model_label": MODEL_BY_ID[model_id]["label"],
            "matched_aliases": sorted({alias for _start, _end, alias in spans}),
            "occurrences": len(spans),
            "contexts": contexts,
            "text_sha256": hashlib.sha256(text.encode(errors="replace")).hexdigest(),
        })
    return rows


def scan_candidates(
    data_root: Path,
    index_path: Path,
    output_path: Path,
    *,
    bucket: int = 0,
    buckets: int = 1,
) -> dict:
    """Scan cached full text referenced by paper_index.jsonl."""
    if not 0 <= bucket < buckets:
        raise ValueError("bucket must be within the configured bucket count")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".part")
    papers_scanned = 0
    candidates = 0
    counts = Counter()
    with index_path.open() as source, temporary.open("w") as destination:
        for line in source:
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("status") != "complete":
                continue
            assignment = int(hashlib.sha256(record["id"].encode()).hexdigest()[:8], 16) % buckets
            if assignment != bucket:
                continue
            text_path = data_root / record["full_text_path"]
            if not text_path.is_file():
                raise FileNotFoundError(text_path)
            text = text_path.read_text(errors="replace")
            papers_scanned += 1
            for row in candidate_rows(record, text):
                destination.write(json.dumps(row, ensure_ascii=False) + "\n")
                candidates += 1
                counts[row["model_id"]] += 1
    temporary.replace(output_path)
    return {
        "papers_scanned": papers_scanned,
        "paper_model_candidates": candidates,
        "by_model": dict(counts),
        "bucket": bucket,
        "buckets": buckets,
        "output": str(output_path),
    }


QUESTIONS = {
    "used_in_study": {
        "type": "noul",
        "instructions": (
            "The authors actively use this named LLM in their method, robot system, data or "
            "content generation, experiments, or direct model evaluation. This is false when "
            "the name appears only in background, related work, a bibliography, a reported "
            "result from another paper, future work, or an authoring-assistance disclosure."
        ),
    },
    "usage_role": {
        "type": "choice",
        "instructions": "What is the named LLM's strongest role in this paper?",
        "criteria": {
            "robot_system_component": (
                "The model is an active component of the proposed or evaluated robot system, "
                "such as a planner, policy, reasoner, perception module, or controller."
            ),
            "direct_evaluation_target": (
                "The paper directly runs or experimentally evaluates the named model, including "
                "as an embodied policy or agent, even if it is not part of a proposed system."
            ),
            "data_or_content_generation": (
                "The authors run the model to generate training data, labels, code, plans, prompts, "
                "or other study inputs, but it is not deployed as the robot system."
            ),
            "authoring_disclosure_only": (
                "The model appears only in a disclosure about writing, editing, or preparing the paper."
            ),
            "mentioned_not_used": (
                "The model is only cited, discussed, compared through reported literature, or named "
                "as background or future work; the authors do not run or integrate it."
            ),
        },
    },
}
QUESTION_SET_SHA256 = hashlib.sha256(
    json.dumps(QUESTIONS, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()


def build_request(candidate: dict, model: str) -> dict:
    return {
        "state": {
            "document_type": "robotics paper with full-text excerpts around a named LLM",
            "paper_title": candidate["title"],
            "paper_abstract": candidate["abstract"],
            "named_model": candidate["model_label"],
            "matched_aliases": candidate["matched_aliases"],
            "full_text_contexts": candidate["contexts"],
            "guidance": (
                "Judge only this named model. The excerpts are sampled from every part of the paper "
                "and can include references. Do not infer use from a citation or broad capability claim."
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
            "User-Agent": "robotics-research-models/llm-usage-survey",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def candidate_key(row: dict) -> str:
    return f"{row['paper_id']}\0{row['model_id']}"


def evidence_sha256(row: dict) -> str:
    evidence = {
        "title": row["title"], "abstract": row["abstract"], "contexts": row["contexts"],
        "model_id": row["model_id"], "matched_aliases": row["matched_aliases"],
    }
    return hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()


def classify_candidate(
    candidate: dict,
    model: str,
    api_key: str,
    timeout: float = 60,
    retries: int = 5,
    request_json: Callable[[dict, str, float], dict] = _request_json,
) -> dict:
    payload = build_request(candidate, model)
    for attempt in range(retries):
        try:
            response = request_json(payload, api_key, timeout)
            answers = response.get("answers")
            if not isinstance(answers, dict) or set(answers) != set(QUESTIONS):
                raise ValueError("Jev response does not contain the expected answers")
            return {
                "schema": SCHEMA_VERSION,
                "paper_id": candidate["paper_id"],
                "month": candidate["month"],
                "title": candidate["title"],
                "model_id": candidate["model_id"],
                "model_label": candidate["model_label"],
                "evidence_sha256": evidence_sha256(candidate),
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
            urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException,
            json.JSONDecodeError,
        ) as exc:
            if attempt + 1 == retries:
                raise RuntimeError(f"TypeSafe API request failed: {exc}") from exc
        except ValueError as exc:
            if attempt + 1 == retries:
                raise RuntimeError(f"TypeSafe API returned an invalid response: {exc}") from exc
        time.sleep(min(16, 2**attempt) + random.random())
    raise AssertionError("retry loop exhausted")


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open() as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on {path}:{number}") from exc
    return rows


def read_completed(path: Path, model: str) -> dict[str, dict]:
    if not path.exists():
        return {}
    return {
        candidate_key(row): row
        for row in load_jsonl(path)
        if row.get("question_set_sha256") == QUESTION_SET_SHA256
        and row.get("model_requested") == model
    }


def database_months(path: Path) -> dict[str, int]:
    db = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    rows = dict(db.execute("SELECT month, COUNT(*) FROM papers GROUP BY month ORDER BY month"))
    db.close()
    return rows


def database_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _used(row: dict, threshold: float) -> bool:
    return float(row["answers"]["used_in_study"]["noul"]) >= threshold


def summarize(
    candidates: Iterable[dict],
    decisions: Iterable[dict],
    month_populations: dict[str, int],
    threshold: float,
    source_database_sha256: str,
) -> tuple[dict, list[dict]]:
    candidates = list(candidates)
    decisions = list(decisions)
    candidate_map = {candidate_key(row): row for row in candidates}
    decision_map = {candidate_key(row): row for row in decisions}
    if set(candidate_map) != set(decision_map):
        raise ValueError("Jev decisions do not exactly cover the full-text LLM candidates")

    mention_papers = {row["paper_id"] for row in candidates}
    used_rows = [row for row in decisions if _used(row, threshold)]
    usage_papers = {row["paper_id"] for row in used_rows}
    role_counts = Counter(row["answers"]["usage_role"]["choice"] for row in decisions)
    token_usage = Counter()
    for row in decisions:
        for key, value in row.get("usage", {}).items():
            if isinstance(value, int):
                token_usage[key] += value

    totals = []
    monthly = []
    for model in LLM_MODELS:
        model_id = model["model_id"]
        mentioned = [row for row in candidates if row["model_id"] == model_id]
        used = [row for row in used_rows if row["model_id"] == model_id]
        totals.append({
            "model_id": model_id,
            "label": model["label"],
            "family": model["family"],
            "company": model["company"],
            "mention_papers": len(mentioned),
            "usage_papers": len(used),
            "usage_share_of_mentions": len(used) / len(mentioned) if mentioned else None,
        })
        mention_months = Counter(row["month"] for row in mentioned)
        usage_months = Counter(row["month"] for row in used)
        for month, population in month_populations.items():
            mention_count = mention_months[month]
            usage_count = usage_months[month]
            monthly.append({
                "month": month,
                "model_id": model_id,
                "label": model["label"],
                "papers_scanned": population,
                "mention_papers": mention_count,
                "usage_papers": usage_count,
                "mention_rate_scanned": mention_count / population if population else None,
                "usage_rate_scanned": usage_count / population if population else None,
                "usage_share_of_mentions": usage_count / mention_count if mention_count else None,
            })

    result = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_database_sha256": source_database_sha256,
        "question_set_sha256": QUESTION_SET_SHA256,
        "evidence": "full-text qualified-name matches plus title, abstract, and sampled hit contexts",
        "threshold": threshold,
        "papers_scanned": sum(month_populations.values()),
        "paper_model_candidates": len(candidates),
        "papers_mentioning_tracked_llm": len(mention_papers),
        "papers_using_tracked_llm": len(usage_papers),
        "models": [{key: value for key, value in model.items() if key != "aliases"} for model in LLM_MODELS],
        "totals": totals,
        "role_counts": dict(role_counts),
        "models_returned": dict(Counter(row.get("model_returned") for row in decisions)),
        "usage": dict(token_usage),
        "monthly": monthly,
        "definitions": {
            "mention": "Qualified model name appears anywhere in extracted full text, bibliography included.",
            "usage": (
                "Jev probability is at or above the threshold that the authors actively use the model "
                "in their system, data generation, experiments, or direct evaluation."
            ),
        },
        "limitations": [
            "Usage is a probabilistic Jev judgment from the title, abstract, and sampled full-text contexts.",
            "A mention can be only a citation; this is why mention and usage are reported separately.",
            "Only explicitly tracked released models are counted; bare Astra and bare fable are excluded.",
            "The chart does not claim that a used LLM is the paper's model backbone.",
        ],
    }
    return result, monthly


def write_outputs(
    candidates: Iterable[dict], decisions: Iterable[dict], database: Path,
    output_dir: Path, threshold: float,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary, monthly = summarize(
        candidates, decisions, database_months(database), threshold, database_sha256(database)
    )
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    fields = [
        "month", "model_id", "label", "papers_scanned", "mention_papers", "usage_papers",
        "mention_rate_scanned", "usage_rate_scanned", "usage_share_of_mentions",
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
    candidates = load_jsonl(args.candidates)
    if args.limit is not None:
        candidates = candidates[:args.limit]
    if args.dry_run:
        if not candidates:
            raise ValueError("No LLM candidates found")
        print(json.dumps(build_request(candidates[0], args.model), indent=2, ensure_ascii=False))
        return {"dry_run": True, "paper_model_candidates": len(candidates)}
    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        raise RuntimeError("Set TYPESAFE_API_KEY before calling Jev")
    completed = read_completed(args.raw, args.model)

    def is_current(candidate: dict) -> bool:
        row = completed.get(candidate_key(candidate))
        return bool(row and row.get("evidence_sha256") == evidence_sha256(candidate))

    pending = [candidate for candidate in candidates if not is_current(candidate)]
    args.raw.parent.mkdir(parents=True, exist_ok=True)
    lock = Lock()
    done = sum(is_current(candidate) for candidate in candidates)

    def classify(candidate: dict) -> dict:
        return classify_candidate(
            candidate, args.model, api_key, timeout=args.timeout, retries=args.retries
        )

    with args.raw.open("a") as handle, ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(classify, candidate): candidate for candidate in pending}
        for future in as_completed(futures):
            candidate = futures[future]
            try:
                row = future.result()
            except Exception as exc:
                for other in futures:
                    other.cancel()
                raise RuntimeError(
                    f"Jev classification failed for {candidate['paper_id']} / {candidate['model_id']}"
                ) from exc
            with lock:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                completed[candidate_key(row)] = row
                done += 1
                if done == len(candidates) or done % 25 == 0:
                    print(f"classified {done}/{len(candidates)} paper-model candidates", file=sys.stderr)
    selected = [completed[candidate_key(candidate)] for candidate in candidates]
    return write_outputs(candidates, selected, args.database, args.output, args.threshold)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/analysis-papers.sqlite"))
    parser.add_argument("--candidates", type=Path, default=Path("data/llm-survey/candidates.jsonl"))
    parser.add_argument("--raw", type=Path, default=Path("data/llm-survey/jev.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("output/llm-survey"))
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
    if not args.dry_run:
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
