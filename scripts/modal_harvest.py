"""Persist incremental OAI metadata separately from PDF pipeline volumes."""
from pathlib import Path

import modal

app = modal.App('robotics-research-metadata')
volume = modal.Volume.from_name('robotics-research-metadata', create_if_missing=True)
image = (modal.Image.debian_slim(python_version='3.12')
         .env({'MENTIONS_DATA': '/metadata'})
         .add_local_python_source('mentions'))


@app.function(image=image, volumes={'/metadata': volume}, timeout=4 * 3600,
              max_containers=1, region='us-east')
def sync(month: str = ''):
    from mentions.harvest import harvest
    volume.reload()
    try:
        harvest(month=month or None, checkpoint=volume.commit)
    finally:
        volume.commit()


@app.local_entrypoint()
def main(month: str = ''):
    sync.remote(month)
    path = Path('data/records.jsonl')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.jsonl.part')
    with temporary.open('wb') as handle:
        for chunk in volume.read_file('records.jsonl'):
            handle.write(chunk)
    temporary.replace(path)
