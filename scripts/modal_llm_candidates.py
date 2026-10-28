"""Extract qualified LLM hit contexts from cached full text on Modal."""

from pathlib import Path
import os

import modal


ROOT = Path(__file__).resolve().parents[1]
app = modal.App(os.environ.get("MENTIONS_MODAL_APP", "paper-pipeline") + "-llm-survey")
volume = modal.Volume.from_name(
    os.environ.get("MENTIONS_MODAL_VOLUME", "papers"), create_if_missing=False
)
image = modal.Image.debian_slim(python_version="3.12").add_local_python_source("mentions")


@app.function(
    image=image, volumes={"/papers": volume}, cpu=1, memory=2048,
    timeout=3600, max_containers=10,
)
def extract_bucket(bucket: int, buckets: int):
    from mentions.llm_survey import scan_candidates

    volume.reload()
    result = scan_candidates(
        Path("/papers"),
        Path("/papers/paper_index.jsonl"),
        Path(f"/papers/llm-survey/shards/candidates-{bucket:02d}.jsonl"),
        bucket=bucket,
        buckets=buckets,
    )
    volume.commit()
    return result


@app.function(image=image, volumes={"/papers": volume}, cpu=1, memory=2048, timeout=600)
def merge(buckets: int):
    import json

    volume.reload()
    rows = []
    for bucket in range(buckets):
        path = Path(f"/papers/llm-survey/shards/candidates-{bucket:02d}.jsonl")
        if not path.is_file():
            raise FileNotFoundError(path)
        rows.extend(json.loads(line) for line in path.read_text().splitlines() if line.strip())
    rows.sort(key=lambda row: (row["paper_id"], row["model_id"]))
    destination = Path("/papers/llm-survey/candidates.jsonl")
    temporary = destination.with_suffix(".jsonl.part")
    temporary.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    temporary.replace(destination)
    volume.commit()
    return {"paper_model_candidates": len(rows), "output": str(destination)}


@app.local_entrypoint()
def main(buckets: int = 10):
    from concurrent.futures import ThreadPoolExecutor

    if not 1 <= buckets <= 10:
        raise ValueError("buckets must be between 1 and 10")
    with ThreadPoolExecutor(max_workers=buckets) as pool:
        futures = [pool.submit(extract_bucket.remote, bucket, buckets) for bucket in range(buckets)]
        for future in futures:
            print(future.result(), flush=True)
    print(merge.remote(buckets), flush=True)
