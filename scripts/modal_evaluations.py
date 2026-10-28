"""Extract evaluation evidence from the existing full-text cache."""
import os
from contextlib import closing
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import modal

app = modal.App('robotics-evaluation-evidence')
volume = modal.Volume.from_name(os.environ.get('MENTIONS_MODAL_VOLUME', 'papers'), create_if_missing=False)
image = modal.Image.debian_slim(python_version='3.12').add_local_python_source('mentions')


@app.function(image=image, volumes={'/papers': volume}, cpu=1, memory=2048, timeout=3600, max_containers=10)
def extract(bucket: int, buckets: int):
    from mentions.evaluations import extract_bucket, extract_evidence
    import gzip
    import hashlib
    import json
    import sqlite3
    volume.reload()
    destination = Path(f'/papers/evaluations/shards/{bucket:02d}.jsonl.gz')
    if destination.exists():
        with closing(sqlite3.connect('file:/papers/papers.sqlite?mode=ro', uri=True)) as db:
            expected = {pid: count for pid, count in db.execute('SELECT paper_id,COUNT(*) FROM mentions GROUP BY paper_id')
                        if int(hashlib.sha256(pid.encode()).hexdigest()[:8], 16) % buckets == bucket}
        with gzip.open(destination, 'rt') as handle:
            rows = [json.loads(line) for line in handle]
        if len(rows) == len(expected) and {r['paper_id']: len(r['models']) for r in rows} == expected:
            repaired = False
            for row in rows:
                if not row['excerpts']:
                    text = Path(f"/papers/text/{row['paper_id']}.txt").read_text(errors='replace')
                    row['excerpts'] = extract_evidence(text, row['models'])
                    repaired = True
            if repaired:
                temporary = destination.with_suffix('.part')
                with gzip.open(temporary, 'wt') as handle:
                    for row in rows:
                        handle.write(json.dumps(row, ensure_ascii=False) + '\n')
                temporary.replace(destination)
                volume.commit()
            return dict(bucket=bucket, papers=len(rows), resumed=True)
    result = extract_bucket(Path('/papers'), destination, bucket, buckets)
    volume.commit()
    return result


@app.function(image=image, volumes={'/papers': volume}, cpu=1, memory=4096, timeout=600)
def merge(buckets: int):
    import gzip
    import json
    import sqlite3
    volume.reload()
    rows = []
    for bucket in range(buckets):
        with gzip.open(f'/papers/evaluations/shards/{bucket:02d}.jsonl.gz', 'rt') as handle:
            rows.extend(json.loads(line) for line in handle)
    with closing(sqlite3.connect('file:/papers/papers.sqlite?mode=ro', uri=True)) as db:
        expected = dict(db.execute('SELECT paper_id,COUNT(*) FROM mentions GROUP BY paper_id'))
    if {r['paper_id']: len(r['models']) for r in rows} != expected or len(rows) != len(expected):
        raise ValueError('Evaluation evidence coverage mismatch')
    path = '/papers/evaluations/candidates.jsonl.gz'
    with gzip.open(path + '.part', 'wt') as handle:
        for row in sorted(rows, key=lambda r: r['paper_id']):
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')
    Path(path + '.part').replace(path)
    volume.commit()
    return dict(papers=len(rows), pairs=sum(len(r['models']) for r in rows), path=path)


@app.function(image=image, volumes={'/papers': volume}, cpu=1, memory=2048, timeout=600)
def audit_text(paper_ids: list[str]):
    import gzip
    import json
    import re
    volume.reload()
    if not all(re.fullmatch(r'\d{4}\.\d{4,5}', pid) for pid in paper_ids):
        raise ValueError('Invalid paper IDs')
    path = Path('/papers/evaluations/audit-text.jsonl.gz')
    with gzip.open(path, 'wt') as handle:
        for pid in paper_ids:
            text = Path(f'/papers/text/{pid}.txt').read_text(errors='replace')
            handle.write(json.dumps(dict(paper_id=pid, text=text)) + '\n')
    volume.commit()
    return dict(path=str(path), papers=len(paper_ids))


@app.local_entrypoint()
def main(buckets: int = 10, audit_ids: str = '', repair_empty: bool = False):
    if repair_empty:
        print(repair_empty_evidence.remote(), flush=True)
        return
    if audit_ids:
        print(audit_text.remote(audit_ids.split(',')), flush=True)
        return
    if not 1 <= buckets <= 10:
        raise ValueError('buckets must be 1..10')
    with ThreadPoolExecutor(max_workers=buckets) as pool:
        futures = [pool.submit(extract.remote, i, buckets) for i in range(buckets)]
        for future in as_completed(futures):
            print(future.result(), flush=True)
    print(merge.remote(buckets), flush=True)


@app.function(image=image, volumes={'/papers': volume}, cpu=1, memory=4096, timeout=600)
def repair_empty_evidence():
    import gzip
    import json
    from mentions.evaluations import extract_evidence
    volume.reload()
    path = Path('/papers/evaluations/candidates.jsonl.gz')
    repaired = []
    with gzip.open(path, 'rt') as source, gzip.open(str(path) + '.part', 'wt') as target:
        for line in source:
            row = json.loads(line)
            if not row['excerpts']:
                text = Path(f"/papers/text/{row['paper_id']}.txt").read_text(errors='replace')
                row['excerpts'] = extract_evidence(text, row['models'])
                repaired.append(row['paper_id'])
            target.write(json.dumps(row, ensure_ascii=False) + '\n')
    Path(str(path) + '.part').replace(path)
    volume.commit()
    return dict(repaired=repaired)
