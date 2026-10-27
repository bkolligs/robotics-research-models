# Robotics research models

Which robotics models show up in `cs.RO` papers, and what share of those
papers name each release. The method follows the Interconnects arXiv-mentions
study ([dashboard](https://dashboard.interconnects.ai/#arxiv-mentions),
[write-up](https://www.interconnects.ai/p/how-many-arxiv-papers-use-various)),
with one change: each released model is its own row. `π0.5` is not also `π0`.

See [METHODOLOGY.md](docs/METHODOLOGY.md) for the corpus, the denominators, and
the alias rules.

## Layout

Python package `mentions`, managed with [uv](https://docs.astral.sh/uv/).

- `src/mentions/taxonomy.py` — variants, with country and releasing organization
- `src/mentions/harvest.py` — arXiv metadata for `cs.RO` since January 2023
- `src/mentions/scan.py` — full-text mention scan and monthly shares
- `src/mentions/export_corpus.py` — writes `data/corpus/YYYY.jsonl` and a local
  `data/papers.sqlite`

## Full pipeline

The historical run downloads each paper's PDF from arXiv's requester-pays
bulk bucket and scans that text, bibliography included. Point
`MENTIONS_DATA` at a disk that can hold the PDFs, configure AWS
credentials, install `pdftotext`, then:

```bash
uv sync --group bulk
MENTIONS_DATA=/var/lib/mentions uv run mentions-pipeline
```

That harvests `cs.RO` metadata, stores each PDF under `$MENTIONS_DATA/pdf/`,
extracts the text, and writes `$MENTIONS_DATA/corpus/YYYY.jsonl`, a local
SQLite file, and `output/summary.json`. Set `MENTIONS_OUTPUT` to put the
summary somewhere else. Stop the command and run it again to resume. A
paper with no readable PDF is recorded as failed and stays out of the
scanned rate.

The daily job is separate. It appends new papers and does not rebuild
this cache.

The committed paper record is JSONL, one paper per line, split by year.
SQLite is generated for queries and is not committed. A single YAML file
and a committed database are both hard to review at this size: the daily
diff would be either an 80 MB rewrite or one opaque binary blob.

`.github/workflows/daily.yml` runs at 12:30 UTC. It appends `cs.RO` papers
submitted since the latest corpus row, with a 3-day overlap so a missed run
is recovered, and commits `data/corpus/` plus `output/summary.json`. It does
not rescan history. A taxonomy change applies to papers added after it.

## Site

The explorer is a static site in `site/`. Locally it reads the in-progress
scan. GitHub Pages builds the same pages from the committed corpus.

```bash
uv run mentions-serve
```

Open http://127.0.0.1:8765 . Restart the server to pick up papers the scan
has added since it started.

## Modal workspace

Complete the local metadata harvest with `uv run mentions-harvest`. The Modal
launcher uploads that metadata and stores the study's cs.RO PDFs, extracted
text, corpus, and summary in the persistent Volume selected by `MENTIONS_MODAL_VOLUME` (default: `papers`).
It transfers only this study's PDFs using S3 byte ranges.

```bash
uv sync --group bulk --group modal
AWS_PROFILE=your-aws-profile uv run --no-sync modal run --profile your-modal-profile --detach scripts/modal_pipeline.py \
  --records data/records.jsonl --workers 10
```

The launcher verifies AWS STS before forwarding fresh temporary credentials as
an ephemeral Modal Secret for each wave of workers. Keys are never written to
the repository or passed as function arguments. Keep the local driver running;
`--detach` preserves only in-flight calls if the driver exits. When the AWS
login expires, log in and relaunch. `--profile your-modal-profile` selects your
workspace independently of the active Modal profile.

Set `MENTIONS_MODAL_VOLUME` to your existing volume name to resume stored data.
Set `MENTIONS_MODAL_APP` to select an app name. Keep these local settings out of Git.

The Modal pipeline has three stages:

1. Ten workers build cached archive offsets in parallel. A barrier then creates
   `paper_manifest.jsonl`: all paper metadata, S3 bucket/key/ETag, byte offset
   and length, planned PDF/full-text paths, and initial status.
2. Ten workers process disjoint archives and papers: selective download,
   text conversion, matching, and per-worker corpus/index export. Each paper
   has exactly one writer. Files under `runs/<manifest hash>/shards/` checkpoint
   results; failed invocations prevent consolidation.
3. One reducer validates exact coverage and merges `paper_index.jsonl`,
   `hits.jsonl`, yearly corpus files, summary, and `papers.sqlite`.

The SQLite `paper_index` table includes **all** study papers, their metadata,
processing status, S3 locations, and PDF/full-text paths. Paths are relative to
`MENTIONS_DATA` (`/papers` on Modal). A planned text path does not mean extraction
succeeded: check `status = 'complete'`. The `papers` and `mentions` tables contain
only successful scans, preserving the scanned denominator.

`indexes/*.tar.json` are small JSON caches of tar headers and download receipts,
not tar archives or the paper database. They avoid repeating S3 header requests.
Keep them for inexpensive reruns. A single pipeline owns the Volume at a time;
its workers write disjoint files. Worker batches have a one-hour timeout.

To download and parse locally after the harvest:

```bash
AWS_PROFILE=your-aws-profile uv run --no-sync mentions-pipeline --skip-harvest
```

The downloader reads tar headers with S3 byte-range requests, then transfers only
the cs.RO PDF payloads. Full archives are not downloaded. Parsing and export
checkpoint during the run. Failed papers stay out of the corpus and all scanned rates.
Changed matching rules invalidate successful scan results on a historical rerun.
The daily job's 14-day backfill guard remains unchanged.

## Selective downloads and reruns

Both the historical pipeline and daily job now use selective S3 ranges. The
standalone local script is:

```bash
AWS_PROFILE=your-aws-profile uv run --no-sync python scripts/download_papers.py
# Force downloading and replacing every selected PDF:
AWS_PROFILE=your-aws-profile uv run --no-sync python scripts/download_papers.py --overwrite
```

The Modal script also accepts `--overwrite`, `--max-chunks N` for bounded runs,
plus `--workers N` (default and maximum 10) and `--batch-size N` (default 5 archives per worker).
Bounded runs validate all stages but keep outputs under `runs/`, leaving published
outputs alone. Omit `--max-chunks` for the full corpus.
Unchanged archive indexes persist in `indexes/` on the data disk or Modal Volume.
PDF receipts store SHA-256 hashes: an unchanged archive with verified local PDFs
requires no additional header or PDF downloads. A new archive checksum triggers
reindexing; only wanted PDFs are fetched, and identical bytes preserve the existing
file and its timestamp. Damaged or missing PDFs are fetched again. This is a
file-level update, not binary delta transfer: a changed PDF is fetched in full.

Range requests pin the source ETag and validate HTTP status, Content-Range,
length, and tar header checksums. Whole-archive MD5 verification is unavailable
without downloading the whole archive; PDF hashes verify cached bytes on reruns.
Keep the indexes with the PDFs to preserve inexpensive resumes. AWS credential
expiry stops the driver; refresh login and rerun the same command to resume.

To restart only consolidation after workers finish (no AWS credentials or PDF
redownloads), use the manifest hash printed by the pipeline:

```bash
uv run --no-sync modal run --profile your-modal-profile --detach scripts/modal_pipeline.py \
  --consolidate-run MANIFEST_SHA256
```

Stop the previous consolidation before starting its replacement. Consolidation
prints its stage and archive/paper counts every ten seconds, validates all shard
coverage, and builds and integrity-checks SQLite on local worker disk. A validated
output generation and backups of prior published files are retained under
`runs/<manifest hash>/consolidations/<generation>/`. Individual published files
are replaced atomically; `consolidation_complete.json` identifies the published
generation. The final `committed` log confirms Volume persistence. Raw worker
shards, PDFs, text, and the manifest are never modified by consolidation.

View a running consolidation as a progress bar with throughput and an ETA:

```bash
uv run --no-sync python scripts/watch_consolidation.py
# Print only the latest snapshot:
uv run --no-sync python scripts/watch_consolidation.py --once
```

The ETA applies to shard validation; database construction, backup, publication,
and Volume commit follow. The watcher works with existing JSON progress logs, so
no restart is needed. New consolidation runs also print the bar directly.

## Full methodology analysis from the completed database

The analysis reuses the completed full-text matches; it does not download PDFs
or rerun extraction. Download `papers.sqlite` from the Modal Volume as
`data/analysis-papers.sqlite`, then run:

```bash
uv run --no-sync python -m mentions.analysis
uv run --no-sync mentions-chart
MENTIONS_DATA=data/analysis SITE_SOURCE=corpus uv run --no-sync mentions-site
```

`output/` contains coverage, variant/family/country/company totals and monthly
rates as CSV, `summary.json`, the two charts, and `analysis_provenance.json` with
input hashes and validation results. CSV shares are fractions between 0 and 1;
empty rate cells mean the denominator is zero. `date_diagnostics.json` lists
mentions in papers first submitted before a model's taxonomy introduction year;
these are diagnostics, not exclusions, since later paper revisions can include
newer models. Bibliography mentions count and do not establish backbone use.
The underlying database and reconstructed per-paper corpus stay under ignored
`data/`. Aggregate outputs are suitable for version control.
