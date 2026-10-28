# Experimental baselines and reported outcomes

This survey asks which tracked robotics model releases papers actually evaluate
as comparators, and how the paper's proposed method performs against each one.
The candidate population is all paper/model pairs in the existing full-text
mention corpus. The robotics mention matcher and its denominators are unchanged.

A baseline requires evidence that the authors run, reproduce, fine-tune, or
directly evaluate the existing model in their own experiments. A clearly named
adapted comparator qualifies. A citation, copied literature score, writing tool,
or model used only inside the proposed method does not qualify. A paper's own
new variant is not credited as an evaluation of the base release.

TypeSafe Jev receives the title, abstract, and up to 60,000 characters of PDF
text selected around tracked model names and experimental headings. Extraction
preserves newlines and table alignment. Overlapping windows are merged, and
windows with comparison and experimental terms receive priority when the budget
is exceeded. Bibliography passages may remain and are explicitly identified in
the instructions as insufficient evidence of baseline use. These are excerpts,
not a complete reading of the paper or its supplementary materials.

Each paper is classified once with separate questions for every mentioned model
release: a baseline-use probability and a comparative-outcome choice. The raw
responses, evidence fingerprints, policy hash, model version, token usage, and
candidate passages remain under ignored `data/evaluations/` for audit/resumption.
The public output contains aggregate counts and paper-level decisions with links
to the source papers; it does not publish full extracted paper text.

Accepted evaluations receive a separate execution-provenance check. Jev must
distinguish authors' own runs from copied published scores, component-only use,
and unspecified provenance. Only `own_runs` with at least 0.7 selected-choice
probability qualifies. A table entry by itself is insufficient. Source review
found this extra gate necessary because tables can mix author-run and published
results. Exact-release distinctions are also enforced: On-Device experiments
cannot be credited to the original Gemini Robotics release.

The main classification and provenance pass cover the full candidate corpus.
A more explicit Gemini release recheck stopped on a TypeSafe HTTP 402 response.
Its 37 affected paper checks remain pending and are excluded as uncertain unless
resolved by the recorded source-text review.

## Outcomes

- **Paper beats baseline:** model-specific evidence establishes that the proposed
  method outperforms the baseline on the principal reported evaluation.
- **Mixed results:** wins and losses across tasks or principal metrics, or an
  explicit performance/efficiency tradeoff, prevent an overall winner.
- **Comparable / tied:** explicitly reported comparable or tied performance.
- **Baseline wins:** the baseline outperforms the proposed method on the principal
  reported evaluation.
- **Outcome unclear:** baseline use is established but the direction is uncertain,
  results are omitted, or the extracted table cannot be interpreted reliably.
- **Evaluation only:** the paper directly evaluates the model but proposes no new
  method to compare against it.

A baseline probability of at least 0.7 is required for inclusion. Intermediate
baseline probabilities remain `uncertain_baseline` and are excluded from the
chart's evaluation denominator. Outcomes whose selected-choice probability is
below 0.7 are downgraded to `unclear`. Generic claims to beat the state of the art
do not establish that a particular baseline was beaten. When the baseline and
outcome answers disagree, the outcome remains unclear rather than inventing a win.

Recorded source reviews take precedence when the full text clearly resolves a
case. Source-text hashes are validated before corrections are applied. Machine
probabilities remain unchanged in the raw checkpoint; reviewed entries are
explicitly identified in the downloadable decisions.

## Source-text spot check

Codex checked 47 paper/model cases against original extracted paper text:
16 initially positive, 16 negative, eight borderline, and seven extraction edge
cases. Selection within the first three strata uses a stable hash and seed
`20261028`; edge cases were added separately. This was an agent source review,
not a human review or independent replication.

The review supported nine qualifying evaluations, rejected 32, and left six
unresolved. The audit records model-specific notes, source line ranges, paper
links, source-text hashes, initial and provenance-verified machine decisions,
and final review dispositions. Corrections include copied-score ambiguity,
original Gemini Robotics versus On-Device, restoring clearly documented runs
withheld by the excerpt pass, and a borrowed masking technique that was mistaken
for the released RDT-1B model. These stratified results are not an estimate of
corpus-wide accuracy.

## Reading the chart

The count view ranks baselines by the number of papers that actually evaluate
them. The percentage view divides each outcome by that model's evaluation-paper
count, retaining unclear results and evaluation-only studies in the denominator.
These are paper/model comparisons, not counts of tasks, experiments, or seeds.
A paper can evaluate several models. Results reflect authors' reported findings;
they do not establish independently replicated superiority or statistical
significance. Click a bar for the source paper list and baseline probability.

Dates use first submission, while full text is the latest available revision at
scan time. No release-date gate is applied. Only models already tracked by this
repository are covered. Partial runs are prominently labeled partial.

## Reproduce

```bash
MENTIONS_MODAL_VOLUME=robotics-research-papers uv run --no-sync modal run scripts/modal_evaluations.py
uv run --no-sync modal volume get robotics-research-papers /evaluations/candidates.jsonl.gz data/evaluations/candidates.jsonl.gz --force
uv run python -m mentions.evaluations --classify-only
uv run python -m mentions.evaluation_verification
uv run python -m mentions.evaluations
uv run python scripts/build_analysis_site.py
```

The Jev step requires `TYPESAFE_API_KEY`. It resumes unchanged paper evidence
from `data/evaluations/jev.jsonl`. Aggregates and downloadable paper decisions are
written to `output/evaluations/`.

The recorded source audit is `output/evaluations/audit.json`. Its sample selection
and publication tools are `scripts/prepare_evaluation_audit.py` and
`scripts/finalize_evaluation_audit.py`; the latter formats already recorded review
notes and never calls a model. Review source texts remain in the ignored
`data/evaluations/audit-text.jsonl.gz` bundle.
