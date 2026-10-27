"""Write the reviewable corpus and a local SQLite database.

The corpus that belongs in git is JSONL, one paper per line, split by the
year of first submission:

    data/corpus/2023.jsonl
    data/corpus/2024.jsonl
    ...

One YAML document for all 39k papers is about 80 MB and has no practical
diff. A committed SQLite file is one binary blob, so a reviewer cannot see
what changed. JSONL is the same row shape as a table, plain text, and a
change to one paper is one changed line. `papers.sqlite` is generated from
those files for queries and is gitignored.

Rows are written only for papers that have been scanned. Re-run after the
scan catches up to refresh both outputs.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from collections import defaultdict
from mentions.paths import data_dir
from mentions.taxonomy import variant_records

META = {row["variant_id"]: row for row in variant_records()}


def corpus_dir():
    path = data_dir() / "corpus"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def paper_rows(records_input=None, hits_input=None) -> list[dict]:
    data = data_dir()
    records = {row["id"]: row for row in (records_input if records_input is not None else load_jsonl(data / "records.jsonl"))}
    rows = []
    for hit in {h["id"]: h for h in (hits_input if hits_input is not None else load_jsonl(data / "hits.jsonl"))}.values():
        if hit.get("source") != "arxiv_bulk_pdf":
            continue
        record = records.get(hit["id"])
        if record is None:
            continue
        variants = []
        for vid in hit["variants"]:
            meta = META.get(vid, {})
            variants.append({
                "id": vid,
                "label": meta.get("label", vid),
                "family": meta.get("family_label", ""),
                "country": meta.get("country", ""),
                "company": meta.get("company", ""),
            })
        rows.append({
            "id": hit["id"],
            "version": record["version"],
            "published": record["published"],
            "month": record["month"],
            "primary": record["primary"],
            "categories": record["categories"],
            "title": record["title"],
            "abstract": record["summary"],
            "text_source": hit["source"],
            "pdf_path": record.get("pdf_path", f"pdf/{hit['id']}.pdf"),
            "full_text_path": record.get("full_text_path", f"text/{hit['id']}.txt"),
            "location": record.get("location"),
            "variants": variants,
        })
    rows.sort(key=lambda row: (row["published"], row["id"]))
    return rows


def write_jsonl(rows: list[dict]) -> None:
    corpus = corpus_dir()
    by_year: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_year[row["month"][:4]].append(row)
    written = []
    for year, year_rows in sorted(by_year.items()):
        path = corpus / f"{year}.jsonl"
        tmp = path.with_suffix(".jsonl.part")
        with tmp.open("w") as handle:
            for row in year_rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        tmp.replace(path)
        written.append(f"{path.name} ({len(year_rows)})")
    for stale in corpus.glob("[0-9][0-9][0-9][0-9].jsonl"):
        if stale.stem not in by_year:
            stale.unlink()
    print("wrote", ", ".join(written))


def write_sqlite(rows: list[dict], index_rows=None) -> None:
    db_path = data_dir() / "papers.sqlite"
    temporary = db_path.with_suffix(".sqlite.part")
    temporary.unlink(missing_ok=True)
    conn = sqlite3.connect(temporary)
    conn.executescript("""
        CREATE TABLE papers (
            id TEXT PRIMARY KEY,
            version TEXT,
            published TEXT,
            month TEXT,
            primary_category TEXT,
            categories TEXT,
            title TEXT,
            abstract TEXT,
            text_source TEXT
        );
        CREATE TABLE mentions (
            paper_id TEXT,
            variant_id TEXT,
            label TEXT,
            family TEXT,
            country TEXT,
            company TEXT,
            PRIMARY KEY (paper_id, variant_id)
        );
        CREATE INDEX mentions_country ON mentions(country);
        CREATE INDEX mentions_company ON mentions(company);
        CREATE INDEX papers_month ON papers(month);
    """)
    for row in rows:
        conn.execute(
            "INSERT INTO papers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["id"], row["version"], row["published"], row["month"],
                row["primary"], ",".join(row["categories"]),
                row["title"], row["abstract"], row["text_source"],
            ),
        )
        for variant in row["variants"]:
            conn.execute(
                "INSERT INTO mentions VALUES (?, ?, ?, ?, ?, ?)",
                (
                    row["id"], variant["id"], variant["label"], variant["family"],
                    variant["country"], variant["company"],
                ),
            )
    conn.execute("CREATE TABLE paper_index (id TEXT PRIMARY KEY, title TEXT, published TEXT, status TEXT, pdf_path TEXT, full_text_path TEXT, s3_key TEXT, byte_offset INTEGER, byte_length INTEGER, metadata TEXT)")
    for row in (index_rows if index_rows is not None else load_jsonl(data_dir() / "paper_index.jsonl")):
        loc = row.get("location") or {}
        conn.execute("INSERT INTO paper_index VALUES (?,?,?,?,?,?,?,?,?,?)", (row["id"], row["title"], row["published"], row["status"], row["pdf_path"], row["full_text_path"], loc.get("s3_key"), loc.get("byte_offset"), loc.get("byte_length"), json.dumps(row)))
    conn.commit()
    conn.close()
    temporary.replace(db_path)
    print(f"wrote {db_path} ({len(rows)} papers)")


def main() -> None:
    rows = paper_rows()
    write_jsonl(rows)
    write_sqlite(rows)


if __name__ == "__main__":
    main()
