import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from mentions.catalog import merge_month, previous_month


def database(path, rows):
    with sqlite3.connect(path) as db:
        db.executescript('''CREATE TABLE paper_index (id TEXT PRIMARY KEY,published TEXT,status TEXT,metadata TEXT);
        CREATE TABLE papers (id TEXT PRIMARY KEY,month TEXT);
        CREATE TABLE mentions (paper_id TEXT,variant_id TEXT,PRIMARY KEY(paper_id,variant_id));''')
        for pid, month, complete in rows:
            metadata = dict(id=pid, published=month+'-01T00:00:00Z', month=month, categories=['cs.RO'])
            db.execute('INSERT INTO paper_index VALUES (?,?,?,?)', (pid,metadata['published'],'complete' if complete else 'missing_from_snapshot',json.dumps(metadata)))
            if complete:
                db.execute('INSERT INTO papers VALUES (?,?)', (pid,month))
                db.execute('INSERT INTO mentions VALUES (?,?)', (pid,'openvla'))


class CatalogTests(unittest.TestCase):
    def test_previous_month_across_year_and_leap_boundaries(self):
        self.assertEqual(previous_month(date(2027,1,1)), '2026-12')
        self.assertEqual(previous_month(date(2024,3,1)), '2024-02')
        self.assertEqual(previous_month(date(2026,11,18)), '2026-10')

    def test_month_replacement_preserves_history_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            base, incoming, out, again = [Path(directory)/x for x in ('base.db','month.db','out.db','again.db')]
            database(base, [('old','2026-09',True),('new','2026-10',False)])
            database(incoming, [('new','2026-10',True),('missing','2026-10',False)])
            merge_month(base,incoming,out,'2026-10','october-volume')
            merge_month(out,incoming,again,'2026-10','october-volume')
            with sqlite3.connect(again) as db:
                self.assertEqual(db.execute('SELECT id FROM papers ORDER BY id').fetchall(), [('new',),('old',)])
                self.assertEqual(db.execute('SELECT COUNT(*) FROM mentions').fetchone()[0], 2)
                self.assertEqual(db.execute('SELECT modal_volume FROM catalog_sources WHERE paper_id="new"').fetchone()[0], 'october-volume')
            with self.assertRaises(ValueError):
                merge_month(base,incoming,out,'2026-09','october-volume')

    def test_refuses_regression_and_keeps_output_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            base,incoming,out = [Path(directory)/x for x in ('base.db','month.db','out.db')]
            database(base, [('kept','2026-10',True)])
            database(incoming, [('different','2026-10',True)])
            out.write_bytes(b'previous valid output')
            with self.assertRaises(ValueError):
                merge_month(base,incoming,out,'2026-10','october-volume')
            self.assertEqual(out.read_bytes(), b'previous valid output')
