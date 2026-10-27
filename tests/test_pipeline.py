"""Regression tests for paper-presence denominators and resumable scans."""
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from mentions import build_site, export_corpus, scan
from mentions.harvest import harvest_windows


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        env = patch.dict(os.environ, {"MENTIONS_DATA": str(self.root),
                                     "MENTIONS_OUTPUT": str(self.root / "output")})
        env.start()
        self.addCleanup(env.stop)
        self.row = dict(id="2301.00001", version="2301.00001v1", month="2023-01",
                        primary="cs.RO", categories=["cs.RO"], title="Paper",
                        summary="Abstract", published="2023-01-01T00:00:00Z")
        (self.root / "records.jsonl").write_text(json.dumps(self.row) + "\n")

    def write_hits(self, hits):
        (self.root / "hits.jsonl").write_text(''.join(json.dumps(h) + '\n' for h in hits))

    def test_retry_failed_scan_and_keep_one_row(self):
        with patch.object(scan, 'pdftotext_bin', return_value='/bin/pdftotext'):
            scan.scan()
            self.assertEqual(scan.load_hits()[self.row['id']]['source'], 'failed')
            (self.root / 'pdf').mkdir()
            (self.root / 'pdf' / '2301.00001.pdf').write_bytes(b'%PDF')
            with patch.object(scan, 'load_paper_text', return_value='OpenVLA') as load:
                scan.scan()
                scan.scan()
                self.assertEqual(load.call_count, 1)
            hits = scan.load_hits()
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[self.row['id']]['source'], 'arxiv_bulk_pdf')

    def test_changed_rules_rescan_cached_success(self):
        (self.root / 'pdf').mkdir()
        (self.root / 'pdf' / '2301.00001.pdf').write_bytes(b'%PDF')
        with patch.object(scan, 'pdftotext_bin'), patch.object(scan, 'load_paper_text', return_value='OpenVLA') as load:
            scan.scan()
            with patch.object(scan, 'scan_fingerprint', return_value='changed'):
                scan.scan()
            self.assertEqual(load.call_count, 2)

    def test_failure_excluded_from_corpus_and_site(self):
        hit = dict(id=self.row['id'], month='2023-01', primary='cs.RO', source='failed', variants=[])
        self.write_hits([hit])
        self.assertEqual(export_corpus.paper_rows(), [])
        papers = build_site.papers_from_scan()
        self.assertEqual(build_site.summarize(papers)['papers_scanned'], 0)

    def test_family_is_counted_once_and_discovered_includes_pending(self):
        from mentions.match import FAMILY_OF
        family = next(f for f in FAMILY_OF.values() if list(FAMILY_OF.values()).count(f) > 1)
        variants = [v for v, f in FAMILY_OF.items() if f == family][:2]
        self.write_hits([dict(id=self.row['id'], month='2023-01', source='arxiv_bulk_pdf', variants=variants)])
        with (self.root / 'records.jsonl').open('a') as out:
            out.write(json.dumps(dict(self.row, id='2301.00002')) + '\n')
        scan.summarize()
        summary = json.loads((self.root / 'output/summary.json').read_text())
        self.assertEqual(dict(summary['family_paper_hits'])[family], 1)
        self.assertEqual(summary['papers_discovered'], 2)
        self.assertEqual(summary['papers_pending'], 1)
        self.assertEqual(summary['papers_scanned'], 1)

    def test_available_only_does_not_freeze_missing_pdfs(self):
        with patch.object(scan, 'pdftotext_bin'):
            scan.scan(available_only=True)
        self.assertEqual(scan.load_hits(), {})

    def test_text_cache_tracks_pdf_content_stamp(self):
        (self.root / 'pdf').mkdir()
        pdf = self.root / 'pdf' / '2301.00001.pdf'
        pdf.write_bytes(b'%PDF first')
        with patch.object(scan, 'pdf_to_text', return_value='body ' * 600) as extract:
            scan.load_paper_text(self.row['id'])
            scan.load_paper_text(self.row['id'])
            self.assertEqual(extract.call_count, 1)
            pdf.write_bytes(b'%PDF changed and longer')
            scan.load_paper_text(self.row['id'])
            self.assertEqual(extract.call_count, 2)

    def test_pipeline_picks_up_records_added_during_download(self):
        from mentions import pipeline
        batches = []

        def fetch(ids, *args, **kwargs):
            batches.append(ids)
            if len(batches) == 1:
                with (self.root / 'records.jsonl').open('a') as out:
                    out.write(json.dumps(dict(self.row, id='2301.00002')) + '\n')
            return {"chunks": 1}

        with patch('sys.argv', ['mentions-pipeline', '--skip-harvest']), \
             patch.object(pipeline, 'pdftotext_bin'), \
             patch.object(pipeline, 'scan'), patch.object(pipeline, 'summarize'), \
             patch.object(pipeline, 'export_main'), \
             patch.object(pipeline, 'fetch_pdfs', side_effect=fetch):
            pipeline.main()
        self.assertEqual(batches, [{'2301.00001'}, {'2301.00001', '2301.00002'}])

    def test_harvest_windows_are_contiguous_calendar_months(self):
        windows = harvest_windows()
        self.assertEqual(windows[0], ('202301010000', '202301312359'))
        self.assertIn(('202402010000', '202402292359'), windows)
        self.assertTrue(all(start[:6] == end[:6] for start, end in windows))


if __name__ == '__main__':
    unittest.main()
