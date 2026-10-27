"""Manifest barrier, disjoint archive workers, and validated consolidation."""
import hashlib
import json
from pathlib import Path

from mentions.export_corpus import load_jsonl, paper_rows, write_jsonl, write_sqlite
from mentions.pdf_store import ManifestChunk
from mentions.selective_store import _get_index, fetch_chunk, save_json
from mentions.scan import scan_record, scan_fingerprint, summarize


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.part')
    tmp.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
    tmp.replace(path)


def construct_manifest(data, chunks, *, partial=False):
    locations = {}
    for chunk in chunks:
        _, index, _ = _get_index(chunk, data, require_index=True)
        for entry in index['entries']:
            locations.setdefault(entry['id'], dict(s3_bucket='arxiv', s3_key=chunk.filename,
                etag=index['etag'], byte_offset=entry['offset'], byte_length=entry['size']))
    rows = []
    for record in load_jsonl(data / 'records.jsonl'):
        source = locations.get(record['id'])
        if partial and source is None:
            continue
        rows.append(dict(record, location=source, pdf_path=f"pdf/{record['id']}.pdf",
            full_text_path=f"text/{record['id']}.txt",
            status='pending' if source else 'missing_from_snapshot'))
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate metadata IDs')
    identity = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    run = data / 'runs' / identity
    write_rows(run / 'manifest.jsonl', rows)
    assignments = {}
    for row in rows:
        if row['location']:
            assignments.setdefault(row['location']['s3_key'], []).append(row)
    for chunk in chunks:
        write_rows(run / 'assignments' / (Path(chunk.filename).name + '.jsonl'), assignments.get(chunk.filename, []))
    save_json(run / 'plan.json', {'chunks': [c.__dict__ for c in chunks], 'partial': partial})
    if not partial:
        write_rows(data / 'paper_manifest.jsonl', rows)
    return {'run_id': identity, 'papers': len(rows), 'located': sum(r['location'] is not None for r in rows)}


def process_archive(data, run_id, chunk, *, overwrite=False):
    run = data / 'runs' / run_id
    records = load_jsonl(run / 'assignments' / (Path(chunk.filename).name + '.jsonl'))
    name = Path(chunk.filename).name
    # Exactly one worker owns each archive and each paper; no shared output writes.
    result = fetch_chunk(chunk, {r['id'] for r in records}, data,
                         overwrite=overwrite, require_index=True)
    hits, indexed = [], []
    fingerprint = scan_fingerprint()
    for row in records:
        hit = scan_record(row)
        pdf = data / row['pdf_path']
        hit.update(fingerprint=fingerprint, pdf_stamp=[pdf.stat().st_size, pdf.stat().st_mtime_ns])
        hits.append(hit)
        indexed.append(dict(row, status='complete' if hit['source'] == 'arxiv_bulk_pdf' else 'failed',
                            error=hit.get('error', ''), full_text_available=hit['source'] == 'arxiv_bulk_pdf'))
    write_rows(run / 'shards' / (name + '.hits.jsonl'), hits)
    write_rows(run / 'shards' / (name + '.index.jsonl'), indexed)
    write_rows(run / 'shards' / (name + '.corpus.jsonl'), paper_rows(records, hits))
    save_json(run / 'shards' / (name + '.done.json'), {'run_id': run_id, 'ids': [r['id'] for r in records]})
    return dict(result, parsed=len(hits))


