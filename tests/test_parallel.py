import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from mentions.parallel_pipeline import construct_manifest, process_archive, merge, write_rows
from mentions.pdf_store import ManifestChunk, PdfStoreError
from mentions.selective_store import save_json


class ParallelTests(TestCase):
    def test_manifest_barrier_metadata_paths_and_merge(self):
        with TemporaryDirectory() as tmp, patch.dict(os.environ, MENTIONS_DATA=tmp, MENTIONS_OUTPUT=tmp+'/output'):
            root = Path(tmp)
            record = dict(id='2301.00001', title='Example', summary='abstract', published='2023-01-01', month='2023-01', version='v1', primary='cs.RO', categories=['cs.RO'])
            write_rows(root/'records.jsonl', [record])
            chunk = ManifestChunk('pdf/test.tar', '2301', 'md5', 3000, '', '', 1)
            with self.assertRaises(PdfStoreError):
                construct_manifest(root, [chunk])
            save_json(root/'indexes/test.tar.json', dict(key=chunk.filename, manifest_md5='md5', manifest_size=3000, size=4096, etag='etag', entries=[dict(id=record['id'], offset=512, size=3000)], receipts={}))
            result = construct_manifest(root, [chunk])
            row = json.loads((root/'paper_manifest.jsonl').read_text())
            self.assertEqual(row['title'], 'Example')
            self.assertEqual(row['full_text_path'], 'text/2301.00001.txt')
            self.assertEqual(row['location']['byte_offset'], 512)
            with self.assertRaises(FileNotFoundError):
                merge(root, result['run_id'])
            (root/'pdf').mkdir()
            (root/'pdf/2301.00001.pdf').write_bytes(b'%PDF')
            hit = dict(id=record['id'], month=record['month'], primary='cs.RO', source='arxiv_bulk_pdf', variants=[], abstract_variants=[])
            with patch('mentions.parallel_pipeline.fetch_chunk', return_value={}), patch('mentions.parallel_pipeline.scan_record', return_value=hit):
                process_archive(root, result['run_id'], chunk)
            self.assertEqual(merge(root, result['run_id'])['scanned'], 1)
            import sqlite3
            with sqlite3.connect(root/'papers.sqlite') as db:
                self.assertEqual(db.execute('select full_text_path,status from paper_index').fetchone(), ('text/2301.00001.txt', 'complete'))
            original = (root/'papers.sqlite').read_bytes()
            rerun = merge(root, result['run_id'])
            self.assertEqual((Path(rerun['generation'])/'previous/papers.sqlite').read_bytes(), original)
            before_failure = (root/'papers.sqlite').read_bytes()
            shard = root/'runs'/result['run_id']/'shards/test.tar.hits.jsonl'
            shard.write_text('')
            with self.assertRaises(ValueError):
                merge(root, result['run_id'])
            self.assertEqual((root/'papers.sqlite').read_bytes(), before_failure)
