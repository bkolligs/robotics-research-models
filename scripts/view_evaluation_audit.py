"""Print source passages for a spot-check; does not make review decisions."""
import argparse
import gzip
import json
import re
from pathlib import Path
from mentions.evaluations import MODEL_RECORDS
from mentions.match import normalize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stratum')
    parser.add_argument('--paper')
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--count', type=int, default=8)
    parser.add_argument('--windows', type=int, default=3)
    parser.add_argument('--radius', type=int, default=7)
    args = parser.parse_args()
    sample = json.loads(Path('data/evaluations/audit-sample.json').read_text())['sample']
    if args.stratum:
        sample = [r for r in sample if r['stratum'] == args.stratum]
    if args.paper:
        sample = [r for r in sample if r['paper_id'] == args.paper]
    sample = sample[args.offset:args.offset + args.count]
    wanted = {r['paper_id'] for r in sample}
    with gzip.open('data/evaluations/audit-text.jsonl.gz', 'rt') as handle:
        texts = {r['paper_id']: r['text'] for r in map(json.loads, handle) if r['paper_id'] in wanted}
    for item in sample:
        print(json.dumps(item, ensure_ascii=False))
        lines = texts[item['paper_id']].splitlines()
        aliases = [*MODEL_RECORDS[item['model_id']]['aliases'], item['model_label']]
        patterns = [re.compile(r'(?<![a-z0-9])' + re.escape(normalize(a).strip()) + r'(?![a-z0-9.])') for a in aliases]
        if item['model_id'] == 'act':
            patterns.append(re.compile(r'\bact\b'))
        hits = []
        for i, line in enumerate(lines):
            if any(p.search(normalize(line)) for p in patterns):
                start, end = max(0, i - args.radius), min(len(lines), i + args.radius + 1)
                excerpt = '\n'.join(lines[start:end])
                score = len(re.findall(r'(?i)baseline|success|ours|table|evaluat|compar|implement|experiment', excerpt))
                hits.append((score, i, start, end))
        used = set()
        count = 0
        for _score, i, start, end in sorted(hits, reverse=True):
            if i in used:
                continue
            used.update(range(start, end))
            print('\n'.join(f'{j+1}: {lines[j]}' for j in range(start, end)))
            count += 1
            if count == args.windows:
                break
        if not hits:
            print('No single-line alias hit; inspect full text for wrapping or notation.')


if __name__ == '__main__':
    main()
