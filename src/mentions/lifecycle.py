"""Export confirmed evaluation usage by calendar month and months after release."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from mentions.taxonomy import variant_records

EVALUATED = {'beaten', 'mixed', 'tied', 'baseline_wins', 'unclear', 'no_proposed_method'}


def month_index(month: str) -> int:
    year, number = map(int, month.split('-'))
    return year * 12 + number - 1


def month_range(start: str, end: str) -> list[str]:
    return [f'{n // 12:04d}-{n % 12 + 1:02d}' for n in range(month_index(start), month_index(end) + 1)]


def summarize(rows: list[dict], releases: dict, published: dict[str, str], populations: dict[str, int]) -> dict:
    registry = {r['model_id']: r for r in releases['models']}
    if len(registry) != len(releases['models']):
        raise ValueError('Duplicate release model IDs')
    taxonomy = {r['variant_id']: r for r in variant_records()}
    for mid, release in registry.items():
        if mid not in taxonomy or not release.get('source', '').startswith('https://'):
            raise ValueError(f'Invalid or unsourced release: {mid}')
        date.fromisoformat(release['released'])
    if not populations:
        raise ValueError('No scanned coverage')
    months = month_range(min(populations), max(populations))
    evaluations = [r for r in rows if r['outcome'] in EVALUATED]
    keys = [(r['paper_id'], r['model_id']) for r in evaluations]
    if len(keys) != len(set(keys)):
        raise ValueError('Duplicate evaluated paper/model pair')
    any_evaluation = defaultdict(set)
    counts = defaultdict(Counter)
    excluded = Counter()
    unknown = Counter()
    intro = Counter()
    for row in evaluations:
        pid, mid = row['paper_id'], row['model_id']
        if pid not in published:
            raise ValueError(f'Paper missing from source database: {pid}')
        submission = date.fromisoformat(published[pid][:10])
        month = submission.isoformat()[:7]
        if row['month'] != month or month not in populations or populations[month] <= 0:
            raise ValueError(f'Evaluation date/coverage mismatch: {pid}')
        # Fixed denominator: each paper counts once, no matter how many models
        # it evaluates or whether their release date has been curated yet.
        any_evaluation[month].add(pid)
        if mid not in registry:
            unknown[mid] += 1
            continue
        release = registry[mid]
        if pid in release.get('intro_paper_ids', []):
            intro[mid] += 1
            continue
        if submission < date.fromisoformat(release['released']):
            excluded[mid] += 1
            continue
        counts[mid][month] += 1
    model_rows, monthly = [], []
    for mid, release in registry.items():
        release_month = release['released'][:7]
        observed = [m for m in months if m >= release_month]
        if not observed:
            continue
        series = []
        for i, month in enumerate(observed):
            scanned = populations.get(month, 0)
            denominator = len(any_evaluation[month])
            count = counts[mid][month] if scanned else None
            window = observed[max(0, i - 2):i + 1]
            usable = all(populations.get(m, 0) > 0 for m in window)
            window_count = sum(counts[mid][m] for m in window) if usable else None
            window_population = sum(len(any_evaluation[m]) for m in window) if usable else None
            series.append(dict(model_id=mid, month=month, months_since_release=month_index(month)-month_index(release_month),
                               papers=count, evaluation_papers=denominator, scanned_papers=scanned,
                               share=count/denominator if count is not None and denominator else None,
                               window_months=len(window), window_papers=window_count,
                               window_evaluation_papers=window_population,
                               window_monthly_papers=window_count/len(window) if window_count is not None else None,
                               window_share=window_count/window_population if window_population else None))
        populated = [r for r in series if r['papers']]
        # A peak based on a few papers can be misleading. Keep a separately
        # labeled descriptive peak only where the window has at least 20 papers.
        supported = [r for r in series if r['window_months'] == 3 and (r['window_evaluation_papers'] or 0) >= 20 and r['window_share'] is not None]
        peak = max(supported, key=lambda r: r['window_share']) if supported else None
        latest = series[-1]
        model_rows.append(dict(**release, label=taxonomy[mid]['label'], access_class=taxonomy[mid]['access_class'],
                               evaluations=sum(counts[mid].values()), excluded_pre_release=excluded[mid], excluded_introduction=intro[mid],
                               observation_start=observed[0], observation_end=observed[-1],
                               missing_early_history=release_month < months[0],
                               observed_age_months=latest['months_since_release'],
                               last_use_month=populated[-1]['month'] if populated else None,
                               last_use_age_months=populated[-1]['months_since_release'] if populated else None,
                               latest_window=latest, supported_peak=peak))
        monthly.extend(series)
    model_rows.sort(key=lambda r: -r['evaluations'])
    return dict(schema=1, generated_at=datetime.now(timezone.utc).isoformat(),
                release_date_basis=releases['date_basis'], release_dates_verified_on=releases['verified_on'],
                corpus_start=months[0], through=months[-1], source_evaluation_pairs=len(evaluations),
                source_evaluation_papers=len({r['paper_id'] for r in evaluations}),
                eligible_post_release_pairs=sum(r['evaluations'] for r in model_rows),
                excluded_pre_release_pairs=sum(excluded.values()), excluded_introduction_pairs=sum(intro.values()),
                unverified_releases=[dict(model_id=mid, label=taxonomy[mid]['label'], evaluation_pairs=count) for mid,count in unknown.most_common()],
                monthly_population=[dict(month=m, evaluation_papers=len(any_evaluation[m]), scanned_papers=populations.get(m,0)) for m in months],
                models=model_rows, monthly=monthly,
                definitions=dict(share='Papers evaluating this model divided by distinct papers evaluating any tracked model in the same calendar month.',
                                 window_share='Sum of model evaluation papers over the current and up to two preceding observed months divided by the sum of monthly evaluation-paper denominators.',
                                 age='Calendar month offset from the documented release month; release month is zero.',
                                 peak='Highest trailing-three-month share among windows containing at least 20 evaluation papers.'),
                limitations=['Only confirmed evaluations from the existing Jev/provenance/source-review dataset qualify.',
                             'First-submission dates are used, although full text may come from a later revision. Post-release gating does not date the actual experiments.',
                             'Release references can precede public checkpoint availability. Release months and initial smoothing windows are partial.',
                             'The corpus starts in 2023: early histories of older models are unobserved, not zero.',
                             'Curves stop at corpus coverage; recent models have shorter observed lifetimes. Last observed use is not a retirement date.',
                             'Missing or unresolved evaluations and model-release dates can depress measured usage; closed model access also differs.',
                             'Declining share or no recent observed use does not establish causal replacement, model obsolescence, or inferior performance.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evaluations', type=Path, default=Path('output/evaluations/papers.json'))
    parser.add_argument('--releases', type=Path, default=Path('docs/model_releases.json'))
    parser.add_argument('--database', type=Path, default=Path('data/analysis-papers.sqlite'))
    parser.add_argument('--output', type=Path, default=Path('output/baseline-lifecycle'))
    args = parser.parse_args()
    db = sqlite3.connect(f'file:{args.database.resolve()}?mode=ro', uri=True)
    try:
        published = dict(db.execute('SELECT id,published FROM papers'))
        populations = dict(db.execute('SELECT month,COUNT(*) FROM papers GROUP BY month'))
    finally:
        db.close()
    result = summarize(json.loads(args.evaluations.read_text()), json.loads(args.releases.read_text()), published, populations)
    result['source_evaluations_sha256'] = hashlib.sha256(args.evaluations.read_bytes()).hexdigest()
    result['release_registry_sha256'] = hashlib.sha256(args.releases.read_bytes()).hexdigest()
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'summary.json').write_text(json.dumps(result, indent=2, ensure_ascii=False)+'\n')
    with (args.output/'monthly.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(result['monthly'][0]))
        writer.writeheader()
        writer.writerows(result['monthly'])
    print(json.dumps({k:result[k] for k in ['through','eligible_post_release_pairs','excluded_pre_release_pairs','excluded_introduction_pairs']}, indent=2))


if __name__ == '__main__':
    main()
