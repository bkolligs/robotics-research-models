"""Synchronize cs.RO metadata through arXiv's OAI-PMH bulk feed.

OAI datestamps describe metadata changes, not first submission. Bootstrap the
whole subject set, then incrementally synchronize it. Export the study window
(or one test month) using v1 submission dates from arXivRaw version history.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from mentions.paths import data_dir

ENDPOINT = 'https://oaipmh.arxiv.org/oai'
NS = {'o': 'http://www.openarchives.org/OAI/2.0/',
      'r': 'http://arxiv.org/OAI/arXivRaw/'}
USER_AGENT = 'robotics-research-models/0.1 (https://github.com/bkolligs/robotics-research-models)'


def fetch(url: str, tries: int = 6) -> bytes:
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
            with urllib.request.urlopen(req, timeout=90) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            delay = 30 * (attempt + 1)
            if isinstance(exc, urllib.error.HTTPError):
                if exc.code not in (429, 500, 502, 503, 504):
                    raise
                retry = exc.headers.get('Retry-After')
                if retry:
                    try:
                        delay = max(delay, int(retry))
                    except ValueError:
                        delay = max(delay, (parsedate_to_datetime(retry) - datetime.now(timezone.utc)).total_seconds())
            if attempt == tries - 1:
                raise RuntimeError(f'OAI request failed after {tries} attempts: {exc}') from exc
            print(f'OAI request failed; retry in {delay}s: {exc}', flush=True)
            time.sleep(delay)
    raise AssertionError('unreachable')


def parse_record(record: ET.Element) -> tuple[str, dict | None]:
    identifier = record.findtext('o:header/o:identifier', namespaces=NS)
    if not identifier or not identifier.startswith('oai:arXiv.org:'):
        raise ValueError('Missing arXiv OAI identifier')
    pid = identifier.removeprefix('oai:arXiv.org:')
    if record.find('o:header', NS).get('status') == 'deleted':
        return pid, None
    raw = record.find('o:metadata/r:arXivRaw', NS)
    if raw is None or raw.findtext('r:id', namespaces=NS) != pid:
        raise ValueError(f'Missing or inconsistent arXivRaw metadata: {pid}')
    versions = raw.findall('r:version', NS)
    versions.sort(key=lambda v: int(v.attrib['version'].removeprefix('v')))
    if not versions or versions[0].attrib['version'] != 'v1':
        raise ValueError(f'Missing original submission date: {pid}')
    published = parsedate_to_datetime(versions[0].findtext('r:date', namespaces=NS))
    stamp = published.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    categories = raw.findtext('r:categories', default='', namespaces=NS).split()
    if 'cs.RO' not in categories:
        return pid, None
    return pid, dict(id=pid, version=pid + versions[-1].attrib['version'],
                    published=stamp, month=stamp[:7], categories=categories,
                    primary=categories[0],
                    title=' '.join(raw.findtext('r:title', default='', namespaces=NS).split()),
                    summary=' '.join(raw.findtext('r:abstract', default='', namespaces=NS).split()))


def harvest(max_pages: int | None = None, month: str | None = None,
            checkpoint=None) -> None:
    if month is not None and (not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', month)
                              or not '2023-01' <= month <= datetime.now(timezone.utc).strftime('%Y-%m')):
        raise ValueError('month must be YYYY-MM within the study window')
    root = data_dir()
    db = sqlite3.connect(root / 'oai.sqlite')
    try:
        db.execute('CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        state = dict(db.execute('SELECT key,value FROM state'))
        pages, restarted = 0, False
        while True:
            params = {'verb': 'ListRecords'}
            if state.get('token'):
                params['resumptionToken'] = state['token']
            else:
                params.update(metadataPrefix='arXivRaw', set='cs:cs:RO')
                if state.get('completed_from'):
                    params['from'] = state['completed_from']
            response = ET.fromstring(fetch(ENDPOINT + '?' + urllib.parse.urlencode(params)))
            error = response.find('o:error', NS)
            if error is not None and error.get('code') == 'badResumptionToken' and not restarted:
                # Tokens expire daily. Replay from the last completed watermark;
                # upserts/deletes are idempotent and the watermark has not advanced.
                state.pop('token', None)
                state.pop('started', None)
                restarted = True
                time.sleep(3)
                continue
            if error is not None and error.get('code') != 'noRecordsMatch':
                raise RuntimeError(f'OAI {error.get("code")}: {error.text}')
            response_date = response.findtext('o:responseDate', namespaces=NS)
            if not response_date:
                raise ValueError('Missing OAI responseDate')
            state.setdefault('started', response_date[:10])
            listing = response.find('o:ListRecords', NS)
            if listing is None and error is None:
                raise ValueError('Missing OAI ListRecords response')
            records = [] if listing is None else listing.findall('o:record', NS)
            token = '' if listing is None else (listing.findtext('o:resumptionToken', default='', namespaces=NS) or '').strip()
            if token and not records:
                raise ValueError('Empty OAI page with continuation token')
            with db:
                for record in records:
                    pid, row = parse_record(record)
                    if row is None:
                        db.execute('DELETE FROM records WHERE id=?', (pid,))
                    else:
                        db.execute('INSERT OR REPLACE INTO records VALUES (?,?)', (pid, json.dumps(row)))
                if token:
                    state['token'] = token
                else:
                    # Inclusive overlap from the first response avoids missing
                    # updates during a multi-page harvest. Never use wall time.
                    state['completed_from'] = state.pop('started')
                    state.pop('token', None)
                db.execute('DELETE FROM state')
                db.executemany('INSERT INTO state VALUES (?,?)', state.items())
            pages += 1
            print(f'OAI page {pages}: {len(records)} records; cached {db.execute("SELECT COUNT(*) FROM records").fetchone()[0]}; more={bool(token)}', flush=True)
            if checkpoint:
                checkpoint()
            if not token:
                break
            if max_pages is not None and pages >= max_pages:
                raise RuntimeError('OAI page limit reached; cache saved, export withheld until sync completes')
            time.sleep(3)
        path = root / 'records.jsonl'
        temporary = path.with_suffix('.jsonl.part')
        count = 0
        with temporary.open('w') as handle:
            for (body,) in db.execute('SELECT body FROM records ORDER BY id'):
                row = json.loads(body)
                if row['published'] < '2023-01-01' or (month and row['month'] != month):
                    continue
                handle.write(body + '\n')
                count += 1
        temporary.replace(path)
        print(f'Exported {count} cs.RO papers' + (f' first submitted in {month}' if month else ''), flush=True)
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pages', nargs='?', type=int, help='Checkpoint and stop after this many pages')
    parser.add_argument('--month', help='Export one first-submission month after synchronizing the cache')
    args = parser.parse_args()
    harvest(args.pages, month=args.month)


if __name__ == '__main__':
    main()
