"""Scan harvested papers for model-variant mentions.

Full text is the bulk PDF, extracted with the bibliography kept. That is
the Interconnects content source `arxiv_bulk_pdf`. A paper whose PDF is
missing or too short to be a body is recorded as `failed` and stays out of
the scanned denominator. Title and abstract are not a substitute.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from collections import Counter, defaultdict

from mentions.match import FAMILY_OF, LABEL_OF, find_variants
from mentions.paths import data_dir, output_dir
from mentions.pdf_text import MIN_CHARS, PdfTextError, pdf_to_text, pdftotext_bin
from mentions.taxonomy import variant_records


def pdf_path(arxiv_id: str):
    return data_dir() / "pdf" / f"{arxiv_id}.pdf"


def load_paper_text(arxiv_id: str) -> str:
    """Return bulk-PDF text. Raises FileNotFoundError or PdfTextError."""
    path = pdf_path(arxiv_id)
    if not path.exists() or path.stat().st_size == 0:
        raise FileNotFoundError(path)
    text_path = data_dir() / "text" / f"{arxiv_id}.txt"
    cache_meta = text_path.with_suffix(".meta.json")
    expected = {
        "pdf_stamp": [path.stat().st_size, path.stat().st_mtime_ns],
        "extractor": hashlib.sha256(Path(__file__).with_name("pdf_text.py").read_bytes()).hexdigest(),
    }
    if text_path.exists() and cache_meta.exists():
        try:
            valid = json.loads(cache_meta.read_text()) == expected
        except (ValueError, OSError):
            valid = False
        if valid:
            cached = text_path.read_text(errors="replace")
            if len(cached.strip()) >= MIN_CHARS:
                return cached
    text = pdf_to_text(path)
    text_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = text_path.with_suffix(".txt.part")
    tmp.write_text(text)
    tmp.replace(text_path)
    meta_tmp = cache_meta.with_suffix(".part")
    meta_tmp.write_text(json.dumps(expected))
    meta_tmp.replace(cache_meta)
    return text


def load_records() -> list[dict]:
    records = data_dir() / "records.jsonl"
    if not records.exists():
        return []
    rows = []
    for line in records.read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def scan_record(row: dict) -> dict:
    """One paper. A missing or unreadable PDF is a failed scan, not a hit."""
    abstract = f"{row['title']} {row['summary']}"
    try:
        text = load_paper_text(row["id"])
    except FileNotFoundError:
        return _hit(row, "failed", [], abstract, error="pdf missing")
    except PdfTextError as exc:
        return _hit(row, "failed", [], abstract, error=str(exc))
    return _hit(row, "arxiv_bulk_pdf", sorted(find_variants(text)), abstract)


def _hit(row: dict, source: str, variants: list[str], abstract: str, error: str = "") -> dict:
    hit = {
        "id": row["id"],
        "month": row["month"],
        "primary": row["primary"],
        "source": source,
        "variants": variants,
        "abstract_variants": sorted(find_variants(abstract)),
    }
    if error:
        hit["error"] = error
    return hit


def scan_fingerprint() -> str:
    """Invalidate cached matches when extraction, matching or taxonomy changes."""
    root = Path(__file__).parent
    return hashlib.sha256(b"".join((root / name).read_bytes() for name in
        ("match.py", "taxonomy.py", "pdf_text.py", "scan.py"))).hexdigest()


def load_hits() -> dict[str, dict]:
    path = data_dir() / "hits.jsonl"
    return {row["id"]: row for row in (
        json.loads(line) for line in path.read_text().splitlines() if line.strip()
    )} if path.exists() else {}


def scan(limit: int | None = None, *, available_only: bool = False) -> None:
    pdftotext_bin()  # A missing executable is a setup failure.
    hits_path = data_dir() / "hits.jsonl"
    hits = load_hits()
    fingerprint = scan_fingerprint()
    n = failed = 0
    pdf_dir = data_dir() / "pdf"
    available = {path.stem: path for path in pdf_dir.glob("*.pdf")}
    records = load_records()
    if limit is not None:
        records = records[:limit]
    try:
        for row in records:
            path = available.get(row["id"], pdf_dir / f"{row['id']}.pdf")
            exists = row["id"] in available and path.stat().st_size > 0
            if available_only and not exists:
                continue
            stamp = [path.stat().st_size, path.stat().st_mtime_ns] if exists else None
            old = hits.get(row["id"], {})
            if (old.get("source") == "arxiv_bulk_pdf"
                    and old.get("fingerprint") == fingerprint
                    and old.get("pdf_stamp") == stamp):
                continue
            hit = scan_record(row)
            hit.update(fingerprint=fingerprint, pdf_stamp=stamp)
            hits[row["id"]] = hit
            n += 1
            failed += hit["source"] != "arxiv_bulk_pdf"
            if n % 50 == 0:
                print(f"scanned {n} failed {failed} latest {row['id']}", flush=True)
    finally:
        tmp = hits_path.with_suffix(".jsonl.part")
        with tmp.open("w") as handle:
            for hit in hits.values():
                handle.write(json.dumps(hit) + "\n")
        tmp.replace(hits_path)
    print(f"scan updated {n}, failed {failed}", flush=True)


def scanned_hits(hits: list[dict]) -> list[dict]:
    """Papers with usable full text. Failed scans stay in the discovered total."""
    return [hit for hit in hits if hit.get("source") == "arxiv_bulk_pdf"]


def summarize() -> None:
    record_ids = {r["id"] for r in load_records()}
    discovered = [h for h in load_hits().values() if h["id"] in record_ids]
    failed = [hit for hit in discovered if hit.get("source") != "arxiv_bulk_pdf"]
    hits = scanned_hits(discovered)
    by_month_papers = Counter(h["month"] for h in hits)
    by_month_variant: dict[str, Counter] = defaultdict(Counter)
    by_month_any = Counter()
    variant_total = Counter()
    family_total = Counter()
    for h in hits:
        if h["variants"]:
            by_month_any[h["month"]] += 1
        for vid in h["variants"]:
            by_month_variant[h["month"]][vid] += 1
            variant_total[vid] += 1
        family_total.update({FAMILY_OF[vid] for vid in h["variants"]})

    records = {r["variant_id"]: r for r in variant_records()}
    # A paper counts once per country and once per company, even if it
    # names several variants from the same origin.
    country_total: Counter = Counter()
    company_total: Counter = Counter()
    by_month_country: dict[str, Counter] = defaultdict(Counter)
    by_month_company: dict[str, Counter] = defaultdict(Counter)
    for h in hits:
        countries = {records[vid]["country"] for vid in h["variants"] if vid in records}
        companies = {records[vid]["company"] for vid in h["variants"] if vid in records}
        for country in countries:
            country_total[country] += 1
            by_month_country[h["month"]][country] += 1
        for company in companies:
            company_total[company] += 1
            by_month_company[h["month"]][company] += 1
    rows = []
    for vid, count in variant_total.most_common():
        rec = records[vid]
        rows.append({
            "variant_id": vid,
            "label": LABEL_OF[vid],
            "family": rec["family_label"],
            "country": rec["country"],
            "company": rec["company"],
            "access": rec["access_class"],
            "papers": count,
            "share_of_scanned": round(count / len(hits), 4) if hits else 0,
            "share_of_model_papers": round(count / by_month_any.total(), 4) if by_month_any.total() else 0,
        })
    summary = {
        "papers_discovered": len(record_ids),
        "papers_pending": len(record_ids - {h["id"] for h in discovered}),
        "papers_scanned": len(hits),
        "papers_failed": len(failed),
        "content_source": "arxiv_bulk_pdf",
        "includes_bibliography": True,
        "papers_mentioning_any_tracked_variant": by_month_any.total(),
        "variants": rows,
        "family_paper_hits": family_total.most_common(),
        "by_country": [
            {"country": country, "papers": count,
             "share_of_model_papers": round(count / by_month_any.total(), 4) if by_month_any.total() else 0}
            for country, count in country_total.most_common()
        ],
        "by_company": [
            {"company": company, "papers": count,
             "share_of_model_papers": round(count / by_month_any.total(), 4) if by_month_any.total() else 0}
            for company, count in company_total.most_common()
        ],
        "months": sorted(by_month_papers),
        "monthly": {
            month: {
                "papers_scanned": by_month_papers[month],
                "any_model_papers": by_month_any[month],
                "variants": dict(by_month_variant[month]),
                "countries": dict(by_month_country[month]),
                "companies": dict(by_month_company[month]),
            }
            for month in sorted(by_month_papers)
        },
    }
    out = output_dir()
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: summary[k] for k in (
        "papers_discovered", "papers_scanned", "papers_failed",
        "papers_mentioning_any_tracked_variant",
    )}, indent=2))
    print("top variants:")
    for row in rows[:20]:
        print(f"  {row['papers']:5d}  {row['share_of_model_papers']:6.1%} of model papers  {row['label']}  ({row['company']}, {row['country']})")
    print("by country:")
    for row in summary["by_country"]:
        print(f"  {row['papers']:5d}  {row['share_of_model_papers']:6.1%}  {row['country']}")
    print("by company:")
    for row in summary["by_company"][:12]:
        print(f"  {row['papers']:5d}  {row['share_of_model_papers']:6.1%}  {row['company']}")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"
    if cmd == "scan":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else None
        scan(limit)
    elif cmd == "summary":
        summarize()
    else:
        raise SystemExit(f"unknown command {cmd}")


if __name__ == "__main__":
    main()
