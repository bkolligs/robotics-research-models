"""Harvest arXiv metadata and scan full text for model-variant mentions.

Corpus, matching the Interconnects date window on the robotics category:

- papers whose category list includes cs.RO
- first submission from 2023-01-01 through the harvest cutoff
- one record per arXiv id (versionless). Later versions replace earlier ones.
- the mention scan reads the bulk PDF, bibliography included. A paper
  whose PDF is missing or unreadable stays in the discovered total and
  is dropped from the scanned denominator.

The API query harvest is resumable. Records land in
$MENTIONS_DATA/records.jsonl.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from mentions.paths import data_dir

USER_AGENT = "robotics-research-models/0.1 (research mention study; local)"

NS = {
    "a": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}

def harvest_windows() -> list[tuple[str, str]]:
    """Calendar months avoid the API's 10,000-result pagination ceiling."""
    from datetime import datetime, timezone
    import calendar

    now = datetime.now(timezone.utc)
    return [
        (f"{year}{month:02d}010000",
         min(f"{year}{month:02d}{calendar.monthrange(year, month)[1]}2359",
             now.strftime("%Y%m%d%H%M")))
        for year in range(2023, now.year + 1)
        for month in range(1, 13)
        if (year, month) <= (now.year, now.month)
    ]


def _text(entry: ET.Element, tag: str) -> str:
    node = entry.find(f"a:{tag}", NS)
    if node is None:
        return ""
    return "".join(node.itertext()).strip()


def parse_entry(entry: ET.Element) -> dict:
    arxiv_id = ""
    for link in entry.findall("a:link", NS):
        if link.get("title") == "pdf":
            href = link.get("href", "")
            arxiv_id = href.rstrip("/").split("/")[-1].replace(".pdf", "")
            break
    if not arxiv_id:
        raw_id = _text(entry, "id")
        arxiv_id = raw_id.rstrip("/").split("/")[-1]
    # versionless id for the paper-presence unit
    base_id = arxiv_id.split("v")[0] if arxiv_id and arxiv_id[-1].isdigit() and "v" in arxiv_id else arxiv_id
    published = _text(entry, "published")
    categories = []
    primary = entry.find("arxiv:primary_category", NS)
    if primary is not None:
        categories.append(primary.get("term", ""))
    for cat in entry.findall("a:category", NS):
        term = cat.get("term", "")
        if term and term not in categories:
            categories.append(term)
    return {
        "id": base_id,
        "version": arxiv_id,
        "published": published,
        "month": published[:7],
        "title": " ".join(_text(entry, "title").split()),
        "summary": " ".join(_text(entry, "summary").split()),
        "categories": categories,
        "primary": categories[0] if categories else "",
    }


def fetch(url: str, tries: int = 6) -> bytes:
    last = None
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in (429, 500, 502, 503):
                # arXiv's export API asks for minutes, not seconds, once
                # a long walk has tripped the limiter.
                print(f"arXiv HTTP {exc.code}; retry {attempt + 1}/{tries} in {30 * (attempt + 1)}s", flush=True)
                time.sleep(30 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            print(f"arXiv network error; retry {attempt + 1}/{tries}", flush=True)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"fetch failed: {last}")


def _flush(records_path, seen: dict[str, dict], cursor_path, cursor: str) -> None:
    tmp = records_path.with_suffix(".jsonl.part")
    with tmp.open("w") as handle:
        for row in seen.values():
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(records_path)
    cursor_tmp = cursor_path.with_suffix(".part")
    cursor_tmp.write_text(cursor)
    cursor_tmp.replace(cursor_path)


def harvest(max_pages: int | None = None) -> None:
    data = data_dir()
    records_path = data / "records.jsonl"
    seen: dict[str, dict] = {}
    if records_path.exists():
        for line in records_path.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                seen[row["id"]] = row
        print(f"resume with {len(seen)} records", flush=True)

    cursor_path = data / "harvest_cursor.txt"
    cursor = cursor_path.read_text().strip() if cursor_path.exists() else ""
    page = 200
    pages = 0
    for start_date, end_date in harvest_windows():
        window_id = f"{start_date}-{end_date}"
        if cursor and window_id < cursor.split("@")[0]:
            print(f"skip window {window_id}", flush=True)
            continue
        start = 0
        if cursor.startswith(window_id + "@"):
            mark = cursor.split("@")[1]
            if mark == "done":
                print(f"skip finished window {window_id}", flush=True)
                continue
            start = int(mark)
            print(f"resume window {window_id} at {start}", flush=True)
        query = f"cat:cs.RO AND submittedDate:[{start_date} TO {end_date}]"
        total = None
        while True:
            url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode({
                "search_query": query,
                "start": start,
                "max_results": page,
                "sortBy": "submittedDate",
                "sortOrder": "ascending",
            })
            root = ET.fromstring(fetch(url))
            if total is None:
                total_node = root.find("opensearch:totalResults", NS)
                total = int(total_node.text) if total_node is not None else 0
                print(f"window {window_id} total {total}", flush=True)
            entries = root.findall("a:entry", NS)
            if not entries:
                if start < (total or 0):
                    raise RuntimeError("arXiv returned an empty page before the reported total")
                break
            new = 0
            for entry in entries:
                row = parse_entry(entry)
                if "cs.RO" not in row["categories"]:
                    continue
                if row["id"] not in seen:
                    new += 1
                seen[row["id"]] = row
            start += len(entries)
            pages += 1
            print(f"{window_id} start {start} unique {len(seen)} new {new}", flush=True)
            _flush(records_path, seen, cursor_path, f"{window_id}@{start}")
            if start >= (total or 0):
                break
            if max_pages is not None and pages >= max_pages:
                print(f"wrote {len(seen)} records", flush=True)
                return
            time.sleep(3.0)
        _flush(records_path, seen, cursor_path, f"{window_id}@done")
        if max_pages is not None and pages >= max_pages:
            return
        time.sleep(3.0)
    print(f"wrote {len(seen)} records", flush=True)


def harvest_since(start_date: str, end_date: str) -> list[dict]:
    """One date window, for the daily job. start/end are YYYYMMDDHHMM."""
    query = f"cat:cs.RO AND submittedDate:[{start_date} TO {end_date}]"
    start = 0
    page = 100
    found: list[dict] = []
    total = None
    while True:
        url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode({
            "search_query": query,
            "start": start,
            "max_results": page,
            "sortBy": "submittedDate",
            "sortOrder": "ascending",
        })
        root = ET.fromstring(fetch(url))
        if total is None:
            total_node = root.find("opensearch:totalResults", NS)
            total = int(total_node.text) if total_node is not None else 0
            print(f"daily window total {total}", flush=True)
        entries = root.findall("a:entry", NS)
        if not entries:
            break
        for entry in entries:
            row = parse_entry(entry)
            if "cs.RO" in row["categories"]:
                found.append(row)
        start += len(entries)
        if start >= (total or 0):
            break
        time.sleep(3.0)
    return found


def main() -> None:
    pages = int(sys.argv[1]) if len(sys.argv) > 1 else None
    harvest(pages)


if __name__ == "__main__":
    main()
