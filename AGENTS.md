# Agent instructions

This repo measures which robotics models `cs.RO` papers name. Read
[docs/METHODOLOGY.md](docs/METHODOLOGY.md) before changing matching, taxonomy,
or denominators. Do not treat a mention as proof that a paper used the model
as a backbone.

## Commands

Use uv. Python is 3.12. Do not add a `requirements.txt` or call `pip`.

```bash
uv sync --group bulk
uv run python -m unittest discover -s tests -q
MENTIONS_DATA=/var/lib/mentions uv run mentions-pipeline
uv run mentions-serve
```

`mentions-pipeline` is the historical backfill. It scans the arXiv bulk PDF,
bibliography included. `pdftotext` must be on `PATH`, and AWS credentials
must be able to read `s3://arxiv` as the requester. `mentions-daily` only
appends papers newer than the latest corpus row. Do not point the daily job
at the full harvest, and do not fall back to title and abstract.

## Data

`MENTIONS_DATA` defaults to `data/` and should point at a disk that can hold
the bulk PDFs. It stores `records.jsonl`, `hits.jsonl`, `harvest_cursor.txt`,
`pdf/`, `text/`, `corpus/YYYY.jsonl`, and `papers.sqlite`. `MENTIONS_OUTPUT`
defaults to `output/`.

Commit `data/corpus/*.jsonl` and `output/summary.json`. Do not commit
`data/pdf/`, `data/text/`, `data/html/`, `data/records.jsonl`, `data/hits.jsonl`,
the harvest cursor, `data/papers.sqlite`, `site/data/`, or `.venv/`. A paper
whose PDF did not extract is `failed` and is not part of the scanned
denominator.

The daily job refuses to backfill a gap longer than 14 days. Leave that
guard in place. It does not rescan history. A taxonomy or alias change needs
a local pipeline rerun before old counts change.

## Matching

Keep each released model on its own row. A longer alias consumes its span, so
`π0.5` is not also `π0`, and `RT-2-X` is not also `RT-2`. Bare `pi0` and
`$\pi_{0}$` count only with a nearby model cue. Add a test in
`tests/test_match.py` when an alias rule changes.

Country is the releasing organization's headquarters country. A paper counts
once per country and once per company. Shares overlap and need not sum to 100%.

## Site

`site/` is the GitHub Pages artifact. Asset paths stay relative. Local
`mentions-serve` reads the in-progress scan. Actions sets `SITE_SOURCE=corpus`.
Verify a site change by requesting the local server, not by a screenshot.

## Commits

Use Conventional Commits: `feat:`, `fix:`, `docs:`, `build:`, `ci:`, `chore:`,
`test:`, `refactor:`. The remote is SSH. Do not force-push `main` unless the
user asks to rewrite history. The daily workflow commits as
`chore: update cs.RO mention corpus`.
