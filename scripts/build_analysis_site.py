"""Build the inspection site from committed analysis exports, without raw data."""
import json
import hashlib
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def check_plot_coverage(output, summary):
    """Do not publish a new corpus alongside stale survey curves."""
    expected = {m: r['papers_scanned'] for m, r in summary['monthly'].items() if r['papers_scanned']}
    models = {m: r['any_model_papers'] for m, r in summary['monthly'].items() if r['any_model_papers']}
    architecture = json.loads((output/'architecture-survey/summary.json').read_text())
    llm = json.loads((output/'llm-survey/summary.json').read_text())
    evaluations = json.loads((output/'evaluations/summary.json').read_text())
    lifecycle = json.loads((output/'baseline-lifecycle/summary.json').read_text())
    catalog_hash = json.loads((output/'analysis_provenance.json').read_text())['database_sha256']
    if any(s.get('source_database_sha256') != catalog_hash for s in (architecture, llm, evaluations)):
        raise ValueError('Survey plots were not generated against the current catalog')
    if {r['month']: r['population'] for r in architecture['monthly']} != models:
        raise ValueError('Architecture plot does not cover the current model-paper corpus')
    if {r['month']: r['papers_scanned'] for r in llm['monthly']} != expected:
        raise ValueError('LLM plots do not cover the current scanned corpus')
    if (evaluations['monthly_population'] != expected or not evaluations['complete']
            or evaluations['papers_classified'] != sum(models.values())
            or evaluations['paper_model_pairs'] != sum(r['papers'] for r in summary['variants'])):
        raise ValueError('Evaluation plots do not cover the current model-paper corpus')
    if ({r['month']: r['scanned_papers'] for r in lifecycle['monthly_population'] if r['scanned_papers']} != expected
            or lifecycle['through'] != max(expected)):
        raise ValueError('Lifecycle plot does not cover the current scanned corpus')

def main():
    output, site = ROOT/'output', ROOT/'site'
    summary = json.loads((output/'summary.json').read_text())
    check_plot_coverage(output, summary)
    papers = json.loads((output/'papers.json').read_text())
    if len(papers) != summary['papers_mentioning_any_tracked_variant']:
        raise ValueError('Paper inspection export does not match analysis')
    payload = dict(papers_scanned=summary['papers_scanned'],
                   any_model_papers=summary['papers_mentioning_any_tracked_variant'],
                   through=summary['months'][-1], months=summary['months'],
                   variants=[dict(r,id=r['variant_id']) for r in summary['variants']],
                   countries=[dict(r,id=r['country']) for r in summary['by_country']],
                   companies=[dict(r,id=r['company']) for r in summary['by_company']],
                   monthly={m:dict(papers=r['papers_scanned'],any=r['any_model_papers'],
                                   variants=r['variants'],countries=r['countries'],companies=r['companies'])
                            for m,r in summary['monthly'].items()})
    (site/'data').mkdir(exist_ok=True)
    (site/'data/summary.json').write_text(json.dumps(payload))
    shutil.copyfile(output/'papers.json',site/'data/papers.json')
    target=site/'analysis'
    target.mkdir(exist_ok=True)
    for name in ['summary.json','analysis_provenance.json','date_diagnostics.json','mentions.png','origin.png','coverage.csv']:
        shutil.copyfile(output/name,target/name)
    for path in output.glob('*_totals.csv'):
        shutil.copyfile(path,target/path.name)
    for path in output.glob('*_monthly.csv'):
        shutil.copyfile(path,target/path.name)
    survey_source = Path(os.environ.get('ARCHITECTURE_SURVEY_OUTPUT', output/'architecture-survey'))
    survey_target = target/'architecture-survey'
    if survey_target.exists():
        shutil.rmtree(survey_target)
    if (survey_source/'summary.json').exists() and (survey_source/'monthly.csv').exists():
        survey_target.mkdir()
        shutil.copyfile(survey_source/'summary.json', survey_target/'summary.json')
        shutil.copyfile(survey_source/'monthly.csv', survey_target/'monthly.csv')
    llm_source = Path(os.environ.get('LLM_SURVEY_OUTPUT', output/'llm-survey'))
    llm_target = target/'llm-survey'
    if llm_target.exists():
        shutil.rmtree(llm_target)
    if (llm_source/'summary.json').exists() and (llm_source/'monthly.csv').exists():
        llm_target.mkdir()
        shutil.copyfile(llm_source/'summary.json', llm_target/'summary.json')
        shutil.copyfile(llm_source/'monthly.csv', llm_target/'monthly.csv')
    evaluation_source = output/'evaluations'
    if (evaluation_source/'summary.json').exists():
        evaluation_target = target/'evaluations'
        evaluation_target.mkdir(exist_ok=True)
        for name in ['summary.json', 'papers.json', 'evaluations.csv']:
            shutil.copyfile(evaluation_source/name, evaluation_target/name)
        if (evaluation_source/'audit.json').exists():
            shutil.copyfile(evaluation_source/'audit.json', evaluation_target/'audit.json')
    lifecycle_source = output/'baseline-lifecycle'
    if (lifecycle_source/'summary.json').exists():
        lifecycle = json.loads((lifecycle_source/'summary.json').read_text())
        if lifecycle['source_evaluations_sha256'] != hashlib.sha256((evaluation_source/'papers.json').read_bytes()).hexdigest():
            raise ValueError('Baseline lifecycle is stale; regenerate with uv run python -m mentions.lifecycle')
        if lifecycle['release_registry_sha256'] != hashlib.sha256((ROOT/'docs/model_releases.json').read_bytes()).hexdigest():
            raise ValueError('Lifecycle release dates changed; regenerate with uv run python -m mentions.lifecycle')
        lifecycle_target = target/'baseline-lifecycle'
        lifecycle_target.mkdir(exist_ok=True)
        for name in ['summary.json', 'monthly.csv']:
            shutil.copyfile(lifecycle_source/name, lifecycle_target/name)
    print(f'Built inspection site: {summary["papers_scanned"]:,} scanned; {len(papers):,} matching papers')

if __name__=='__main__':
    main()
