# Frontier LLM mentions and usage

This chart is separate from the robotics-model mention taxonomy and its
denominators. It currently tracks three released frontier models:

- GPT-6 Astra
- Claude Fable 5
- Claude Fable 5.1

Each release has its own row. The scanner accepts qualified spelling variants
such as `GPT-6-Astra` and `Fable 5.1`. It deliberately rejects bare `Astra`,
which is also the name of unrelated robotics systems, and bare `fable`, which
is ordinary prose.

## Two measurements

**Mention** is deterministic paper presence. A qualified name appears at least
once in the extracted full text. The bibliography is included, so a mention is
not evidence of use.

**Usage** is a TypeSafe Jev decision for each paper/model pair found by the
full-text pass. Jev receives the paper title, abstract, and up to eight sampled
contexts around the name. A paper counts as usage when Jev assigns at least
0.5 probability that the authors actively ran, integrated, or directly
evaluated the named model in their method, robot system, data generation, or
experiments. Background discussion, related work, bibliography entries,
reported results from another paper, future work, and authoring disclosures do
not count as usage.

The sampled contexts span the paper rather than taking only the first hits, so
method evidence and bibliography evidence can both be represented. The raw
candidate contexts and Jev responses remain local under `data/llm-survey/` for
audit; the website receives only aggregate counts and provenance.

## Denominator

Both lines use successfully scanned `cs.RO` papers in the month as their
denominator. A paper counts once per released LLM per month. Papers can name or
use more than one LLM, so model shares can overlap.

The month is the paper's first-submission month, while the scan reads the latest
available full-text revision. There is no release-date gate. A later revision
can therefore add a newly released model to a paper whose chart month is earlier
than the model release.

This chart does not claim that a used LLM is the paper's backbone. “Usage” also
includes direct evaluation and data generation, which are recorded as separate
Jev roles in the aggregate output.

## Reproduce

Extract candidates against the same persistent full-text cache used by the
model-mention study, download the small result, then run Jev:

```bash
MENTIONS_MODAL_VOLUME=robotics-research-papers uv run --no-sync modal run scripts/modal_llm_candidates.py
uv run --no-sync modal volume get robotics-research-papers /llm-survey/candidates.jsonl data/llm-survey/candidates.jsonl --force
uv run mentions-llm-survey
```

`TYPESAFE_API_KEY` must be present in the environment for the final command.
The JSONL checkpoint makes repeated runs resume rather than reclassify unchanged
paper/model evidence.
