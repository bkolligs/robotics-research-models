"""The full-text path keeps the bibliography and refuses a short extract."""

from __future__ import annotations

import io
import tarfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from mentions.pdf_store import extract_wanted, parse_manifest, yymm_of, fetch_pdfs
from mentions.pdf_text import MIN_CHARS, PdfTextError, pdf_to_text


MANIFEST = b"""<?xml version='1.0' standalone='yes'?>
<arXivPDF>
  <file>
    <filename>pdf/arXiv_pdf_2301_001.tar</filename>
    <yymm>2301</yymm>
    <md5sum>abc</md5sum>
    <size>10</size>
    <first_item>2301.00001</first_item>
    <last_item>2301.00999</last_item>
    <num_items>2</num_items>
  </file>
  <file>
    <filename>pdf/arXiv_pdf_2401_001.tar</filename>
    <yymm>2401</yymm>
    <md5sum>def</md5sum>
    <size>10</size>
    <first_item>2401.00001</first_item>
    <last_item>2401.00002</last_item>
    <num_items>1</num_items>
  </file>
</arXivPDF>
"""


class PdfStoreTests(unittest.TestCase):
    def test_manifest_month_filter_uses_the_id_prefix(self):
        chunks = parse_manifest(MANIFEST)
        self.assertEqual(yymm_of("2301.04446"), "2301")
        self.assertIsNone(yymm_of("cs/0001001"))
        months = {yymm_of("2301.04446")}
        picked = [chunk.filename for chunk in chunks if chunk.yymm in months]
        self.assertEqual(picked, ["pdf/arXiv_pdf_2301_001.tar"])

    def test_extract_keeps_only_wanted_ids(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            tar_path = root / "chunk.tar"
            with tarfile.open(tar_path, "w") as archive:
                for name, payload in (
                    ("2301.00001.pdf", b"%PDF wanted"),
                    ("2301.00002.pdf", b"%PDF other"),
                    ("../2301.00003.pdf", b"%PDF bad"),
                ):
                    info = tarfile.TarInfo(name)
                    info.size = len(payload)
                    archive.addfile(info, io.BytesIO(payload))
            pdf_dir = root / "pdf"
            written = extract_wanted(tar_path, {"2301.00001"}, pdf_dir)
            self.assertEqual(written, 1)
            self.assertEqual((pdf_dir / "2301.00001.pdf").read_bytes(), b"%PDF wanted")
            self.assertFalse((pdf_dir / "2301.00002.pdf").exists())
            self.assertFalse((pdf_dir / "2301.00003.pdf").exists())

    def test_empty_cached_pdf_is_downloaded_and_checkpointed(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf_dir = root / "pdf"
            pdf_dir.mkdir()
            (pdf_dir / "2301.00001.pdf").touch()
            chunks = parse_manifest(MANIFEST)[:1]
            client = Mock()

            def download(bucket, key, dest, **kwargs):
                self.assertEqual(kwargs["ExtraArgs"], {"RequestPayer": "requester"})
                with tarfile.open(dest, "w") as archive:
                    payload = b"%PDF restored"
                    info = tarfile.TarInfo("2301/2301.00001.pdf")
                    info.size = len(payload)
                    archive.addfile(info, io.BytesIO(payload))

            client.download_file.side_effect = download
            checkpoint = Mock()
            with patch('mentions.pdf_store._client', return_value=client), \
                 patch('mentions.pdf_store.download_manifest', return_value=chunks), \
                 patch('mentions.pdf_store._md5', return_value='abc'):
                counts = fetch_pdfs({'2301.00001'}, pdf_dir, root / 'manifest.xml',
                                    root / 'tar', on_chunk=checkpoint)
            self.assertEqual(counts['extracted'], 1)
            self.assertEqual(counts['not_in_manifest'], 0)
            self.assertEqual(counts['already_present'], 0)
            checkpoint.assert_called_once()
            self.assertEqual(list((root / 'tar').glob('*.tar')), [])



class PdfTextTests(unittest.TestCase):
    def test_short_extract_is_a_failure(self):
        with TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "short.pdf"
            # A tiny valid-enough stream is not required: pdftotext returns
            # an error or a short string, and either one must not count.
            pdf.write_bytes(b"%PDF-1.1\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n")
            with self.assertRaises(PdfTextError):
                pdf_to_text(pdf)

    def test_a_real_pdf_keeps_the_reference_section(self):
        sample = Path("/usr/share/doc/poppler-utils")
        pdfs = list(sample.glob("*.pdf")) if sample.exists() else []
        if not pdfs:
            self.skipTest("no sample pdf")
        text = pdf_to_text(pdfs[0]) if len(pdfs[0].read_bytes()) else ""
        if len(text) < MIN_CHARS:
            self.skipTest("sample pdf is shorter than a paper body")
        self.assertIn("\n", text)


if __name__ == "__main__":
    unittest.main()
