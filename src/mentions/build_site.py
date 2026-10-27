"""Build the static site in site/.

Locally this reads the in-progress scan (data/hits.jsonl joined to
data/records.jsonl) so the server shows the latest papers. In GitHub
Actions, SITE_SOURCE=corpus reads data/corpus/*.jsonl, which is the
committed record the daily job appends.

The HTML is static. It fetches site/data/summary.json and
site/data/papers.json with relative paths, so the same build works on
http://127.0.0.1 and on GitHub Pages.
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from pathlib import Path

from mentions.paths import ROOT, data_dir
from mentions.taxonomy import variant_records

SITE = ROOT / "site"
SITE_DATA = SITE / "data"
META = {row["variant_id"]: row for row in variant_records()}


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def papers_from_scan() -> list[dict]:
    data = data_dir()
    records = {row["id"]: row for row in load_jsonl(data / "records.jsonl")}
    papers = []
    for hit in load_jsonl(data / "hits.jsonl"):
        record = records.get(hit["id"])
        if record is None:
            continue
        papers.append({
            "id": hit["id"],
            "month": hit["month"],
            "title": record["title"],
            "source": hit["source"],
            "variants": [
                {
                    "id": vid,
                    "label": META.get(vid, {}).get("label", vid),
                    "country": META.get(vid, {}).get("country", ""),
                    "company": META.get(vid, {}).get("company", ""),
                }
                for vid in hit["variants"]
                if vid in META
            ],
        })
    return papers


def papers_from_corpus() -> list[dict]:
    papers = []
    for path in sorted((data_dir() / "corpus").glob("*.jsonl")):
        for row in load_jsonl(path):
            papers.append({
                "id": row["id"],
                "month": row["month"],
                "title": row["title"],
                "source": row.get("text_source", ""),
                "variants": [
                    {
                        "id": variant["id"],
                        "label": variant.get("label", variant["id"]),
                        "country": variant.get("country", ""),
                        "company": variant.get("company", ""),
                    }
                    for variant in row.get("variants", [])
                ],
            })
    return papers


def summarize(papers: list[dict]) -> dict:
    papers = list({p["id"]: p for p in papers if p.get("source") == "arxiv_bulk_pdf"}.values())
    by_month_papers = Counter(paper["month"] for paper in papers)
    by_month_any = Counter()
    by_month_variant: dict[str, Counter] = defaultdict(Counter)
    by_month_country: dict[str, Counter] = defaultdict(Counter)
    by_month_company: dict[str, Counter] = defaultdict(Counter)
    variant_total = Counter()
    country_total = Counter()
    company_total = Counter()
    for paper in papers:
        if paper["variants"]:
            by_month_any[paper["month"]] += 1
        for variant in paper["variants"]:
            variant_total[variant["id"]] += 1
            by_month_variant[paper["month"]][variant["id"]] += 1
        for country in {variant["country"] for variant in paper["variants"] if variant["country"]}:
            country_total[country] += 1
            by_month_country[paper["month"]][country] += 1
        for company in {variant["company"] for variant in paper["variants"] if variant["company"]}:
            company_total[company] += 1
            by_month_company[paper["month"]][company] += 1
    model_papers = sum(by_month_any.values())
    scanned = len(papers)
    months = sorted(by_month_papers)
    return {
        "papers_scanned": scanned,
        "any_model_papers": model_papers,
        "through": months[-1] if months else "",
        "variants": [
            {
                "id": vid,
                "label": META.get(vid, {}).get("label", vid),
                "country": META.get(vid, {}).get("country", ""),
                "company": META.get(vid, {}).get("company", ""),
                "papers": count,
                "share_of_scanned": round(count / scanned, 4) if scanned else 0,
                "share_of_model_papers": round(count / model_papers, 4) if model_papers else 0,
            }
            for vid, count in variant_total.most_common()
        ],
        "countries": [
            {"id": key, "papers": count,
             "share_of_model_papers": round(count / model_papers, 4) if model_papers else 0}
            for key, count in country_total.most_common()
        ],
        "companies": [
            {"id": key, "papers": count,
             "share_of_model_papers": round(count / model_papers, 4) if model_papers else 0}
            for key, count in company_total.most_common()
        ],
        "months": months,
        "monthly": {
            month: {
                "papers": by_month_papers[month],
                "any": by_month_any[month],
                "variants": dict(by_month_variant[month]),
                "countries": dict(by_month_country[month]),
                "companies": dict(by_month_company[month]),
            }
            for month in months
        },
    }


def site_papers(papers: list[dict]) -> list[dict]:
    """Titles and variant ids only. Abstracts stay in the corpus JSONL."""
    out = []
    for paper in papers:
        if not paper["variants"]:
            continue
        out.append({
            "id": paper["id"],
            "month": paper["month"],
            "title": paper["title"],
            "variants": [variant["id"] for variant in paper["variants"]],
        })
    return out


def build() -> None:
    source = os.environ.get("SITE_SOURCE", "")
    if source == "corpus" or not (data_dir() / "hits.jsonl").exists():
        papers = papers_from_corpus()
        source_name = "corpus"
    else:
        papers = papers_from_scan()
        source_name = "scan"
    summary = summarize(papers)
    summary["source"] = source_name
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    (SITE_DATA / "summary.json").write_text(json.dumps(summary) + "\n")
    (SITE_DATA / "papers.json").write_text(json.dumps(site_papers(papers)) + "\n")
    print(
        f"built site from {source_name}: {summary['papers_scanned']} papers, "
        f"{summary['any_model_papers']} name a tracked model, through {summary['through']}"
    )


def main() -> None:
    build()


if __name__ == "__main__":
    main()
