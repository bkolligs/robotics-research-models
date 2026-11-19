"""Combine disjoint historical/monthly survey snapshots and verify plot coverage."""
import copy
import csv
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

KINDS = ('architecture-survey', 'llm-survey', 'evaluations')


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n')


def csv_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def add_maps(parts, field):
    result = Counter()
    for part in parts:
        result.update(part.get(field, {}))
    return dict(result)


def combine(parts, kind, database_hash):
    result = copy.deepcopy(parts[0])
    for key in ('schema', 'threshold', 'question_set_sha256' if kind != 'evaluations' else 'policy_sha256'):
        if any(p.get(key) != result.get(key) for p in parts):
            raise ValueError(f'Incompatible {kind} snapshot {key}')
    if kind == 'architecture-survey' and any(p['population'] != 'model-papers' for p in parts):
        raise ValueError('Architecture snapshots must classify model papers')
    seen = set()
    monthly = []
    for p in parts:
        months = set(p['monthly_population']) if kind == 'evaluations' else {r['month'] for r in p['monthly']}
        if seen & months:
            raise ValueError(f'Overlapping {kind} snapshot months: {seen & months}')
        seen |= months
        monthly.extend(p['monthly'])
    result.update(generated_at=datetime.now(timezone.utc).isoformat(), source_database_sha256=database_hash,
                  through=max(seen), monthly=sorted(monthly, key=lambda r:(r['month'], r.get('trend',r.get('model_id','')))),
                  snapshot_sources=[{'through':max(p['monthly_population'] if kind=='evaluations' else (r['month'] for r in p['monthly'])),
                                     'generated_at':p['generated_at'], 'source_database_sha256':p.get('source_database_sha256')} for p in parts])
    for field in ('usage', 'models_returned'):
        if field in result:
            result[field] = add_maps(parts, field)
    if kind == 'architecture-survey':
        for field in ('papers_classified','trend_positive'):
            result[field] = sum(p[field] for p in parts)
        population, positive = result['papers_classified'], result['trend_positive']
        result['share_trend_positive'] = positive/population if population else None
        primary = Counter()
        for p in parts:
            primary.update({r['trend']:r['papers'] for r in p['primary_trends']})
        result['primary_trends'] = [dict(trend=k,papers=v,share_of_trend_positive=v/positive if positive else None) for k,v in primary.most_common()]
        totals = {}
        for p in parts:
            for row in p['multi_label_trends']:
                total = totals.setdefault(row['trend'],dict(trend=row['trend'],label=row['label'],papers=0,examples=[]))
                total['papers'] += row['papers']
                total['examples'].extend(row['examples'])
        for total in totals.values():
            total.update(share_of_population=total['papers']/population if population else None,
                         share_of_trend_positive=total['papers']/positive if positive else None)
            total['examples'] = sorted(total['examples'],key=lambda r:(-r['probability'],r['id']))[:5]
        result['multi_label_trends'] = sorted(totals.values(),key=lambda r:(-r['papers'],r['trend']))
    elif kind == 'llm-survey':
        for field in ('papers_scanned','paper_model_candidates','papers_mentioning_tracked_llm','papers_using_tracked_llm'):
            result[field] = sum(p[field] for p in parts)
        result['role_counts'] = add_maps(parts,'role_counts')
        totals = {}
        for p in parts:
            if p['models'] != parts[0]['models']:
                raise ValueError('LLM taxonomy changed across snapshots')
            for row in p['totals']:
                total=totals.setdefault(row['model_id'],dict(row,mention_papers=0,usage_papers=0))
                for field in ('mention_papers','usage_papers'):
                    total[field] += row[field]
        for total in totals.values():
            total['usage_share_of_mentions']=total['usage_papers']/total['mention_papers'] if total['mention_papers'] else None
        result['totals']=list(totals.values())
    else:
        if not all(p['complete'] for p in parts):
            raise ValueError('Incomplete evaluation snapshot')
        if any(p['execution_verification']['policy_sha256'] != parts[0]['execution_verification']['policy_sha256']
               or p['model_requested'] != parts[0]['model_requested'] for p in parts):
            raise ValueError('Evaluation verification policy or model changed')
        for field in ('papers_classified','paper_model_pairs','papers_scanned'):
            result[field]=sum(p[field] for p in parts)
        result['monthly_population']={m:n for p in parts for m,n in p['monthly_population'].items()}
        totals={}
        for p in parts:
            for row in p['totals']:
                total=totals.setdefault(row['model_id'],dict(model_id=row['model_id'],label=row['label'],mentions=0,evaluations=0,outcomes=Counter()))
                total['mentions']+=row['mentions']; total['evaluations']+=row['evaluations']
                total['outcomes'].update(row['outcomes'])
        result['totals']=sorted(totals.values(),key=lambda r:(-r['evaluations'],r['model_id']))
        verification=copy.deepcopy(parts[0]['execution_verification'])
        for field in ('papers','release_recheck_pending'):
            verification[field]=sum(p['execution_verification'][field] for p in parts)
        verification['usage']=add_maps([p['execution_verification'] for p in parts],'usage')
        verification['source_counts']=add_maps([p['execution_verification'] for p in parts],'source_counts')
        result['execution_verification']=verification
    return result


def validate_coverage(output, database):
    with sqlite3.connect(f'file:{Path(database).resolve()}?mode=ro',uri=True) as db:
        population=dict(db.execute('SELECT month,COUNT(*) FROM papers GROUP BY month'))
        model_population=dict(db.execute('SELECT p.month,COUNT(DISTINCT p.id) FROM papers p JOIN mentions m ON p.id=m.paper_id GROUP BY p.month'))
        pairs=db.execute('SELECT COUNT(*) FROM mentions').fetchone()[0]
    summaries={kind:read(Path(output)/kind/'summary.json') for kind in KINDS}
    a=summaries['architecture-survey']; l=summaries['llm-survey']; e=summaries['evaluations']
    arch_population={r['month']:r['population'] for r in a['monthly']}
    if arch_population != model_population or a['papers_classified'] != sum(model_population.values()):
        raise ValueError('Architecture coverage is stale or incomplete')
    if {r['month']:r['papers_scanned'] for r in l['monthly']} != population or l['papers_scanned'] != sum(population.values()):
        raise ValueError('LLM coverage is stale or incomplete')
    if e['monthly_population'] != population or e['papers_classified'] != sum(model_population.values()) or e['paper_model_pairs'] != pairs or not e['complete']:
        raise ValueError('Evaluation coverage is stale or incomplete')
    return max(population)


def publish(state, database, destination):
    state,database,destination=map(Path,(state,database,destination))
    snapshots=[state/'baseline', *sorted((state/'months').glob('*/output'))]
    with database.open('rb') as handle:
        digest=hashlib.file_digest(handle,'sha256').hexdigest()
    for kind in KINDS:
        parts=[read(p/kind/'summary.json') for p in snapshots]
        summary=combine(parts,kind,digest)
        write(destination/kind/'summary.json',summary)
        if kind != 'evaluations':
            csv_rows(destination/kind/'monthly.csv',summary['monthly'])
        else:
            papers=[row for p in snapshots for row in read(p/kind/'papers.json')]
            if len({(r['paper_id'],r['model_id']) for r in papers}) != len(papers):
                raise ValueError('Duplicate evaluation decisions')
            write(destination/kind/'papers.json',papers)
            csv_rows(destination/kind/'evaluations.csv',papers)
            audit=state/'baseline'/kind/'audit.json'
            if audit.exists():
                write(destination/kind/'audit.json',read(audit))
    validate_coverage(destination,database)
