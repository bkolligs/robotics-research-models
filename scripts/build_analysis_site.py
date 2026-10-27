"""Build the inspection site from committed analysis exports, without raw data."""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    output, site = ROOT/'output', ROOT/'site'
    summary = json.loads((output/'summary.json').read_text())
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
    print(f'Built inspection site: {summary["papers_scanned"]:,} scanned; {len(papers):,} matching papers')

if __name__=='__main__':
    main()
