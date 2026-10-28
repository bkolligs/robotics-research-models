# Architecture trend survey with Jev

This survey is a separate analysis layer over the model-mention corpus. It asks
TypeSafe Jev to classify the substantive architecture topics described by each
paper's title and abstract, including papers that propose, analyze, evaluate, or
apply an architecture. It does **not** change the full-text mention matcher, the
tracked-model taxonomy, or any existing denominator.

The default population is the successfully scanned papers that name at least
one tracked robotics model. A paper's presence in this population still means
only that its full text names a model, possibly in the bibliography. It does not
prove that the paper used that model as a backbone.

## Decisions

Jev answers one primary-trend Choice and independent Noul questions for these
overlapping hypotheses:

- vision-language-action models
- world-action models
- agentic robotics
- world/dynamics models
- generative action policies (diffusion, flow, autoregressive)
- modular action experts and dual-stream/mixture-of-experts designs
- action representations, tokenization, chunking, and horizons
- hierarchical planning and control
- spatial and 3D reasoning
- cross-embodiment and generalist policies
- memory and retrieval
- multisensory and tactile models
- critics and verifiers
- runtime adaptation and recovery
- safety and alignment
- data scaling and pretraining
- data-efficient adaptation
- efficient deployment

The independent decisions make overlap explicit. A world-action model can also
be a VLA, use a generative action policy, and contain an action expert. Shares
therefore need not sum to 100%.

Jev is a typed decision model, not a text generator. `other_architecture`
identifies likely gaps in the taxonomy, but a person must inspect those papers
and name any newly emerging trend before adding another hypothesis.

## Run

Download the completed database as described in the README, set a TypeSafe API
key, inspect the exact first request, then run the resumable survey:

```bash
export TYPESAFE_API_KEY="..."
uv run mentions-survey --dry-run
uv run mentions-survey
```

The Jev model is pinned by default for reproducibility. Override it explicitly
with `--model` when evaluating a new release. Use `--limit` for an end-to-end
sample, `--since YYYY-MM` for a recent window, and `--population all-scanned`
to classify every successfully scanned cs.RO paper instead of the model-paper
population.

Raw decisions and probabilities checkpoint to the ignored
`data/architecture-survey/jev.jsonl`. Compatible rows are reused on restart.
Changing the question set or requested model creates a new logical run within
that append-only file. Aggregates are written to:

- `output/architecture-survey/summary.json`
- `output/architecture-survey/monthly.csv`

When those files exist, `scripts/build_analysis_site.py` copies them into the
GitHub Pages artifact. The website adds an interactive multi-line trend chart.
It is intentionally not stacked because classifications overlap, and readers
can switch between all surveyed model papers and trend-positive papers
as the monthly denominator. If no completed survey output is present, the site
build succeeds and hides the chart.

The summary records the database hash, question-set hash, returned Jev model,
token usage, decision threshold, examples, and limitations. Threshold changes
only require re-aggregation of the saved probabilities, not new API calls.

## Interpretation

The title and abstract are appropriate evidence for the paper's stated primary
contribution, but they can omit implementation details found in the body. Treat
the probabilities as survey judgments and validate a stratified sample before
publishing conclusions. In particular, review:

1. high-probability `other_architecture` papers;
2. low-confidence primary choices;
3. papers near the selected Noul threshold; and
4. a random sample of positives and negatives for each major trend.
