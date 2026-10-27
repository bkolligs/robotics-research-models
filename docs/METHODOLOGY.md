# Robotics research adoption, measured the way Interconnects measures LLMs

This is a reimplementation of the arXiv-mentions method behind
[dashboard.interconnects.ai/#arxiv-mentions](https://dashboard.interconnects.ai/#arxiv-mentions),
applied to robotics models. The public method is the dashboard contract and
the August 2026 write-up
[How many arXiv papers use various open LLMs](https://www.interconnects.ai/p/how-many-arxiv-papers-use-various).
The scanner that holds the executable LLM aliases is private. The rules below
are the public contract, copied, plus the variant split this study needs.

## What Interconnects actually counts

From the live dashboard payload (`/data/arxiv_mentions.json`, schema 2,
generated daily) and the chart notes in the dashboard bundle:

- Corpus: `cs.AI`, `cs.CL`, `cs.CV`, `cs.LG`, `stat.ML`. About 500k papers
  since late 2022. The chart window starts January 2023.
- Date basis: `first_submission`. A paper is filed in the month it was first
  submitted, not the month of the latest version.
- Version policy: `latest_available_at_scan`. One row per versionless arXiv id.
- Text: full text. Historical PDFs come from arXiv's requester-pays
  [Full Text via S3](https://info.arxiv.org/help/bulk_data_s3.html) bulk set.
  The daily sweep backfills new papers. Content sources in the contract are
  `arxiv_bulk_pdf`, `html`, `pdf`, `other`.
- Unit: `paper_presence`. A paper counts at most once per family per month.
- Co-mentions: `independent`. A paper that names Qwen and Llama counts for both.
- Bibliography: included (`includes_bibliography: true`). A citation counts.
  Lambert is explicit that a mention is not the same as use as a backbone.
- Denominators:
  - Paper rate = family papers / successfully scanned papers that month.
    Discovered papers with no usable text stay in the discovered total and
    are dropped from this denominator.
  - Rate (LLM papers) = family papers / papers that mention at least one of
    the 51 tracked families. This is the "1/3 of papers that mention any LLM
    mention Qwen" number.
- Release gate: a family is not counted in a paper submitted before that
  family's verified eligible date. Two families (`deepseek`, `kimi`) are
  still unresolved on that gate in the 2026-10-26 preview.
- Taxonomy: 51 raw families in the frozen scanner, 42 of them on the public
  curated list in
  [arxiv_models.csv](https://github.com/Interconnects-AI/tracked-models/blob/main/arxiv_models.csv).
  Aliases in that CSV are illustrative. The executable rules are
  provider-qualified so ordinary words (`command`, `phi`, `opt`) do not fire.
  Closed models (OpenAI GPT, Claude, Gemini) are in the denominator and on
  the chart. Region is the releasing organization's region.

The featured chart is a monthly line chart of those rates. Partial months are
drawn as month-to-date, not projected.

## What changes for robotics

The question is which robotics models papers use, and the relative share of
each release. Interconnects collapses a family (`llama` covers Llama 2, 3,
and 4). That hides the split we care about. So the unit here is the released
model, and the family is a rollup:

| Family | Variants kept separate |
| --- | --- |
| π | π0, π0-FAST, π0.5, π0.6, π*0.6, π0.7 |
| GR00T | N1, N1.5, N1.6, N1.7, plus a "version unspecified" row for bare "GR00T" |
| RT | RT-1, RT-1-X, RT-2, RT-2-X, RT-H |
| OpenVLA | OpenVLA, OpenVLA-OFT |
| Diffusion Policy | Diffusion Policy, 3D Diffusion Policy |
| RDT | RDT-1B, RDT2 |
| LingBot | LingBot-VLA, LingBot-VLA 2.0 |
| MolmoAct | MolmoAct, MolmoAct2 |
| Gemini Robotics | Gemini Robotics, Gemini Robotics 1.5 |

A longer alias consumes its span before a shorter sibling. `π0.5` is not
also `π0`. `RT-2-X` is not also `RT-2`. `OpenVLA-OFT` is not also `OpenVLA`
unless the base name also appears. Bare `GR00T` is its own row, not N1.

`π0` is the awkward name. Bare `pi0` and `$\pi_{0}$` are also standard
policy notation, and a raw match counted 2023 control papers as π0 users.
Those spellings count only when a model cue sits within 180 characters:
`VLA`, `vision-language-action`, `Physical Intelligence`, `openpi`,
`flow matching`, or a dotted sibling (`pi0.5`, `pi0-FAST`). `pi0.5` and
`pi05` always count. They are not policy notation.

Ordinary words stay qualified, the same way Interconnects qualifies `command`
and `phi`. `Octo` matches `octo policy` / `octo model`, not the animal.
`ACT` matches "Action Chunking with Transformers", not the verb. `FAST`
matches "FAST action tokenizer" and the expanded name, not the adjective.

Corpus: `cs.RO`, first submission from 2023-01-01, which is the same start
Interconnects uses. `cs.RO` is the robotics analogue of their five ML
categories. It is smaller (about 39k papers in that window) and it misses
robotics papers filed only under `cs.LG` or `cs.CV`. Those can be added later
as a second corpus. They are not mixed into the first denominator.

## Full text

Historical text is the arXiv bulk PDF, the content source the dashboard
calls `arxiv_bulk_pdf`. The pipeline selectively reads the requester-pays bucket
`s3://arxiv` (`RequestPayer=requester`), keeps the PDFs whose ids are in
the harvest, and extracts each one with `pdftotext`. The bibliography
stays in the extracted text, so a citation counts.

A paper with no PDF in the current bulk snapshot, or whose extract is
shorter than a paper body, is `failed`. It stays in the discovered total
and is dropped from the scanned denominator. Title and abstract are not
used as a fallback. The daily job leaves such a paper unwritten so the
next run can retry it once the bulk snapshot includes it. The caller pays
the S3 transfer. AWS credentials are the standard chain.

## What this reimplementation cannot copy exactly

- The private precision policy and release gate are not available. A variant
  is counted whenever its name appears. Pre-release mentions are possible
  and will be rare for these names.
- The variant list is a curated baseline set, on the same principle as their
  51 families. It is not every robotics checkpoint. A name that is not in
  `src/mentions/taxonomy.py` cannot be counted.

## Outputs

The reviewable corpus is JSONL, one paper per line, split by first-submission
year in `data/corpus/`. A single YAML file of 39k papers is about 80 MB and
does not diff. A committed SQLite file is one binary blob, so a reviewer
cannot see which paper changed. JSONL is the same row shape as a table, and
a change to one paper is one changed line.

`data/papers.sqlite` is generated from those files by `uv run mentions-export`
for local queries. It is gitignored. Rebuild it rather than committing it.

The daily job (`uv run mentions-daily`, scheduled in `.github/workflows/daily.yml`)
appends papers whose first submission is newer than the latest corpus row.
It looks back three days so a missed run is recovered on the next one.
Papers already in the corpus are not rewritten. That keeps the git history
a log of new papers, and it means a later alias fix does not silently
change old counts. Re-run the full pipeline locally when the taxonomy
itself changes:

```bash
MENTIONS_DATA=/var/lib/mentions uv run mentions-pipeline
```

`MENTIONS_DATA` is the disk that holds `records.jsonl`, `hits.jsonl`, the
bulk PDFs, the extracted text, and the year-split corpus. The default is
`data/` in the checkout. A rerun skips nonempty PDFs and successful scans whose matching code and PDF
stamp are unchanged. Failed scans are retried, and changes to the matcher or
taxonomy invalidate cached matches. Parsing and export checkpoint after each
bulk archive, so results appear before the entire download finishes.
Install poppler (`pdftotext`) and run `uv sync --group bulk` first. The
bulk group installs boto3, which the S3 download needs.

- `data/corpus/YYYY.jsonl` — one row per successfully scanned paper: id, version, date,
  categories, title, abstract, text source, and the variants found, each
  with its family, country, and company
- `data/papers.sqlite` — local query cache, not committed
- `output/summary.json` — monthly paper counts and shares
- `output/mentions.png` — the chart

Each variant carries the releasing organization's country and company.
Country is headquarters country, the same basis Interconnects uses for
region. A paper counts once per country and once per company even when it
names several variants from that origin.

Shares:

- paper rate = papers naming that variant / scanned papers that month
- model-paper rate = papers naming that variant / papers naming any tracked variant

A paper can sit in more than one variant's numerator. Shares of a family,
a country, or a company therefore need not sum to 100%.

### Selective transfer and integrity

The source remains `arxiv_bulk_pdf`. The downloader walks the uncompressed tar
headers with conditional S3 byte-range requests and transfers only PDFs whose
ids belong to the metadata harvest. Cached indexes use the manifest checksum;
PDF receipts use SHA-256. Changed archives are reindexed, missing or damaged PDFs
are fetched again, and byte-identical PDFs preserve their timestamps. Explicit
`--overwrite` on the download scripts forces replacement. This changes transfer
mechanics, not the matching rules or scanned denominator.

Ranges are pinned to an ETag and checked for exact length and Content-Range.
Tar header checksums are validated. Selective downloads do not validate the
whole-tar MD5, because that requires all payload bytes. The manifest size is the
payload total and can differ from S3 Content-Length due to tar headers/padding.
