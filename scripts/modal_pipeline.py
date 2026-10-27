"""Persistent cs.RO bulk storage and parsing in the selected Modal workspace.

uv run --group bulk --group modal modal run --profile your-modal-profile --detach \
    scripts/modal_pipeline.py --records data/records.jsonl

Use --max-chunks 10 --batch-size 1 for a bounded ten-worker validation.
"""
from pathlib import Path

import os

import modal

ROOT = Path(__file__).resolve().parents[1]
app = modal.App(os.environ.get("MENTIONS_MODAL_APP", "paper-pipeline"))
volume = modal.Volume.from_name(os.environ.get("MENTIONS_MODAL_VOLUME", "papers"), create_if_missing=True)
image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("poppler-utils")
    .uv_sync(uv_project_dir=str(ROOT), groups=["bulk"], extra_options="--no-dev")
    .env({"MENTIONS_DATA": "/papers", "MENTIONS_OUTPUT": "/papers/output"})
    .add_local_python_source("mentions")
)


@app.function(image=image, volumes={"/papers": volume}, cpu=1, memory=2048,
              timeout=3600, max_containers=10, region="us-east")
def worker(stage: str, chunks: list[dict], run_id: str = "", overwrite: bool = False):
    from mentions.pdf_store import ManifestChunk
    from mentions.selective_store import index_chunk
    from mentions.parallel_pipeline import process_archive
    volume.reload()
    results = []
    try:
        for raw in chunks:
            chunk = ManifestChunk(**raw)
            result = (index_chunk(chunk, Path('/papers')) if stage == 'index' else
                      process_archive(Path('/papers'), run_id, chunk, overwrite=overwrite))
            results.append(result)
            print({"stage": stage, **result}, flush=True)
        return results
    finally:
        volume.commit()


@app.function(image=image, volumes={"/papers": volume}, cpu=2, memory=4096,
              timeout=4 * 3600, max_containers=1, region="us-east")
def control(stage: str, chunks: list[dict] | None = None, run_id: str = "", partial: bool = False):
    from mentions.parallel_pipeline import construct_manifest, merge
    from mentions.pdf_store import ManifestChunk
    print({"stage": stage, "state": "reloading_volume"}, flush=True)
    volume.reload()
    print({"stage": stage, "state": "started"}, flush=True)
    if stage == 'manifest':
        result = construct_manifest(Path('/papers'), [ManifestChunk(**c) for c in chunks], partial=partial)
    else:
        result = merge(Path('/papers'), run_id)
    print({"stage": stage, "state": "committing_volume"}, flush=True)
    volume.commit()
    print({"stage": stage, "state": "committed"}, flush=True)
    return result


@app.local_entrypoint()
def main(records: str = "data/records.jsonl", overwrite: bool = False,
         max_chunks: int = 0, batch_size: int = 5, workers: int = 10, consolidate_run: str = ""):
    if consolidate_run:
        import re
        if not re.fullmatch(r"[0-9a-f]{64}", consolidate_run):
            raise ValueError("consolidate_run must be a manifest SHA-256")
        print(control.remote("merge", run_id=consolidate_run), flush=True)
        return
    import boto3
    import json
    from concurrent.futures import ThreadPoolExecutor
    from dataclasses import asdict
    from mentions.pdf_store import download_manifest, yymm_of

    if max_chunks < 0 or not 1 <= batch_size <= 20 or not 1 <= workers <= 10:
        raise ValueError("Require max_chunks >= 0, batch_size 1..20, workers 1..10")
    session = boto3.Session()
    session.client('sts').get_caller_identity()
    path = Path(records)
    months = {yymm_of(json.loads(line)['id']) for line in path.read_text().splitlines() if line.strip()}
    chunks = [c for c in download_manifest(path.parent / 'pdf_manifest.xml') if c.yymm in months]
    if max_chunks:
        chunks = chunks[:max_chunks]
    with volume.batch_upload(force=True) as batch:
        batch.put_file(path, '/records.jsonl')
    raw = [asdict(c) for c in chunks]

    def parallel(stage, run_id=''):
        for start in range(0, len(raw), batch_size * workers):
            credentials = session.get_credentials().get_frozen_credentials()
            values = {'AWS_ACCESS_KEY_ID': credentials.access_key,
                      'AWS_SECRET_ACCESS_KEY': credentials.secret_key,
                      'AWS_DEFAULT_REGION': 'us-east-1'}
            if credentials.token:
                values['AWS_SESSION_TOKEN'] = credentials.token
            function = worker.with_options(secrets=[modal.Secret.from_dict(values)])
            wave = raw[start:start + batch_size * workers]
            batches = [wave[i:i + batch_size] for i in range(0, len(wave), batch_size)]
            print(f'{stage}: archives {start + 1}-{start + len(wave)}/{len(raw)}, workers={len(batches)}', flush=True)
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(function.remote, stage=stage, chunks=b, run_id=run_id,
                                       overwrite=overwrite) for b in batches]
                # Any failed future prevents the manifest/process/merge barrier advancing.
                for future in futures:
                    future.result()

    parallel('index')
    manifest = control.remote('manifest', chunks=raw, partial=bool(max_chunks))
    print(manifest, flush=True)
    parallel('process', manifest['run_id'])
    print(control.remote('merge', run_id=manifest['run_id']), flush=True)