def merge(data, run_id, *, read_workers=8):
    """Read immutable shards concurrently, build locally, then publish with backups."""
    import os
    import shutil
    import sqlite3
    import tempfile
    import threading
    import time
    import uuid
    from concurrent.futures import ThreadPoolExecutor, as_completed

    run = data / 'runs' / run_id
    started = time.monotonic()
    progress = {'stage': 'loading_manifest', 'archives_done': 0, 'papers_read': 0}
    stopped = threading.Event()

    def report():
        from mentions.progress import format_progress
        event = dict(progress, event='consolidation_progress', run_id=run_id,
                     elapsed_seconds=round(time.monotonic() - started, 1))
        print(format_progress(event), flush=True)
        print(json.dumps(event), flush=True)

    def heartbeat():
        while not stopped.wait(10):
            report()

    report()
    reporter = threading.Thread(target=heartbeat, daemon=True)
    reporter.start()
    try:
        plan = json.loads((run / 'plan.json').read_text())
        manifest = load_jsonl(run / 'manifest.jsonl')
        owners = {}
        for row in manifest:
            if row['location']:
                owners.setdefault(row['location']['s3_key'], set()).add(row['id'])
        progress.update(stage='reading_and_validating_shards', archives_total=len(plan['chunks']))
        report()

        def read_chunk(chunk):
            name = Path(chunk['filename']).name
            marker = json.loads((run / 'shards' / (name + '.done.json')).read_text())
            expected = owners.get(chunk['filename'], set())
            if (marker['run_id'] != run_id or set(marker['ids']) != expected
                    or len(marker['ids']) != len(expected)):
                raise ValueError(f'Incomplete worker results: {name}')
            outputs = {}
            for suffix in ('hits', 'index', 'corpus'):
                path = run / 'shards' / (name + f'.{suffix}.jsonl')
                if not path.is_file():
                    raise FileNotFoundError(path)
                rows = load_jsonl(path)
                ids = [r['id'] for r in rows]
                required = expected if suffix != 'corpus' else {
                    h['id'] for h in outputs['hits'] if h['source'] == 'arxiv_bulk_pdf'}
                if len(ids) != len(set(ids)) or set(ids) != required:
                    raise ValueError(f'Invalid {suffix} shard coverage: {name}')
                outputs[suffix] = rows
            return expected, outputs

        hits, index, corpus, seen = [], [], [], set()
        with ThreadPoolExecutor(max_workers=read_workers) as pool:
            # Bound submitted tasks while overlapping small-file storage latency.
            for start in range(0, len(plan['chunks']), 64):
                pending = [pool.submit(read_chunk, c) for c in plan['chunks'][start:start + 64]]
                for future in as_completed(pending):
                    expected, outputs = future.result()
                    if seen & expected:
                        raise ValueError('Overlapping worker results')
                    seen.update(expected)
                    hits.extend(outputs['hits'])
                    index.extend(outputs['index'])
                    corpus.extend(outputs['corpus'])
                    progress.update(archives_done=progress['archives_done'] + 1, papers_read=len(hits))
                report()
        if seen != {r['id'] for r in manifest if r['location']}:
            raise ValueError('Missing manifest coverage')
        index.extend(r for r in manifest if not r['location'])
        for rows in (hits, index, corpus):
            rows.sort(key=lambda r: r['id'])
        progress.update(stage='building_database', scanned=len(corpus))
        report()
        # SQLite writes and checks run on local disk, not the remote Volume.
        with tempfile.TemporaryDirectory(prefix='mentions-merge-') as tmp:
            staging = Path(tmp)
            old_data, old_output = os.environ.get('MENTIONS_DATA'), os.environ.get('MENTIONS_OUTPUT')
            try:
                os.environ['MENTIONS_DATA'] = str(staging)
                os.environ['MENTIONS_OUTPUT'] = str(staging / 'output')
                write_rows(staging / 'records.jsonl', manifest)
                write_rows(staging / 'paper_index.jsonl', index)
                write_rows(staging / 'hits.jsonl', hits)
                write_jsonl(corpus)
                write_sqlite(corpus, index)
                summarize()
                with sqlite3.connect(f'file:{staging / "papers.sqlite"}?mode=ro', uri=True) as db:
                    if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                        raise ValueError('SQLite integrity check failed')
                    if db.execute('SELECT COUNT(*) FROM paper_index').fetchone()[0] != len(manifest):
                        raise ValueError('Database coverage mismatch')
            finally:
                for key, value in [('MENTIONS_DATA', old_data), ('MENTIONS_OUTPUT', old_output)]:
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
            generation = run / 'consolidations' / uuid.uuid4().hex
            progress.update(stage='saving_validated_generation', generation=str(generation))
            report()
            generation.mkdir(parents=True)
            files = [Path('paper_index.jsonl'), Path('hits.jsonl'), Path('papers.sqlite'),
                     Path('output/summary.json')] + [p.relative_to(staging) for p in sorted((staging / 'corpus').glob('*.jsonl'))]
            for relative in files:
                dest = generation / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(staging / relative, dest)
            result = {'papers': len(index), 'scanned': len(corpus), 'partial': plan['partial'],
                      'generation': str(generation), 'integrity_check': 'ok'}
            save_json(generation / 'validated.json', result)
            if not plan['partial']:
                progress.update(stage='backing_up_previous_outputs')
                report()
                for relative in files:
                    previous = data / relative
                    if previous.exists():
                        backup = generation / 'previous' / relative
                        backup.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(previous, backup)
                progress.update(stage='publishing_outputs')
                report()
                for relative in files:
                    dest = data / relative
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    temporary = dest.with_name(dest.name + '.publish-part')
                    shutil.copyfile(staging / relative, temporary)
                    temporary.replace(dest)
                save_json(data / 'consolidation_complete.json', result)
            progress.update(stage='complete')
            report()
            return result
    except BaseException as exc:
        progress.update(stage='failed', error=str(exc))
        report()
        raise
    finally:
        stopped.set()
        reporter.join()
