"""Read committed corpus progress without downloading PDFs or changing the job.

uv run --no-sync modal run --profile your-modal-profile scripts/modal_status.py
"""
import os

import modal

app = modal.App(os.environ.get("MENTIONS_MODAL_APP", "paper-status"))
volume = modal.Volume.from_name(os.environ.get("MENTIONS_MODAL_VOLUME", "papers"))


@app.function(volumes={'/papers': volume}, timeout=300, region='us-east')
def status():
    import json
    from pathlib import Path
    from datetime import datetime, timezone

    root = Path('/papers')
    volume.reload()
    wanted = {json.loads(line)['id'] for line in (root / 'records.jsonl').read_text().splitlines() if line.strip()}
    indexed = set()
    indexes = list((root / 'indexes').glob('*.json'))
    for path in indexes:
        index = json.loads(path.read_text())
        indexed.update(e['id'] for e in index['entries'] if e['id'] in wanted)
    pdfs = [p for p in (root / 'pdf').glob('*.pdf') if p.stem in wanted and p.stat().st_size > 0]
    texts = [p for p in (root / 'text').glob('*.txt') if p.stem in wanted and p.stat().st_size > 0]
    manifest = root / 'paper_manifest.jsonl'
    from collections import Counter
    missing = [json.loads(line) for line in manifest.read_text().splitlines()
               if line.strip() and json.loads(line).get('location') is None] if manifest.exists() else []
    return dict(as_of=datetime.now(timezone.utc).isoformat(), papers=len(wanted),
                indexed_papers=len(indexed), committed_archive_indexes=len(indexes),
                downloaded_papers=len(pdfs), downloaded_bytes=sum(p.stat().st_size for p in pdfs),
                text_files=len(texts), full_manifest_exists=manifest.exists(),
                missing_count=len(missing),
                missing_by_month=dict(sorted(Counter(r['month'] for r in missing).items())),
                missing_examples=[{'id': r['id'], 'title': r['title'], 'published': r['published']} for r in missing[:12]])


@app.local_entrypoint()
def main():
    import json
    print(json.dumps(status.remote(), indent=2))
