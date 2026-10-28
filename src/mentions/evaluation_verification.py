"""Verify execution provenance for accepted experimental model evaluations."""
import argparse
import gzip
import hashlib
import json
import os
import time
import urllib.error
import http.client
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from mentions.evaluations import fingerprint
from mentions.llm_survey import _request_json

CRITERIA = {
    'own_runs': "The paper explicitly establishes that its authors train, fine-tune, run, reproduce, or directly measure this exact released model in their own experiments. A named list of models plus an unambiguous shared authors-run protocol qualifies. New, model-specific real-world measurements or implementation details can establish this. A table row or a sentence saying the proposed method beats the model does NOT establish own runs by itself.",
    'published_scores': "This model's scores are taken from a cited paper, an official paper, a benchmark leaderboard, or another published source. Reproducing a table or reporting a score does NOT mean reproducing the experiment. No separate author-run experiment with this model is established.",
    'component_only': "The model is used only as a component/backbone, teacher, or source of generated data, with no direct evaluation of the existing model as a distinct model, comparator, or diagnostic target. Do not confuse a newly modified model's results with evaluation of the released base model.",
    'unspecified': "The paper does not establish who actually ran this particular model, or the evidence is ambiguous/incomplete. If some baselines are reported and others reproduced without identifying this model's provenance, choose unspecified. Listing a model in a comparison table alone is unspecified, not own_runs.",
}
INSTRUCTIONS = (
    "Verify execution provenance, not claimed performance. Be strict about the exact release. "
    "Read the experimental setup, captions, appendix protocols, and result-source notes together. "
    "A generic common benchmark protocol does not prove all rows were rerun. If the authors both "
    "quote this model's literature scores AND clearly run a separate experiment with it, own_runs "
    "takes precedence. Do not assume active evaluation from a numeric score or a citation. "
    "The goal is evidence of authors' own model evaluation, not general use of a model family."
)
POLICY_SHA = hashlib.sha256(json.dumps([INSTRUCTIONS, CRITERIA], sort_keys=True).encode()).hexdigest()
MODEL_NOTES = {'gemini_robotics': 'This is the ORIGINAL Gemini Robotics release (2025). Gemini Robotics On-Device and Gemini Robotics 1.5 are distinct releases. Do not attribute their experiments to the original model. Only own runs of the original release itself qualify; otherwise use unspecified or component_only as appropriate.'}
MODEL_NOTES_SHA = hashlib.sha256(json.dumps(MODEL_NOTES, sort_keys=True).encode()).hexdigest()


def verify(paper, models, model, key):
    questions = {item['model_id']: dict(type='choice', instructions=INSTRUCTIONS + f" What establishes execution provenance for {item['label']}? " + MODEL_NOTES.get(item['model_id'], ''), criteria=CRITERIA) for item in models}
    request = dict(model=model, questions=questions, state=dict(title=paper['title'], abstract=paper['abstract'], evidence=paper['excerpts']))
    for attempt in range(5):
        try:
            response = _request_json(request, key, 120)
            answers = response.get('answers', {})
            if set(answers) != set(questions) or any(a.get('choice') not in CRITERIA for a in answers.values()):
                raise ValueError('Invalid execution verification response')
            return dict(paper_id=paper['paper_id'], fingerprint=fingerprint(paper), models=[m['model_id'] for m in models],
                        policy_sha256=POLICY_SHA, model_notes_sha256=MODEL_NOTES_SHA, model_requested=model, model_returned=response.get('model'),
                        answers=answers, usage=response.get('usage', {}))
        except urllib.error.HTTPError as exc:
            if exc.code not in {408, 409, 429, 500, 502, 503, 504} or attempt == 4:
                raise
        except (OSError, http.client.HTTPException, ValueError):
            if attempt == 4:
                raise
        time.sleep(min(16, 2 ** attempt))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--concurrency', type=int, default=12)
    args = parser.parse_args()
    with gzip.open('data/evaluations/candidates.jsonl.gz', 'rt') as handle:
        papers = [json.loads(line) for line in handle]
    decisions = {r['paper_id']: r for r in map(json.loads, Path('data/evaluations/jev.jsonl').read_text().splitlines())}
    raw = Path('data/evaluations/verification.jsonl')
    completed = {}
    if raw.exists():
        completed = {r['paper_id']: r for r in map(json.loads, raw.read_text().splitlines()) if r['policy_sha256'] == POLICY_SHA}
    pending = []
    total = 0
    for paper in papers:
        models = [m for m in paper['models'] if decisions[paper['paper_id']]['answers'][f"{m['model_id']}_baseline"]['noul'] >= .7]
        if not models:
            continue
        total += 1
        previous = completed.get(paper['paper_id'], {})
        changed_notes = any(m['model_id'] in MODEL_NOTES for m in models) and previous.get('model_notes_sha256') != MODEL_NOTES_SHA
        if previous.get('fingerprint') != fingerprint(paper) or previous.get('models') != [m['model_id'] for m in models] or changed_notes:
            pending.append((paper, models))
    done = total - len(pending)
    print(f'Verifying {len(pending)}/{total} papers with accepted evaluations', flush=True)
    key = os.environ.get('TYPESAFE_API_KEY')
    if pending and not key:
        raise RuntimeError('Set TYPESAFE_API_KEY')
    with raw.open('a') as handle, ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(verify, p, models, 'jev-1.14.0', key) for p, models in pending]
        for future in as_completed(futures):
            row = future.result()
            handle.write(json.dumps(row) + '\n')
            handle.flush()
            done += 1
            if done % 100 == 0 or done == total:
                print(f'verified {done}/{total}', flush=True)


if __name__ == '__main__':
    main()
