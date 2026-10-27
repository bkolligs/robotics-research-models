"""Reproduce methodology outputs from a completed SQLite scan, without PDFs."""
import argparse
import csv
import hashlib
import json
import os
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from mentions.export_corpus import paper_rows, write_jsonl
from mentions.parallel_pipeline import write_rows
from mentions.scan import summarize
from mentions.taxonomy import variant_records


def rates(count, scanned, model):
    return {'papers': count, 'share_of_scanned': count / scanned if scanned else None,
            'share_of_model_papers': count / model if model else None}


def write_csv(path, rows, fields):
    with path.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run(database, data, output):
    database, data, output = map(lambda p: Path(p).resolve(), (database, data, output))
    data.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(f'file:{database}?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    if [r[0] for r in db.execute('PRAGMA integrity_check')] != ['ok']:
        raise ValueError('Database failed integrity check')
    records = []
    statuses = {}
    for row in db.execute('SELECT * FROM paper_index ORDER BY published,id'):
        record = json.loads(row['metadata'])
        if record['published'] < '2023-01-01' or 'cs.RO' not in record['categories']:
            raise ValueError(f'Paper outside study scope: {row["id"]}')
        if record['month'] != record['published'][:7]:
            raise ValueError('Month does not match first submission')
        records.append(record)
        statuses[row['id']] = row['status']
    scanned = {r['id']: dict(r) for r in db.execute('SELECT * FROM papers')}
    if set(scanned) != {pid for pid, status in statuses.items() if status == 'complete'}:
        raise ValueError('Scanned papers and complete index records disagree')
    metadata = {r['variant_id']: r for r in variant_records()}
    mentions = defaultdict(list)
    for row in db.execute('SELECT * FROM mentions ORDER BY paper_id,variant_id'):
        if row['paper_id'] not in scanned or row['variant_id'] not in metadata:
            raise ValueError('Orphan paper or unknown model mention')
        current = metadata[row['variant_id']]
        if any(row[k] != current[v] for k,v in [('label','label'), ('family','family_label'), ('country','country'), ('company','company')]):
            raise ValueError('Taxonomy differs from the scanned database; rescan explicitly')
        mentions[row['paper_id']].append(dict(row))
    hits = []
    for record in records:
        pid = record['id']
        hits.append(dict(id=pid, month=record['month'], primary=record['primary'],
                         source='arxiv_bulk_pdf' if pid in scanned else 'failed',
                         variants=[r['variant_id'] for r in mentions[pid]], abstract_variants=[],
                         **({} if pid in scanned else {'error': statuses[pid]})))
    # Reuse the established corpus and chart summary format; never run extraction.
    old = {key: os.environ.get(key) for key in ('MENTIONS_DATA','MENTIONS_OUTPUT')}
    try:
        os.environ.update(MENTIONS_DATA=str(data), MENTIONS_OUTPUT=str(output))
        write_rows(data/'records.jsonl', records)
        write_rows(data/'hits.jsonl', hits)
        write_jsonl(paper_rows())
        summarize()
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    from mentions.build_site import site_papers
    inspected = [{'id': r['id'], 'month': r['month'], 'title': r['title'],
                  'variants': [{'id': m['variant_id']} for m in mentions[r['id']]]} for r in records]
    (output/'papers.json').write_text(json.dumps(site_papers(inspected))+'\n')
    summary = json.loads((output/'summary.json').read_text())
    discovered_month = Counter(r['month'] for r in records)
    scanned_month = Counter(r['month'] for r in scanned.values())
    model_month = Counter(scanned[pid]['month'] for pid, rows in mentions.items() if rows)
    groups = {'variant': defaultdict(set), 'family': defaultdict(set),
              'country': defaultdict(set), 'company': defaultdict(set)}
    monthly = {kind: defaultdict(lambda: defaultdict(set)) for kind in groups}
    for pid, rows in mentions.items():
        if not rows:
            continue
        month = scanned[pid]['month']
        for kind, field in [('variant','variant_id'), ('family','family'), ('country','country'), ('company','company')]:
            for key in {r[field] for r in rows}:
                groups[kind][key].add(pid)
                monthly[kind][month][key].add(pid)
    # Include curated variants with zero observations in the analysis tables.
    for vid, meta in metadata.items():
        groups['variant'][vid]
        for kind, field in [('family','family_label'), ('country','country'), ('company','company')]:
            groups[kind][meta[field]]
    model_count = sum(model_month.values())
    if model_count != summary['papers_mentioning_any_tracked_variant']:
        raise ValueError('Model denominator mismatch')
    # Independent SQL DISTINCT checks guard deduplication at every aggregation level.
    for kind, field in [('variant','variant_id'), ('family','family'), ('country','country'), ('company','company')]:
        expected = dict(db.execute(f'SELECT {field},COUNT(DISTINCT paper_id) FROM mentions GROUP BY {field}'))
        actual = {key: len(ids) for key, ids in groups[kind].items() if ids}
        if actual != expected:
            raise ValueError(f'{kind} aggregation disagrees with SQL')
        expected_month = {(r[0],r[1]): r[2] for r in db.execute(f'SELECT p.month,m.{field},COUNT(DISTINCT m.paper_id) FROM mentions m JOIN papers p ON p.id=m.paper_id GROUP BY p.month,m.{field}')}
        actual_month = {(month,key):len(ids) for month,items in monthly[kind].items() for key,ids in items.items()}
        if actual_month != expected_month:
            raise ValueError(f'{kind} monthly aggregation disagrees with SQL')
    coverage = []
    for month in sorted(discovered_month):
        n = scanned_month[month]
        coverage.append(dict(month=month, discovered=discovered_month[month], scanned=n,
                             unavailable=discovered_month[month]-n, model_papers=model_month[month],
                             coverage=n/discovered_month[month],
                             share_naming_any_model=model_month[month]/n if n else None))
    write_csv(output/'coverage.csv', coverage, list(coverage[0]))
    tables = {}
    for kind, items in groups.items():
        rows = [dict(key=key, **rates(len(ids),len(scanned),model_count))
                for key,ids in sorted(items.items(), key=lambda item: (-len(item[1]),item[0]))]
        tables[kind] = rows
        write_csv(output/f'{kind}_totals.csv', rows, list(rows[0]))
        series = []
        for month in sorted(discovered_month):
            for key in sorted(items):
                series.append(dict(month=month, key=key,
                                   **rates(len(monthly[kind][month][key]),scanned_month[month],model_month[month])))
        write_csv(output/f'{kind}_monthly.csv', series, list(series[0]))
    summary.update(papers_missing_from_snapshot=sum(s=='missing_from_snapshot' for s in statuses.values()),
                   coverage=coverage, analysis_tables=tables,
                   date_basis='first_submission', release_gate_applied=False,
                   full_text_stored_in_database=False)
    for month in summary['months']:
        summary['monthly'][month]['families'] = {k:len(v) for k,v in monthly['family'][month].items()}
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    early = []
    for vid, meta in metadata.items():
        ids = sorted(pid for pid in groups['variant'][vid]
                     if int(scanned[pid]['published'][:4]) < meta['introduced'])
        if ids:
            early.append(dict(variant_id=vid, introduced_year=meta['introduced'],
                              papers=len(ids), paper_ids=ids))
    (output/'date_diagnostics.json').write_text(json.dumps({
        'note': 'Diagnostic only: first submission predates the taxonomy introduction year. Later revisions or ambiguous names can cause this; no release gate was applied.',
        'variants': early}, indent=2)+'\n')
    with database.open('rb') as source:
        database_digest = hashlib.file_digest(source, 'sha256').hexdigest()
    provenance = dict(database_sha256=database_digest,
                      generated_at=datetime.now(timezone.utc).isoformat(),
                      methodology_sha256=hashlib.sha256(Path('docs/METHODOLOGY.md').read_bytes()).hexdigest(),
                      database_integrity='ok', sql_aggregation_checks='passed',
                      discovered=len(records), scanned=len(scanned), model_papers=model_count,
                      unavailable=len(records)-len(scanned), statuses=dict(Counter(statuses.values())),
                      first_scanned=min(r['published'] for r in scanned.values()),
                      last_scanned=max(r['published'] for r in scanned.values()),
                      last_discovered=max(r['published'] for r in records),
                      limitations=['Mentions include bibliography and do not establish use as a backbone.',
                                   'No release-date gate is applied.',
                                   'Results cover only the curated taxonomy and cs.RO corpus.',
                                   'Metadata version is not independent verification of the version inside the bulk PDF.',
                                   'Months with no scanned PDFs have undefined rates, not zero rates.'])
    (output/'analysis_provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    db.close()
    return provenance


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Path('data/analysis-papers.sqlite'))
    parser.add_argument('--data', type=Path, default=Path('data/analysis'))
    parser.add_argument('--output', type=Path, default=Path('output'))
    args=parser.parse_args()
    print(json.dumps(run(args.database,args.data,args.output),indent=2))


if __name__ == '__main__':
    main()
