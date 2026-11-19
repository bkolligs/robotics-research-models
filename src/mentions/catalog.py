"""Merge one validated submission month into a cumulative analysis catalog."""
import argparse
import json
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path


def previous_month(today=None):
    today = today or date.today()
    return (today.replace(day=1) - timedelta(days=1)).strftime('%Y-%m')


def merge_month(base, incoming, output, month, source_volume):
    if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', month):
        raise ValueError('month must be YYYY-MM')
    base, incoming, output = map(Path, (base, incoming, output))
    if not base.is_file() or not incoming.is_file():
        raise ValueError('Both source databases must exist')
    if output.resolve() in (base.resolve(), incoming.resolve()):
        raise ValueError('Output must differ from both source databases')
    with sqlite3.connect(f'file:{incoming.resolve()}?mode=ro', uri=True) as src:
        if src.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('Incoming database failed integrity check')
        indexed = src.execute('SELECT id,published,status,metadata FROM paper_index').fetchall()
        if not indexed or any(published[:7] != month for _, published, _, _ in indexed):
            raise ValueError('Incoming index must contain exactly the requested month')
        for pid, published, _, metadata in indexed:
            row = json.loads(metadata)
            if row['id'] != pid or row['published'] != published or row['month'] != month or 'cs.RO' not in row['categories']:
                raise ValueError('Incoming metadata does not match the requested cs.RO month')
        scanned = set(r[0] for r in src.execute('SELECT id FROM papers'))
        if not scanned or scanned != {pid for pid, _, status, _ in indexed if status == 'complete'}:
            raise ValueError('Incoming scanned/index records disagree or no PDFs were scanned')
        if src.execute('SELECT COUNT(*) FROM papers WHERE month != ?', (month,)).fetchone()[0]:
            raise ValueError('Incoming scanned papers contain another month')
        if src.execute('SELECT COUNT(*) FROM mentions WHERE paper_id NOT IN (SELECT id FROM papers)').fetchone()[0]:
            raise ValueError('Incoming mentions contain orphan papers')
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.sqlite.part')
    temporary.unlink(missing_ok=True)
    try:
        with sqlite3.connect(f'file:{base.resolve()}?mode=ro', uri=True) as src, sqlite3.connect(temporary) as dest:
            src.backup(dest)
        with sqlite3.connect(temporary) as db:
            if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise ValueError('Base database failed integrity check')
            db.execute('ATTACH DATABASE ? AS incoming', (str(incoming.resolve()),))
            for table in ('paper_index', 'papers', 'mentions'):
                if db.execute(f'PRAGMA main.table_info({table})').fetchall() != db.execute(f'PRAGMA incoming.table_info({table})').fetchall():
                    raise ValueError(f'Incompatible {table} schemas')
            old_scanned = {r[0] for r in db.execute('SELECT id FROM papers WHERE month=?', (month,))}
            if not old_scanned <= scanned:
                raise ValueError('Refusing to drop previously scanned papers from this month')
            collision = db.execute('SELECT COUNT(*) FROM main.paper_index b JOIN incoming.paper_index n USING(id) WHERE substr(b.published,1,7) != ?', (month,)).fetchone()[0]
            if collision:
                raise ValueError('Incoming IDs overlap a different historical month')
            db.execute('CREATE TABLE IF NOT EXISTS catalog_sources (paper_id TEXT PRIMARY KEY, modal_volume TEXT NOT NULL)')
            db.execute("INSERT OR IGNORE INTO catalog_sources SELECT id,'robotics-research-papers' FROM main.paper_index")
            with db:
                db.execute('DELETE FROM catalog_sources WHERE paper_id IN (SELECT id FROM main.paper_index WHERE substr(published,1,7)=?)', (month,))
                db.execute('DELETE FROM main.mentions WHERE paper_id IN (SELECT id FROM main.paper_index WHERE substr(published,1,7)=?)', (month,))
                db.execute('DELETE FROM main.papers WHERE month=?', (month,))
                db.execute('DELETE FROM main.paper_index WHERE substr(published,1,7)=?', (month,))
                for table in ('paper_index', 'papers', 'mentions'):
                    db.execute(f'INSERT INTO main.{table} SELECT * FROM incoming.{table}')
                db.execute('INSERT INTO catalog_sources SELECT id,? FROM incoming.paper_index', (source_volume,))
            if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise ValueError('Merged catalog failed integrity check')
        temporary.replace(output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return {'month': month, 'discovered': len(indexed), 'scanned': len(scanned), 'source_volume': source_volume}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--incoming', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--month', required=True)
    parser.add_argument('--source-volume', required=True)
    args = parser.parse_args()
    print(json.dumps(merge_month(args.base, args.incoming, args.output, args.month, args.source_volume)))


if __name__ == '__main__':
    main()
