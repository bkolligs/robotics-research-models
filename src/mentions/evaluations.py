"""Evaluate whether named robotics models are experimental baselines and beaten."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path

from mentions.llm_survey import _request_json
from mentions.taxonomy import variant_records

MODEL_RECORDS = {row['variant_id']: row for row in variant_records()}
OUTCOMES = {
    'beaten': "The authors' proposed method clearly outperforms this baseline on the principal reported evaluation. Require model-specific evidence; generic state-of-the-art claims are insufficient.",
    'mixed': "The proposed method beats this baseline on some reported tasks, settings, or principal metrics and loses on others, or an explicit performance/efficiency tradeoff prevents an overall winner.",
    'tied': "The principal comparison explicitly reports comparable or tied performance, with no clear overall winner. Similar-looking numbers alone do not establish a tie.",
    'baseline_wins': "This baseline clearly outperforms the authors' proposed method on the principal reported evaluation.",
    'unclear': "The model is an experimental baseline, but excerpts omit decisive results, the tables cannot be read reliably, or the evidence does not establish the direction of the comparison.",
    'no_proposed_method': "The model is directly evaluated in a benchmark, survey, or diagnostic with no new proposed method to beat it.",
    'not_baseline': "The model is cited, discussed, used only as a backbone or component, or its performance is copied from another work without running it as an experimental comparator in this paper.",
}
POLICY = (
    "Judge the specific released model separately. An experimental baseline requires evidence that "
    "the authors run, reproduce, fine-tune, or directly evaluate this existing model as a comparator "
    "in their own experiments. Bibliography/related work, authoring assistance, a model used only "
    "inside the proposed method, and copied literature scores do not qualify. An adapted baseline "
    "counts if it remains a clearly identified comparator. The proposed variant's result must not "
    "be attributed to the unmodified base release. Do not infer defeat from mere baseline inclusion. "
    "Preserve mixed outcomes across tasks/metrics. These are reported empirical comparisons, not "
    "independently verified superiority or statistical significance. Missing evidence means unclear."
)
POLICY_SHA = hashlib.sha256(json.dumps([POLICY, OUTCOMES], sort_keys=True).encode()).hexdigest()


def extract_evidence(text: str, models: list[dict], budget: int = 60000) -> list[dict]:
    """Preserve line/table layout; combine all model hit windows with results headings."""
    lines = text.splitlines()
    hits = set()
    for i, line in enumerate(lines):
        folded = line.lower().replace('–', '-').replace('—', '-')
        for model in models:
            aliases = MODEL_RECORDS[model['model_id']]['aliases']
            if any(alias.lower() in folded for alias in aliases):
                hits.add(i)
                break
    # Include pi typesetting and evaluation headings even where the PDF spells
    # a short name differently from the mention matcher's normalized aliases.
    for i, line in enumerate(lines):
        if re.search(r'(?i)^\s*(?:\d[.\d]*\s+)?(?:experiments?|evaluation|results|baselines?|quantitative|ablation)\b', line):
            hits.add(i)
        if re.search(r'(?i)\bpi\s*0|π', line):
            hits.add(i)
    # Prefer windows with experimental language, retaining references as evidence
    # of mention-only rather than discarding them and silently inventing use.
    windows = []
    for i in sorted(hits):
        start, end = max(0, i - 12), min(len(lines), i + 22)
        excerpt = '\n'.join(lines[start:end])
        priority = len(re.findall(r'(?i)baseline|success|ours|table|outperform|evaluat|compar|experiment', excerpt))
        windows.append((priority, start, end))
    selected = set()
    used = 0
    for _score, start, end in sorted(windows, reverse=True):
        additions = [i for i in range(start, end) if i not in selected]
        size = sum(len(lines[i]) + 1 for i in additions)
        if used + size <= budget:
            selected.update(additions)
            used += size
    chunks = []
    for i in sorted(selected):
        if not chunks or i != chunks[-1][-1] + 1:
            chunks.append([i])
        else:
            chunks[-1].append(i)
    if not chunks:
        # Some PDFs wrap model names and headings across lines. Never silently
        # reduce those papers to a title/abstract-only evaluation judgment.
        return [dict(excerpt_id='1', start_line=1, text=text[:budget])]
    return [dict(excerpt_id=str(n + 1), start_line=chunk[0] + 1,
                 text='\n'.join(lines[i] for i in chunk)) for n, chunk in enumerate(chunks)]


def extract_bucket(root: Path, destination: Path, bucket: int, buckets: int) -> dict:
    db = sqlite3.connect(f'file:{root / "papers.sqlite"}?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    papers = db.execute('SELECT p.* ,i.full_text_path FROM papers p JOIN paper_index i ON p.id=i.id WHERE EXISTS (SELECT 1 FROM mentions m WHERE m.paper_id=p.id) ORDER BY p.id').fetchall()
    destination.parent.mkdir(parents=True, exist_ok=True)
    count = pairs = 0
    temporary = destination.with_suffix('.part')
    with gzip.open(temporary, 'wt') as handle:
        for paper in papers:
            if int(hashlib.sha256(paper['id'].encode()).hexdigest()[:8], 16) % buckets != bucket:
                continue
            models = [dict(model_id=row['variant_id'], label=row['label']) for row in db.execute('SELECT variant_id,label FROM mentions WHERE paper_id=? ORDER BY variant_id', (paper['id'],))]
            text = (root / paper['full_text_path']).read_text(errors='replace')
            excerpts = extract_evidence(text, models)
            row = dict(paper_id=paper['id'], month=paper['month'], title=paper['title'], abstract=paper['abstract'], models=models, excerpts=excerpts,
                       text_sha256=hashlib.sha256(text.encode()).hexdigest())
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')
            count += 1
            pairs += len(models)
            if count % 100 == 0:
                print(f'bucket {bucket}: {count} papers', flush=True)
    temporary.replace(destination)
    db.close()
    return dict(bucket=bucket, papers=count, paper_model_pairs=pairs)


def build_request(paper: dict, model: str) -> dict:
    questions = {}
    for item in paper['models']:
        model_id, label = item['model_id'], item['label']
        questions[f'{model_id}_baseline'] = dict(type='noul', instructions=f'{POLICY} Is {label} actually run as an experimental baseline or direct evaluation target in this paper?')
        questions[f'{model_id}_outcome'] = dict(type='choice', instructions=f'{POLICY} What do the results establish for {label}, relative to the paper\'s proposed method?', criteria=OUTCOMES)
    return dict(model=model, questions=questions, state=dict(
        title=paper['title'], abstract=paper['abstract'], tracked_models=paper['models'],
        evidence=paper['excerpts'], guidance='Extracted PDF excerpts preserve table line layout. Excerpts may be incomplete. Use only model-specific evidence.'))


def fingerprint(paper: dict) -> str:
    return hashlib.sha256(json.dumps([POLICY_SHA, paper], sort_keys=True).encode()).hexdigest()


def classify(paper: dict, model: str, key: str) -> dict:
    # Reuse the transport/retry implementation while keeping this dynamic question
    # schema isolated from the architecture survey module's global questions.
    import time
    import urllib.error
    import http.client
    request = build_request(paper, model)
    for attempt in range(5):
        try:
            response = _request_json(request, key, 120)
            answers = response.get('answers', {})
            if set(answers) != set(request['questions']):
                raise ValueError('incomplete Jev answers')
            for name, question in request['questions'].items():
                answer = answers[name]
                if question['type'] == 'noul' and not 0 <= float(answer['noul']) <= 1:
                    raise ValueError('invalid baseline probability')
                if question['type'] == 'choice' and answer.get('choice') not in OUTCOMES:
                    raise ValueError('invalid outcome')
            return dict(paper_id=paper['paper_id'], month=paper['month'], title=paper['title'],
                        fingerprint=fingerprint(paper), policy_sha256=POLICY_SHA, model_requested=model,
                        model_returned=response.get('model'), answers=answers, usage=response.get('usage', {}))
        except urllib.error.HTTPError as exc:
            if exc.code not in {408, 409, 429, 500, 502, 503, 504}:
                raise RuntimeError(f'TypeSafe HTTP {exc.code}') from exc
            if attempt == 4:
                raise
        except (OSError, http.client.HTTPException, ValueError, KeyError):
            if attempt == 4:
                raise
        time.sleep(min(16, 2 ** attempt))
    raise AssertionError('unreachable')


def adjudicate(row: dict, model_id: str, threshold: float = .7) -> str:
    baseline = float(row['answers'][f'{model_id}_baseline']['noul'])
    answer = row['answers'][f'{model_id}_outcome']
    if baseline < threshold:
        return 'not_baseline' if baseline <= 1 - threshold else 'uncertain_baseline'
    outcome = answer['choice']
    if outcome == 'not_baseline':
        return 'unclear'
    probability = answer.get('probabilities', {}).get(outcome, answer.get('confidence', 0))
    return outcome if probability >= threshold else 'unclear'


def verified_outcome(row: dict, model_id: str, verification: dict, threshold: float = .7) -> str:
    outcome = adjudicate(row, model_id, threshold)
    if outcome in {'not_baseline', 'uncertain_baseline'}:
        return outcome
    if model_id == 'gemini_robotics':
        from mentions.evaluation_verification import MODEL_NOTES_SHA
        if verification.get('model_notes_sha256') != MODEL_NOTES_SHA:
            return 'uncertain_baseline'
    answer = verification['answers'][model_id]
    source = answer['choice']
    probability = answer.get('probabilities', {}).get(source, answer.get('confidence', 0))
    if probability < threshold or source == 'unspecified':
        return 'uncertain_baseline'
    if source in {'published_scores', 'component_only'}:
        return 'not_baseline'
    return outcome


def write_outputs(papers: list[dict], decisions: dict, output: Path, database: Path, threshold: float,
                  verifications: dict | None = None) -> dict:
    from mentions.evaluation_verification import POLICY_SHA as VERIFICATION_POLICY_SHA
    verifications = verifications or {}
    for paper in papers:
        row = decisions[paper['paper_id']]
        accepted = [m['model_id'] for m in paper['models'] if row['answers'][f"{m['model_id']}_baseline"]['noul'] >= threshold]
        if accepted:
            verification = verifications.get(paper['paper_id'], {})
            if (verification.get('fingerprint') != fingerprint(paper)
                    or verification.get('policy_sha256') != VERIFICATION_POLICY_SHA
                    or not set(accepted) <= set(verification.get('answers', {}))):
                raise ValueError(f"Execution verification is incomplete for {paper['paper_id']}")
    totals = {}
    monthly = {}
    inspection = []
    audit_path = output / 'audit.json'
    audit = json.loads(audit_path.read_text()) if audit_path.exists() else None
    if audit and audit.get('classification_policy_sha256') != POLICY_SHA:
        raise ValueError('Source audit belongs to a different classification policy')
    reviews = {(r['paper_id'], r['model_id']): r for r in audit['reviews']} if audit else {}
    for paper in papers:
        row = decisions[paper['paper_id']]
        for item in paper['models']:
            mid = item['model_id']
            verification = verifications.get(paper['paper_id'], {})
            outcome = verified_outcome(row, mid, verification, threshold)
            review = reviews.get((paper['paper_id'], mid))
            if review:
                if review['source_text_sha256'] != paper['text_sha256']:
                    raise ValueError(f"Source audit text mismatch for {paper['paper_id']}")
                outcome = review['reviewed_outcome']
            total = totals.setdefault(mid, dict(model_id=mid, label=item['label'], mentions=0, evaluations=0, outcomes=Counter()))
            total['mentions'] += 1
            total['outcomes'][outcome] += 1
            is_baseline = outcome not in {'not_baseline', 'uncertain_baseline'}
            total['evaluations'] += is_baseline
            month = monthly.setdefault((paper['month'], mid), dict(month=paper['month'], model_id=mid, evaluations=0, outcomes=Counter()))
            month['evaluations'] += is_baseline
            month['outcomes'][outcome] += 1
            if outcome != 'not_baseline':
                inspection.append(dict(paper_id=paper['paper_id'], month=paper['month'], title=paper['title'], model_id=mid,
                                       outcome=outcome, baseline_probability=row['answers'][f'{mid}_baseline']['noul'],
                                       execution_source='source_review' if review else verification.get('answers', {}).get(mid, {}).get('choice', 'not_verified'),
                                       source_reviewed=bool(review)))
    with closing(sqlite3.connect(f'file:{database.resolve()}?mode=ro', uri=True)) as db:
        population = dict(db.execute('SELECT month,COUNT(*) FROM papers GROUP BY month'))
        expected = dict(db.execute('SELECT paper_id,COUNT(*) FROM mentions GROUP BY paper_id'))
    full_coverage = {p['paper_id']: len(p['models']) for p in papers} == expected
    summary = dict(schema=1, generated_at=datetime.now(timezone.utc).isoformat(), policy_sha256=POLICY_SHA,
                   model_requested=next(iter(decisions.values()))['model_requested'] if decisions else None,
                   threshold=threshold, evidence='PDF full-text excerpts with preserved table layout; title and abstract',
                   papers_classified=len(papers), paper_model_pairs=sum(len(p['models']) for p in papers),
                   complete=full_coverage, papers_scanned=sum(population.values()), monthly_population=population,
                   execution_verification=dict(policy_sha256=VERIFICATION_POLICY_SHA, papers=len(verifications),
                                               release_recheck_pending=sum('gemini_robotics' in v['answers'] and not v.get('model_notes_sha256') for v in verifications.values()),
                                               source_counts=dict(Counter(a['choice'] for v in verifications.values() for a in v['answers'].values())),
                                               usage=dict(sum((Counter(v.get('usage', {})) for v in verifications.values()), Counter()))),
                   totals=sorted(totals.values(), key=lambda r: -r['evaluations']), monthly=list(monthly.values()),
                   outcome_definitions=OUTCOMES, usage=dict(sum((Counter(row.get('usage', {})) for row in decisions.values()), Counter())),
                   source_audit={k: audit[k] for k in ['reviewer','cases','papers','source_judgments','limitation']} if audit else None,
                   limitations=['Jev judgments from excerpts; some tables and supplementary results may be incomplete.',
                                'Results reflect authors\' reported comparisons, not independent replication or statistical significance.',
                                'Only tracked robotics models are included. A backbone is not automatically a baseline.',
                                'Mixed results retain tradeoffs. Uncertain baseline roles are excluded from evaluation counts.',
                                'Months use first submission; later revisions can discuss later model releases.'])
    output.mkdir(parents=True, exist_ok=True)
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    (output / 'papers.json').write_text(json.dumps(inspection, ensure_ascii=False) + '\n')
    with (output / 'evaluations.csv').open('w', newline='') as handle:
        fields = ['paper_id', 'month', 'title', 'model_id', 'outcome', 'baseline_probability', 'execution_source', 'source_reviewed']
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(inspection)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidates', type=Path, default=Path('data/evaluations/candidates.jsonl.gz'))
    parser.add_argument('--raw', type=Path, default=Path('data/evaluations/jev.jsonl'))
    parser.add_argument('--output', type=Path, default=Path('output/evaluations'))
    parser.add_argument('--database', type=Path, default=Path('data/analysis-papers.sqlite'))
    parser.add_argument('--model', default='jev-1.14.0')
    parser.add_argument('--concurrency', type=int, default=8)
    parser.add_argument('--threshold', type=float, default=.7)
    parser.add_argument('--verification', type=Path, default=Path('data/evaluations/verification.jsonl'))
    parser.add_argument('--limit', type=int)
    parser.add_argument('--classify-only', action='store_true', help='Checkpoint classifications before the separate execution verification pass.')
    args = parser.parse_args()
    if not .5 < args.threshold <= 1 or args.concurrency < 1:
        parser.error('threshold must be above .5 and at most 1; concurrency must be positive')
    with gzip.open(args.candidates, 'rt') as handle:
        papers = [json.loads(line) for line in handle if line.strip()]
    if args.limit:
        papers = papers[:args.limit]
    if len({p['paper_id'] for p in papers}) != len(papers):
        raise ValueError('duplicate candidate paper IDs')
    completed = {}
    if args.raw.exists():
        for line in args.raw.read_text().splitlines():
            row = json.loads(line)
            if row.get('policy_sha256') == POLICY_SHA and row.get('model_requested') == args.model:
                completed[row['paper_id']] = row
    pending = [p for p in papers if completed.get(p['paper_id'], {}).get('fingerprint') != fingerprint(p)]
    key = os.environ.get('TYPESAFE_API_KEY')
    if pending and not key:
        raise RuntimeError('Set TYPESAFE_API_KEY')
    args.raw.parent.mkdir(parents=True, exist_ok=True)
    with args.raw.open('a') as handle, ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(classify, p, args.model, key): p for p in pending}
        done = len(papers) - len(pending)
        for future in as_completed(futures):
            row = future.result()
            handle.write(json.dumps(row) + '\n')
            handle.flush()
            completed[row['paper_id']] = row
            done += 1
            if done % 50 == 0 or done == len(papers):
                print(f'classified {done}/{len(papers)} evaluation papers', file=sys.stderr, flush=True)
    selected = {p['paper_id']: completed[p['paper_id']] for p in papers}
    if args.classify_only:
        print(json.dumps(dict(papers_classified=len(selected), next_step='python -m mentions.evaluation_verification')))
        return
    verifications = {}
    if args.verification.exists():
        from mentions.evaluation_verification import POLICY_SHA as VERIFICATION_POLICY_SHA
        for line in args.verification.read_text().splitlines():
            row = json.loads(line)
            if row.get('policy_sha256') == VERIFICATION_POLICY_SHA and row.get('model_requested') == args.model:
                verifications[row['paper_id']] = row
    relevant_verifications = {pid: v for pid, v in verifications.items() if pid in selected}
    summary = write_outputs(papers, selected, args.output, args.database, args.threshold, relevant_verifications)
    print(json.dumps({k: summary[k] for k in ['papers_classified', 'paper_model_pairs', 'complete', 'usage']}, indent=2))


if __name__ == '__main__':
    main()
