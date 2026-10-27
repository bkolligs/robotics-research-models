"""Run the full mention study on a machine that can keep the papers.

    MENTIONS_DATA=/var/lib/mentions uv run mentions-pipeline

Harvests cs.RO metadata, downloads the matching PDFs from arXiv's
requester-pays bulk bucket, extracts the full text including the
bibliography, matches model names, and writes the year-split corpus.
A second run skips PDFs and hits already on disk.

This is the historical backfill. The daily job only appends new papers
and does not rebuild this cache. AWS credentials must be able to read
s3://arxiv with RequestPayer=requester. The caller pays the transfer.
"""

from __future__ import annotations

import argparse
import json
from mentions.pdf_text import pdftotext_bin

from mentions.export_corpus import main as export_main
from mentions.harvest import harvest
from mentions.paths import data_dir, output_dir
from mentions.selective_store import fetch_pdfs
from mentions.scan import scan, summarize


def main() -> None:
    parser = argparse.ArgumentParser(description="Harvest, cache, scan, and export the cs.RO corpus.")
    parser.add_argument(
        "--pages",
        type=int,
        default=None,
        help="Stop the harvest after this many API pages. For a smoke test.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Restrict download and scan to the first N harvested papers. For a smoke test.",
    )
    parser.add_argument("--skip-harvest", action="store_true", help="Use existing records.jsonl.")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    pdftotext_bin()

    data = data_dir()
    print(f"data dir {data}", flush=True)
    print(f"output dir {output_dir()}", flush=True)
    if not args.skip_harvest:
        harvest(args.pages)
    records = data / "records.jsonl"
    ids = []
    if records.exists():
        for line in records.read_text().splitlines():
            if line.strip():
                ids.append(json.loads(line)["id"])
    if args.limit is not None:
        ids = ids[: args.limit]
    if not ids:
        raise RuntimeError("No harvested records; refusing an empty pipeline run")

    def checkpoint():
        scan(limit=args.limit, available_only=True)
        summarize()
        export_main()

    checkpoint()
    while True:
        counts = fetch_pdfs(set(ids), data / "pdf", data / "pdf_manifest.xml", data / "tar",
                            on_chunk=checkpoint)
        print(f"pdf fetch {counts}", flush=True)
        latest = [json.loads(line)["id"] for line in records.read_text().splitlines() if line.strip()]
        if args.limit is not None:
            latest = latest[:args.limit]
        if set(latest) <= set(ids):
            break
        print(f"Harvest grew from {len(ids)} to {len(latest)} papers; fetching additions", flush=True)
        ids = latest
    scan(limit=args.limit)
    summarize()
    export_main()
    print(f"pipeline finished; pdf cache is {data / 'pdf'}", flush=True)


if __name__ == "__main__":
    main()
