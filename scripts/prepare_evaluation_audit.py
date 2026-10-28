"""Choose a reproducible, stratified spot-check sample from Jev decisions."""
import argparse
import hashlib
import json
from pathlib import Path

from mentions.evaluations import MODEL_RECORDS, POLICY_SHA, adjudicate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw', type=Path, default=Path('data/evaluations/jev.jsonl'))
    parser.add_argument('--output', type=Path, default=Path('data/evaluations/audit-sample.json'))
    args = parser.parse_args()
    strata = {'positive': [], 'negative': [], 'uncertain': []}
    latest = {}
    for line in args.raw.read_text().splitlines():
        row = json.loads(line)
        if row.get('policy_sha256') == POLICY_SHA:
            latest[row['paper_id']] = row
    for row in latest.values():
        for name, answer in row['answers'].items():
            if not name.endswith('_baseline'):
                continue
            mid = name.removesuffix('_baseline')
            probability = answer['noul']
            stratum = 'positive' if probability >= .7 else 'negative' if probability <= .3 else 'uncertain'
            strata[stratum].append(dict(paper_id=row['paper_id'], title=row['title'], month=row['month'],
                                       model_id=mid, model_label=MODEL_RECORDS[mid]['label'],
                                       baseline_probability=probability, jev_outcome=adjudicate(row, mid), stratum=stratum))
    selected = []
    for stratum, limit in [('positive', 16), ('negative', 16), ('uncertain', 8)]:
        ordered = sorted(strata[stratum], key=lambda r: hashlib.sha256(
            f"20261028:{r['paper_id']}:{r['model_id']}".encode()).hexdigest())
        selected.extend(ordered[:limit])
    edge_ids = {'2309.16699', '2312.04224', '2406.18699', '2409.08507', '2506.19597', '2603.07663', '2609.36151'}
    selected_keys = {(r['paper_id'], r['model_id']) for r in selected}
    for group in strata.values():
        for row in group:
            if row['paper_id'] in edge_ids and (row['paper_id'], row['model_id']) not in selected_keys:
                selected.append(dict(row, stratum='extraction_edge_case'))
    result = dict(seed='20261028', source_papers_classified=len(latest),
                  strategy='16 positive, 16 negative, 8 uncertain paper/model pairs; stable hash order within strata; plus seven extraction edge cases',
                  stratum_populations={k: len(v) for k, v in strata.items()}, sample=selected)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(','.join(sorted({r['paper_id'] for r in selected})))


if __name__ == '__main__':
    main()
