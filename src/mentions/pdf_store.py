"""Fetch the arXiv bulk PDFs and keep the ones this corpus needs.

Historical text comes from the requester-pays bucket documented at
https://info.arxiv.org/help/bulk_data_s3.html . That is the source the
Interconnects scanner calls `arxiv_bulk_pdf`. The caller pays the S3
transfer. Credentials are the normal AWS chain: env vars, a profile, or
an instance role.

Each month is packed into `pdf/arXiv_pdf_YYMM_NNN.tar`. The manifest lists
every chunk, its checksum, and the first and last paper id inside it. A
modern PDF is stored in the tar as `{id}.pdf`. The download keeps only the
ids in the harvested record list, verifies the tar checksum, and deletes
the tar. A second run skips a paper whose PDF is already on disk.
"""

from __future__ import annotations

import hashlib
import tarfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from collections.abc import Callable
from pathlib import Path

BUCKET = "arxiv"
MANIFEST_KEY = "pdf/arXiv_pdf_manifest.xml"
REGION = "us-east-1"


class PdfStoreError(RuntimeError):
    """The bulk PDF could not be fetched or verified."""


@dataclass(frozen=True)
class ManifestChunk:
    filename: str
    yymm: str
    md5sum: str
    size: int
    first_item: str
    last_item: str
    num_items: int


def yymm_of(arxiv_id: str) -> str | None:
    """The bulk-manifest month key for a modern arXiv id, or None."""
    head = arxiv_id.split("v", 1)[0]
    if len(head) < 4 or not head[:4].isdigit() or "." not in head:
        return None
    return head[:4]


def parse_manifest(xml_bytes: bytes) -> list[ManifestChunk]:
    root = ET.fromstring(xml_bytes)
    chunks = []
    for node in root.findall("file"):
        filename = _child(node, "filename")
        if not filename:
            continue
        chunks.append(ManifestChunk(
            filename=filename,
            yymm=_child(node, "yymm"),
            md5sum=_child(node, "md5sum"),
            size=int(_child(node, "size") or "0"),
            first_item=_child(node, "first_item"),
            last_item=_child(node, "last_item"),
            num_items=int(_child(node, "num_items") or "0"),
        ))
    return chunks


def chunks_for(chunks: list[ManifestChunk], yymms: set[str]) -> list[ManifestChunk]:
    return [chunk for chunk in chunks if chunk.yymm in yymms]


def member_name(arxiv_id: str) -> str:
    return f"{arxiv_id.split('v', 1)[0]}.pdf"


def _child(node: ET.Element, tag: str) -> str:
    found = node.find(tag)
    return (found.text or "").strip() if found is not None and found.text else ""


def _client():
    try:
        import boto3
    except ImportError as exc:
        raise PdfStoreError(
            "boto3 is not installed. Run `uv sync --group bulk` before fetching PDFs."
        ) from exc
    return boto3.client("s3", region_name=REGION)


def download_manifest(dest: Path) -> list[ManifestChunk]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    client = _client()
    try:
        client.download_file(
            BUCKET, MANIFEST_KEY, str(dest), ExtraArgs={"RequestPayer": "requester"}
        )
    except Exception as exc:
        raise PdfStoreError(
            "could not download s3://arxiv/pdf/arXiv_pdf_manifest.xml. "
            "Set AWS credentials for the requester-pays bucket."
        ) from exc
    return parse_manifest(dest.read_bytes())


def _md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_member(name: str) -> bool:
    path = Path(name)
    return not path.is_absolute() and ".." not in path.parts and path.name.endswith(".pdf")


def extract_wanted(tar_path: Path, wanted: set[str], pdf_dir: Path) -> int:
    """Copy wanted `{id}.pdf` members out of a verified tar. Returns the count."""
    pdf_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    with tarfile.open(tar_path, "r") as archive:
        for member in archive.getmembers():
            if not member.isfile() or not _safe_member(member.name):
                continue
            arxiv_id = Path(member.name).name
            if arxiv_id.endswith(".pdf"):
                arxiv_id = arxiv_id[:-4]
            if arxiv_id not in wanted:
                continue
            dest = pdf_dir / f"{arxiv_id}.pdf"
            if dest.exists() and dest.stat().st_size > 0:
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            tmp = dest.with_suffix(".pdf.part")
            with tmp.open("wb") as handle:
                while block := extracted.read(1024 * 1024):
                    handle.write(block)
            tmp.replace(dest)
            written += 1
    return written


def fetch_pdfs(ids: set[str], pdf_dir: Path, manifest_path: Path, tar_dir: Path,
               *, on_chunk: Callable[[], None] | None = None,
               chunks: list[ManifestChunk] | None = None) -> dict[str, int]:
    """Download the chunks that contain `ids` and keep those PDFs.

    Returns counts: downloaded chunks, extracted pdfs, already present,
    and ids the manifest does not cover. The last group is papers newer
    than the latest bulk snapshot.
    """
    needed = {arxiv_id for arxiv_id in ids if not (pdf_dir / f"{arxiv_id}.pdf").exists() or (pdf_dir / f"{arxiv_id}.pdf").stat().st_size == 0}
    present = len(ids) - len(needed)
    yymms = {yymm for arxiv_id in needed if (yymm := yymm_of(arxiv_id))}
    uncovered = {arxiv_id for arxiv_id in needed if yymm_of(arxiv_id) is None}
    if not yymms:
        return {
            "chunks": 0,
            "extracted": 0,
            "already_present": present,
            "not_in_manifest": len(uncovered),
        }

    chunks = chunks_for(download_manifest(manifest_path) if chunks is None else chunks, yymms)
    covered = set()
    client = _client()
    tar_dir.mkdir(parents=True, exist_ok=True)
    extracted = 0
    downloaded = 0
    for chunk in chunks:
        if not any(yymm_of(i) == chunk.yymm for i in needed - covered):
            continue
        tar_path = tar_dir / Path(chunk.filename).name
        print(f"fetch {chunk.filename} ({chunk.size} bytes)", flush=True)
        try:
            client.download_file(
                BUCKET, chunk.filename, str(tar_path), ExtraArgs={"RequestPayer": "requester"}
            )
        except Exception as exc:
            raise PdfStoreError(f"download failed for {chunk.filename}") from exc
        digest = _md5(tar_path)
        if chunk.md5sum and digest != chunk.md5sum:
            tar_path.unlink(missing_ok=True)
            raise PdfStoreError(
                f"checksum mismatch for {chunk.filename}: {digest} != {chunk.md5sum}"
            )
        downloaded += 1
        extracted += extract_wanted(tar_path, needed, pdf_dir)
        tar_path.unlink(missing_ok=True)
        # The manifest's first/last ids are not a reliable numeric range
        # for new-style ids, so coverage is what landed on disk.
        for arxiv_id in list(needed):
            if (pdf_dir / f"{arxiv_id}.pdf").exists() and (pdf_dir / f"{arxiv_id}.pdf").stat().st_size > 0:
                covered.add(arxiv_id)
        if on_chunk is not None:
            on_chunk()
    missing = needed - covered - uncovered
    return {
        "chunks": downloaded,
        "extracted": extracted,
        "already_present": present,
        "not_in_manifest": len(missing | uncovered),
    }
