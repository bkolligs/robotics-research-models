"""Resumable, selective local downloader. Unchanged PDFs are reused by default.

AWS_PROFILE=your-aws-profile uv run --no-sync python scripts/download_papers.py
Add --overwrite to download and replace all selected PDFs again.
"""
import argparse
from mentions.paths import data_dir
from mentions.pdf_store import download_manifest, yymm_of
from mentions.scan import load_records, scan, summarize
from mentions.export_corpus import main as export
from mentions.selective_store import fetch_chunk


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--overwrite', action='store_true')
    parser.add_argument('--max-chunks', type=int, default=0, help='0 means all archives')
    args = parser.parse_args()
    if args.max_chunks < 0:
        parser.error('--max-chunks must be nonnegative')
    data = data_dir()
    ids = {r['id'] for r in load_records()}
    if not ids:
        parser.error('Run mentions-harvest first')
    months = {yymm_of(i) for i in ids}
    chunks = [c for c in download_manifest(data / 'pdf_manifest.xml') if c.yymm in months]
    if args.max_chunks:
        chunks = chunks[:args.max_chunks]
    for chunk in chunks:
        fetch_chunk(chunk, ids, data, overwrite=args.overwrite)
        scan(available_only=True)
        summarize()
        export()


if __name__ == '__main__':
    main()
