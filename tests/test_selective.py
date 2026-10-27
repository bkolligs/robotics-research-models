import io
import json
import tarfile
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from mentions.pdf_store import ManifestChunk, PdfStoreError
from mentions.selective_store import fetch_chunk, S3Ranges


class FakeS3:
    def __init__(self, payload):
        self.payload = payload
        self.ranges = []

    def head_object(self, **kwargs):
        return {'ContentLength': len(self.payload), 'ETag': 'etag'}

    def get_object(self, **kwargs):
        assert kwargs['RequestPayer'] == 'requester'
        assert kwargs['IfMatch'] == 'etag'
        start, end = map(int, kwargs['Range'][6:].split('-'))
        self.ranges.append((start, end))
        return {'Body': io.BytesIO(self.payload[start:end + 1]), 'ETag': 'etag',
                'ContentRange': f'bytes {start}-{end}/{len(self.payload)}',
                'ResponseMetadata': {'HTTPStatusCode': 206}}


class SelectiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        buf = io.BytesIO()
        self.pdf = b'%PDF-1.4\n' + b'paper' * 600
        with tarfile.open(fileobj=buf, mode='w', format=tarfile.PAX_FORMAT) as archive:
            for name, data in [('2301/2301.00001.pdf', b'ignored' * 100000),
                               ('long/' * 30 + '2301.00002.pdf', self.pdf),
                               ('../2301.00003.pdf', self.pdf)]:
                member = tarfile.TarInfo(name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        self.client = FakeS3(buf.getvalue())
        self.chunk = ManifestChunk('pdf/test.tar', '2301', 'md5', len(buf.getvalue()), '', '', 3)
        mock = patch('mentions.selective_store._client', return_value=self.client)
        mock.start()
        self.addCleanup(mock.stop)

    def test_selective_bytes_and_zero_network_resume(self):
        result = fetch_chunk(self.chunk, {'2301.00002', '2301.00003'}, self.root)
        self.assertEqual(result['written_pdfs'], 1)
        self.assertLess(result['bytes_received'], 15000)
        self.assertEqual((self.root / 'pdf/2301.00002.pdf').read_bytes(), self.pdf)
        self.assertFalse((self.root / 'pdf/2301.00003.pdf').exists())
        self.client.ranges.clear()
        result = fetch_chunk(self.chunk, {'2301.00002'}, self.root)
        self.assertEqual(result['reused_pdfs'], 1)
        self.assertEqual(self.client.ranges, [])

    def test_overwrite_redownloads_and_corruption_is_repaired(self):
        fetch_chunk(self.chunk, {'2301.00002'}, self.root)
        result = fetch_chunk(self.chunk, {'2301.00002'}, self.root, overwrite=True)
        self.assertEqual(result['downloaded_pdfs'], 1)
        dest = self.root / 'pdf/2301.00002.pdf'
        dest.write_bytes(b'x' * len(self.pdf))
        result = fetch_chunk(self.chunk, {'2301.00002'}, self.root)
        self.assertEqual(result['written_pdfs'], 1)
        self.assertEqual(dest.read_bytes(), self.pdf)

    def test_changed_archive_preserves_identical_pdf_mtime(self):
        fetch_chunk(self.chunk, {'2301.00002'}, self.root)
        dest = self.root / 'pdf/2301.00002.pdf'
        stamp = dest.stat().st_mtime_ns
        result = fetch_chunk(replace(self.chunk, md5sum='changed'), {'2301.00002'}, self.root)
        self.assertEqual(result['identical_pdfs'], 1)
        self.assertEqual(dest.stat().st_mtime_ns, stamp)

    def test_adding_ids_to_cached_index(self):
        fetch_chunk(self.chunk, set(), self.root)
        result = fetch_chunk(self.chunk, {'2301.00002'}, self.root)
        self.assertEqual(result['written_pdfs'], 1)
        self.assertLess(result['bytes_received'], 4000)

    def test_server_ignoring_range_is_rejected_without_reading_payload(self):
        reader = S3Ranges(self.client, 'pdf/test.tar', len(self.client.payload), 'etag')
        response = self.client.get_object(Range='bytes=0-511', RequestPayer='requester', IfMatch='etag')
        response['ResponseMetadata']['HTTPStatusCode'] = 200
        with patch.object(self.client, 'get_object', return_value=response):
            with self.assertRaises(PdfStoreError):
                reader.read(512)
        self.assertTrue(response['Body'].closed)

    def test_manifest_size_excludes_tar_padding(self):
        result = fetch_chunk(replace(self.chunk, size=700000), {'2301.00002'}, self.root)
        self.assertEqual(result['written_pdfs'], 1)
        result = fetch_chunk(replace(self.chunk, size=700000), {'2301.00002'}, self.root)
        self.assertEqual(result['bytes_received'], 0)

    def test_unbounded_read_is_rejected(self):
        with self.assertRaises(PdfStoreError):
            S3Ranges(self.client, 'key', len(self.client.payload), 'etag').read()
