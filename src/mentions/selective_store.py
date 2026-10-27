"""Read tar headers and selected PDFs through conditional S3 range requests.

Cached indexes are keyed by the manifest's archive checksum. Receipts hold
SHA-256 hashes of downloaded PDFs. Updates replace only changed PDF bytes.
This verifies ranges, tar header checksums and PDF receipts, not the whole-tar
MD5 (which would require transferring every byte).
"""
from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

from mentions.pdf_store import BUCKET, ManifestChunk, PdfStoreError, _client, _safe_member


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.json.part')
    tmp.write_text(json.dumps(value))
    tmp.replace(path)


class S3Ranges(io.RawIOBase):
    """Seek without transferring skipped payloads; pin reads to one ETag."""
    def __init__(self, client, key: str, size: int, etag: str):
        self.client, self.key, self.size, self.etag = client, key, size, etag
        self.position = 0
        self.bytes_read = 0
        self.requests = 0
        self.cache_start = -1
        self.cache = b''

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        pos = offset if whence == 0 else self.position + offset if whence == 1 else self.size + offset
        if pos < 0 or pos > self.size:
            raise PdfStoreError(f'Seek outside archive: {pos}/{self.size}')
        self.position = pos
        return pos

    def read(self, size=-1):
        if size < 0:
            raise PdfStoreError('Unbounded S3 reads are forbidden')
        size = min(size, self.size - self.position)
        if size == 0:
            return b''
        offset = self.position - self.cache_start
        if not (0 <= offset and offset + size <= len(self.cache)):
            start = self.position
            end = min(self.size, start + max(size, 512)) - 1
            r = self.client.get_object(Bucket=BUCKET, Key=self.key,
                RequestPayer='requester', Range=f'bytes={start}-{end}', IfMatch=self.etag)
            body = r['Body']
            try:
                if (r['ResponseMetadata']['HTTPStatusCode'] != 206
                        or r.get('ContentRange') != f'bytes {start}-{end}/{self.size}'
                        or r.get('ETag') != self.etag):
                    raise PdfStoreError('S3 did not return the requested pinned byte range')
                data = body.read(end - start + 2)
                if len(data) != end - start + 1:
                    raise PdfStoreError('Truncated or oversized S3 range')
            finally:
                body.close()
            self.requests += 1
            self.bytes_read += len(data)
            self.cache_start, self.cache = start, data
            offset = 0
        data = self.cache[offset:offset + size]
        self.position += len(data)
        return data


def _get_index(chunk: ManifestChunk, data: Path, *, require_index=False):
    index_path = data / 'indexes' / (Path(chunk.filename).name + '.json')
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    reader = None
    if (not chunk.md5sum or index.get('manifest_md5') != chunk.md5sum
            or index.get('manifest_size') != chunk.size or index.get('key') != chunk.filename):
        if require_index:
            raise PdfStoreError(f'Missing or stale index for {chunk.filename}; finish indexing first')
        client = _client()
        head = client.head_object(Bucket=BUCKET, Key=chunk.filename, RequestPayer='requester')
        # Manifest size is PDF payload bytes, excluding tar headers/padding.
        etag_md5 = head['ETag'].strip(chr(34))
        if len(etag_md5) == 32 and chunk.md5sum and etag_md5 != chunk.md5sum:
            raise PdfStoreError('Archive changed since manifest download; refresh manifest')
        reader = S3Ranges(client, chunk.filename, head['ContentLength'], head['ETag'])
        entries = []
        with tarfile.open(fileobj=reader, mode='r:') as archive:
            for member in archive:
                if member.isfile() and _safe_member(member.name):
                    entries.append({'id': Path(member.name).stem,
                                    'offset': member.offset_data, 'size': member.size})
        index = dict(key=chunk.filename, size=head['ContentLength'], manifest_size=chunk.size, manifest_md5=chunk.md5sum,
                     etag=head['ETag'], entries=entries, receipts={})
        save_json(index_path, index)
    return index_path, index, reader


def index_chunk(chunk: ManifestChunk, data: Path) -> dict:
    """Build just this archive's index, with no PDF downloads or shared outputs."""
    _, index, reader = _get_index(chunk, data)
    result = dict(archive=chunk.filename, entries=len(index['entries']),
                  reused=reader is None,
                  bytes_received=reader.bytes_read if reader else 0,
                  range_requests=reader.requests if reader else 0)
    print(json.dumps(result), flush=True)
    return result


def fetch_chunk(chunk: ManifestChunk, wanted: set[str], data: Path, *, overwrite=False,
                require_index=False) -> dict:
    """Fetch selected PDFs; require_index enforces the parallel stage barrier."""
    index_path, index, reader = _get_index(chunk, data, require_index=require_index)
    client = None
    pdf_dir = data / 'pdf'
    pdf_dir.mkdir(parents=True, exist_ok=True)
    result = dict(archive=chunk.filename, downloaded_pdfs=0, written_pdfs=0,
                  reused_pdfs=0, identical_pdfs=0, bytes_received=0, range_requests=0)
    try:
        for entry in index['entries']:
            paper_id = entry['id']
            if paper_id not in wanted:
                continue
            dest = pdf_dir / f'{paper_id}.pdf'
            receipt = index['receipts'].get(paper_id)
            if (not overwrite and receipt and dest.exists()
                    and dest.stat().st_size == entry['size'] and sha256(dest) == receipt):
                result['reused_pdfs'] += 1
                continue
            if reader is None:
                client = client or _client()
                reader = S3Ranges(client, chunk.filename, index['size'], index['etag'])
            reader.seek(entry['offset'])
            tmp = dest.with_suffix('.pdf.part')
            remaining = entry['size']
            digest = hashlib.sha256()
            try:
                with tmp.open('wb') as out:
                    while remaining:
                        block = reader.read(min(1024 * 1024, remaining))
                        if not block:
                            raise PdfStoreError('PDF payload ended early')
                        out.write(block)
                        digest.update(block)
                        remaining -= len(block)
                with tmp.open('rb') as check:
                    if b'%PDF-' not in check.read(1024):
                        raise PdfStoreError(f'{paper_id} is not a PDF')
                checksum = digest.hexdigest()
                result['downloaded_pdfs'] += 1
                if not overwrite and dest.exists() and sha256(dest) == checksum:
                    result['identical_pdfs'] += 1
                    tmp.unlink()
                else:
                    tmp.replace(dest)
                    result['written_pdfs'] += 1
                index['receipts'][paper_id] = checksum
                save_json(index_path, index)
            finally:
                tmp.unlink(missing_ok=True)
    finally:
        if reader:
            result['bytes_received'] = reader.bytes_read
            result['range_requests'] = reader.requests
    print(json.dumps(result), flush=True)
    return result


def fetch_pdfs(ids, pdf_dir, manifest_path, tar_dir=None, *, on_chunk=None,
               chunks=None, overwrite=False):
    """Compatible pipeline entry point; tar_dir is unused (no full archives)."""
    from mentions.pdf_store import download_manifest, yymm_of
    data = pdf_dir.parent
    months = {yymm_of(i) for i in ids}
    manifest = download_manifest(manifest_path) if chunks is None else chunks
    results = []
    for chunk in manifest:
        if chunk.yymm not in months:
            continue
        results.append(fetch_chunk(chunk, ids, data, overwrite=overwrite))
        if on_chunk:
            on_chunk()
    return {'chunks': len(results), 'extracted': sum(r['written_pdfs'] for r in results),
            'bytes_received': sum(r['bytes_received'] for r in results),
            'not_in_manifest': sum(not (pdf_dir / f'{i}.pdf').exists() for i in ids)}
