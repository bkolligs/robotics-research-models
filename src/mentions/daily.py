"""Append papers submitted since the last corpus row, then rebuild shares.

Designed for a daily GitHub Actions run. It does not re-walk the historical
corpus. A paper already in data/corpus is left as it was, so a taxonomy
change does not silently rewrite history. New papers are matched and appended.

The committed record is data/corpus/YYYY.jsonl. data/papers.sqlite is rebuilt
locally and is not committed: a binary database makes the daily diff opaque.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from mentions.export_corpus import META, corpus_dir, write_jsonl, write_sqlite
from mentions.harvest import harvest_since
from mentions.match import find_variants
from mentions.paths import data_dir, output_dir
from mentions.pdf_store import PdfStoreError
from mentions.selective_store import fetch_pdfs
from mentions.pdf_text import PdfTextError
from mentions.scan import load_paper_text


def known_ids() -> set[str]:
    ids = set()
    corpus = corpus_dir()
    if not corpus.exists():
        return ids
    for path in corpus.glob("*.jsonl"):
        for line in path.read_text().splitlines():
            if line.strip():
                ids.add(json.loads(line)["id"])
    return ids


def latest_published() -> datetime | None:
    latest = None
    corpus = corpus_dir()
    if not corpus.exists():
        return None
    for path in corpus.glob("*.jsonl"):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            published = json.loads(line)["published"]
            stamp = datetime.fromisoformat(published.replace("Z", "+00:00"))
            if latest is None or stamp > latest:
                latest = stamp
    return latest


def row_from_record(record: dict) -> dict | None:
    """One new paper from its bulk PDF. None means the PDF was not readable.

    A missing PDF is not written into the corpus. Writing an abstract-only
    row would put an unscanned paper in the denominator and freeze it there,
    because the daily job does not rewrite history.
    """
    try:
        text = load_paper_text(record["id"])
    except (FileNotFoundError, PdfTextError) as exc:
        print(f"skip {record['id']}: {exc}", flush=True)
        return None
    variants = []
    for vid in sorted(find_variants(text)):
        meta = META.get(vid, {})
        variants.append({
            "id": vid,
            "label": meta.get("label", vid),
            "family": meta.get("family_label", ""),
            "country": meta.get("country", ""),
            "company": meta.get("company", ""),
        })
    return {
        "id": record["id"],
        "version": record["version"],
        "published": record["published"],
        "month": record["month"],
        "primary": record["primary"],
        "categories": record["categories"],
        "title": record["title"],
        "abstract": record["summary"],
        "text_source": "arxiv_bulk_pdf",
        "variants": variants,
    }


def append_new(lookback_days: int = 3) -> int:
    """Fetch a short overlap window so a missed day is picked up next run."""
    latest = latest_published()
    now = datetime.now(timezone.utc)
    # A multi-year gap is a local backfill, not a cron. One Actions run
    # cannot re-walk cs.RO, and trying would trip arXiv's rate limit.
    if latest is not None and now - latest > timedelta(days=14):
        print(
            f"corpus latest is {latest.date()}, more than 14 days behind. "
            "Daily job will not backfill history. Finish the local harvest "
            "and commit data/corpus first.",
            flush=True,
        )
        return 0
    if latest is None:
        start = now - timedelta(days=lookback_days)
    else:
        start = latest - timedelta(days=lookback_days)
    start_s = start.strftime("%Y%m%d%H%M")
    end_s = now.strftime("%Y%m%d%H%M")
    print(f"window {start_s} to {end_s}", flush=True)
    seen = known_ids()
    fresh = [record for record in harvest_since(start_s, end_s) if record["id"] not in seen]
    if fresh:
        data = data_dir()
        try:
            counts = fetch_pdfs(
                {record["id"] for record in fresh},
                data / "pdf",
                data / "pdf_manifest.xml",
                data / "tar",
            )
        except PdfStoreError as exc:
            print(f"bulk pdf fetch failed: {exc}", flush=True)
            print("no papers appended; the next run retries these ids", flush=True)
            return 0
        print(f"pdf fetch {counts}", flush=True)
    added = []
    for record in fresh:
        row = row_from_record(record)
        if row is None:
            continue
        added.append(row)
        seen.add(record["id"])
        print(f"added {record['id']} {record['month']} variants {len(row['variants'])}", flush=True)
    if not added:
        print("no new papers", flush=True)
        return 0
    existing = []
    for path in sorted(corpus_dir().glob("*.jsonl")):
        existing.extend(json.loads(line) for line in path.read_text().splitlines() if line.strip())
    write_jsonl(existing + added)
    return len(added)


def summarize_from_corpus() -> None:
    rows = []
    for path in sorted(corpus_dir().glob("*.jsonl")):
        rows.extend(json.loads(line) for line in path.read_text().splitlines() if line.strip())
    rows = list({r["id"]: r for r in rows if r.get("text_source") == "arxiv_bulk_pdf"}.values())
    by_month_papers = Counter(row["month"] for row in rows)
    by_month_variant: dict[str, Counter] = defaultdict(Counter)
    by_month_any = Counter()
    by_month_country: dict[str, Counter] = defaultdict(Counter)
    by_month_company: dict[str, Counter] = defaultdict(Counter)
    variant_total = Counter()
    country_total = Counter()
    company_total = Counter()
    for row in rows:
        if row["variants"]:
            by_month_any[row["month"]] += 1
        for variant in row["variants"]:
            variant_total[variant["id"]] += 1
            by_month_variant[row["month"]][variant["id"]] += 1
        for country in {variant["country"] for variant in row["variants"]}:
            country_total[country] += 1
            by_month_country[row["month"]][country] += 1
        for company in {variant["company"] for variant in row["variants"]}:
            company_total[company] += 1
            by_month_company[row["month"]][company] += 1
    model_papers = by_month_any.total()
    summary = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "papers": len(rows),
        "papers_mentioning_any_tracked_variant": model_papers,
        "variants": [
            {
                "variant_id": vid,
                "label": META.get(vid, {}).get("label", vid),
                "country": META.get(vid, {}).get("country", ""),
                "company": META.get(vid, {}).get("company", ""),
                "papers": count,
                "share_of_papers": round(count / len(rows), 4) if rows else 0,
                "share_of_model_papers": round(count / model_papers, 4) if model_papers else 0,
            }
            for vid, count in variant_total.most_common()
        ],
        "by_country": [
            {"country": country, "papers": count,
             "share_of_model_papers": round(count / model_papers, 4) if model_papers else 0}
            for country, count in country_total.most_common()
        ],
        "by_company": [
            {"company": company, "papers": count,
             "share_of_model_papers": round(count / model_papers, 4) if model_papers else 0}
            for company, count in company_total.most_common()
        ],
        "months": sorted(by_month_papers),
        "monthly": {
            month: {
                "papers": by_month_papers[month],
                "any_model_papers": by_month_any[month],
                "variants": dict(by_month_variant[month]),
                "countries": dict(by_month_country[month]),
                "companies": dict(by_month_company[month]),
            }
            for month in sorted(by_month_papers)
        },
    }
    out = output_dir()
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"summary {len(rows)} papers, {model_papers} name a tracked model", flush=True)


def corpus_rows() -> list[dict]:
    rows = []
    for path in sorted(corpus_dir().glob("*.jsonl")):
        rows.extend(json.loads(line) for line in path.read_text().splitlines() if line.strip())
    return rows


def main() -> None:
    added = append_new()
    # Local query cache. Gitignored, so the daily commit stays text.
    write_sqlite(corpus_rows())
    summarize_from_corpus()
    print(f"added {added}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"daily update failed: {exc}", file=sys.stderr)
        raise
