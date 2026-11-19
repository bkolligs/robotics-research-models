"""Refresh every plot from a month scan, retaining historical survey snapshots."""
import os
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]
app = modal.App('robotics-research-surveys')
state_volume = modal.Volume.from_name('robotics-research-surveys', create_if_missing=True)
paper_volume = modal.Volume.from_name(os.environ.get('MENTIONS_MODAL_VOLUME', 'papers'))
image = (modal.Image.debian_slim(python_version='3.12')
         .add_local_python_source('mentions'))


@app.function(image=image, volumes={'/papers':paper_volume, '/state':state_volume},
              cpu=2, memory=4096, timeout=4*3600, max_containers=1, region='us-east')
def refresh(month: str):
    import json
    import shutil
    import sqlite3
    import subprocess
    import sys
    from mentions.survey_catalog import publish
    from mentions.llm_survey import scan_candidates
    from mentions.evaluations import extract_bucket

    state_volume.reload(); paper_volume.reload()
    state=Path('/state')
    work=state/'months'/month
    out=work/'output'
    work.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect('file:/papers/papers.sqlite?mode=ro',uri=True) as db:
        months={r[0] for r in db.execute('SELECT DISTINCT month FROM papers')}
    if months != {month}:
        raise ValueError('Survey input must be exactly the requested scanned month')
    if not (state/'baseline').exists():
        shutil.copytree(state/'bootstrap',state/'baseline')
        state_volume.commit()
    baseline_months={r['month'] for r in json.loads((state/'baseline/architecture-survey/summary.json').read_text())['monthly']}
    if month in baseline_months:
        raise ValueError('Requested month overlaps immutable historical survey baseline')

    def run(module,*args):
        print(f'Running {module}',flush=True)
        with (work/(module.rsplit('.',1)[-1]+'.log')).open('w') as log:
            subprocess.run([sys.executable,'-m',module,*map(str,args)],stdout=log,check=True)
        state_volume.commit()

    try:
        llm_candidates=work/'llm-candidates.jsonl'
        evaluation_candidates=work/'evaluation-candidates.jsonl.gz'
        # Refresh evidence after a month rescan; classifier fingerprints reuse
        # unchanged decisions but cannot hide changed text or model mentions.
        scan_candidates(Path('/papers'),Path('/papers/paper_index.jsonl'),llm_candidates)
        extract_bucket(Path('/papers'),evaluation_candidates,0,1)
        state_volume.commit()
        run('mentions.survey','--database','/papers/papers.sqlite','--raw',work/'architecture.jsonl',
            '--output',out/'architecture-survey','--concurrency','8')
        run('mentions.llm_survey','--database','/papers/papers.sqlite','--candidates',llm_candidates,
            '--raw',work/'llm.jsonl','--output',out/'llm-survey','--concurrency','8')
        evaluation_args=['--database','/papers/papers.sqlite','--candidates',evaluation_candidates,
                         '--raw',work/'evaluations.jsonl','--verification',work/'verification.jsonl',
                         '--output',out/'evaluations']
        run('mentions.evaluations',*evaluation_args,'--classify-only')
        run('mentions.evaluation_verification','--candidates',evaluation_candidates,
            '--raw',work/'evaluations.jsonl','--verification',work/'verification.jsonl')
        run('mentions.evaluations',*evaluation_args)
        staging=state/'publishing'
        if staging.exists():
            shutil.rmtree(staging)
        publish(state,state/'input/catalog.sqlite',staging)
        run('mentions.lifecycle','--database',state/'input/catalog.sqlite',
            '--evaluations',staging/'evaluations/papers.json','--releases',state/'input/model_releases.json',
            '--output',staging/'baseline-lifecycle')
        published=state/'published'
        if published.exists():
            shutil.rmtree(published)
        staging.rename(published)
        print(f'All surveys and lifecycle updated through {month}',flush=True)
    finally:
        state_volume.commit()


@app.local_entrypoint()
def main(month: str, database: str = 'data/analysis-papers.sqlite'):
    import re
    if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])',month):
        raise ValueError('month must be YYYY-MM')
    key=os.environ.get('TYPESAFE_API_KEY')
    if not key:
        raise ValueError('TYPESAFE_API_KEY is required')
    with state_volume.batch_upload(force=True) as upload:
        upload.put_file(database,'/input/catalog.sqlite')
        upload.put_file(ROOT/'docs/model_releases.json','/input/model_releases.json')
        for kind in ('architecture-survey','llm-survey','evaluations'):
            upload.put_directory(ROOT/'output'/kind,'/bootstrap/'+kind)
    refresh.with_options(secrets=[modal.Secret.from_dict({'TYPESAFE_API_KEY':key})]).remote(month)
    files={'architecture-survey':['summary.json','monthly.csv'],
           'llm-survey':['summary.json','monthly.csv'],
           'evaluations':['summary.json','papers.json','evaluations.csv','audit.json'],
           'baseline-lifecycle':['summary.json','monthly.csv']}
    for kind,names in files.items():
        for name in names:
            target=ROOT/'output'/kind/name
            target.parent.mkdir(parents=True,exist_ok=True)
            temp=target.with_suffix(target.suffix+'.part')
            with temp.open('wb') as handle:
                for chunk in state_volume.read_file('published/'+kind+'/'+name):
                    handle.write(chunk)
            temp.replace(target)
