import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from mentions.harvest import harvest


def record(pid='2610.00001', date='Thu, 01 Oct 2026 12:00:00 GMT', categories='cs.LG cs.RO'):
    return f'''<record><header><identifier>oai:arXiv.org:{pid}</identifier><datestamp>2026-11-01</datestamp></header>
    <metadata><arXivRaw xmlns="http://arxiv.org/OAI/arXivRaw/"><id>{pid}</id>
    <version version="v2"><date>Sun, 01 Nov 2026 12:00:00 GMT</date></version>
    <version version="v1"><date>{date}</date></version><categories>{categories}</categories>
    <title>A robot</title><abstract>Body</abstract></arXivRaw></metadata></record>'''


def page(records='', token='', error=''):
    content = f'<error code="{error}" />' if error else f'<ListRecords>{records}<resumptionToken>{token}</resumptionToken></ListRecords>'
    return f'<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><responseDate>2026-11-18T12:00:00Z</responseDate>{content}</OAI-PMH>'.encode()


class HarvestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for mock in [patch('mentions.harvest.data_dir', return_value=self.root), patch('mentions.harvest.time.sleep')]:
            mock.start()
            self.addCleanup(mock.stop)

    def rows(self):
        return [json.loads(line) for line in (self.root/'records.jsonl').read_text().splitlines()]

    def test_month_uses_v1_not_update_date_and_continuations_use_only_token(self):
        with patch('mentions.harvest.fetch', side_effect=[page(record(), 'next'), page(record('2609.00001', 'Tue, 01 Sep 2026 12:00:00 GMT'))]) as fetch:
            harvest(month='2026-10')
        self.assertEqual([r['id'] for r in self.rows()], ['2610.00001'])
        self.assertEqual(self.rows()[0]['version'], '2610.00001v2')
        self.assertEqual(self.rows()[0]['primary'], 'cs.LG')
        first = parse_qs(urlsplit(fetch.call_args_list[0].args[0]).query)
        self.assertEqual(first['set'], ['cs:cs:RO'])
        self.assertNotIn('from', first)
        self.assertEqual(parse_qs(urlsplit(fetch.call_args_list[1].args[0]).query), {'verb':['ListRecords'], 'resumptionToken':['next']})

    def test_incremental_deletion_and_no_records(self):
        with patch('mentions.harvest.fetch', return_value=page(record())):
            harvest()
        deleted = '<record><header status="deleted"><identifier>oai:arXiv.org:2610.00001</identifier></header></record>'
        with patch('mentions.harvest.fetch', return_value=page(deleted)) as fetch:
            harvest()
        self.assertIn('from=2026-11-18', fetch.call_args.args[0])
        self.assertEqual(self.rows(), [])
        with patch('mentions.harvest.fetch', return_value=page(error='noRecordsMatch')):
            harvest()
        self.assertEqual(self.rows(), [])

    def test_failed_page_does_not_advance_watermark_or_export_partial_data(self):
        with patch('mentions.harvest.fetch', side_effect=[page(record(), 'next'), RuntimeError('offline')]):
            with self.assertRaises(RuntimeError):
                harvest()
        self.assertFalse((self.root/'records.jsonl').exists())
        with sqlite3.connect(self.root/'oai.sqlite') as db:
            state = dict(db.execute('SELECT key,value FROM state'))
        self.assertEqual(state['token'], 'next')
        self.assertNotIn('completed_from', state)
        with patch('mentions.harvest.fetch', side_effect=[page(error='badResumptionToken'), page(record())]) as fetch:
            harvest()
        self.assertIn('resumptionToken=next', fetch.call_args_list[0].args[0])
        self.assertNotIn('resumptionToken', fetch.call_args_list[1].args[0])
        self.assertEqual(len(self.rows()), 1)

    def test_invalid_month_and_malformed_response_fail(self):
        for month in ['2026-13', '../../bad', '2022-01']:
            with self.assertRaises(ValueError):
                harvest(month=month)
        with patch('mentions.harvest.fetch', return_value=b'<feed/>'):
            with self.assertRaises(ValueError):
                harvest()
        with patch('mentions.harvest.fetch', return_value=page(error='badArgument')):
            with self.assertRaises(RuntimeError):
                harvest()
