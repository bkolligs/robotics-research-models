"""Inspect committed database state without walking the PDF/text caches."""
import os

import modal
app = modal.App(os.environ.get("MENTIONS_MODAL_APP", "database-status"))
volume = modal.Volume.from_name(os.environ.get("MENTIONS_MODAL_VOLUME", "papers"))

@app.function(volumes={'/papers': volume}, timeout=300, region='us-east')
def inspect():
    import json, sqlite3, shutil
    from pathlib import Path
    from datetime import datetime, timezone
    volume.reload()
    root = Path('/papers')
    result = {'as_of': datetime.now(timezone.utc).isoformat(), 'files': {}}
    for name in ['papers.sqlite', 'papers.sqlite.part', 'paper_index.jsonl', 'hits.jsonl', 'output/summary.json', 'paper_manifest.jsonl']:
        p = root / name
        if p.exists():
            s = p.stat()
            result['files'][name] = {'bytes': s.st_size, 'modified': datetime.fromtimestamp(s.st_mtime, timezone.utc).isoformat()}
        else:
            result['files'][name] = None
    p = root / 'papers.sqlite'
    if p.exists():
        shutil.copyfile(p, '/tmp/inspect.sqlite')
        with sqlite3.connect('file:/tmp/inspect.sqlite?mode=ro', uri=True) as db:
            tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            result['tables'] = {t: db.execute('SELECT COUNT(*) FROM "' + t.replace('"','""') + '"').fetchone()[0] for t in tables}
            result['quick_check'] = [r[0] for r in db.execute('PRAGMA quick_check')]
            if 'paper_index' in tables:
                result['statuses'] = dict(db.execute('SELECT status,COUNT(*) FROM paper_index GROUP BY status'))
    if (root/'output/summary.json').exists():
        summary = json.loads((root/'output/summary.json').read_text())
        result['summary_counts'] = {k:v for k,v in summary.items() if isinstance(v,(int,str))}
    return result

@app.local_entrypoint()
def main():
    import json
    print(json.dumps(inspect.remote(), indent=2))
