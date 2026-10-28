# Baseline usage after release

The lifecycle chart follows confirmed model evaluations from the baseline survey
over time. It addresses persistence and popularity of a particular released
baseline, rather than counting citations. It reuses the completed evaluation
decisions, execution-provenance checks, and recorded source reviews described in
[EVALUATIONS.md](EVALUATIONS.md). No additional Jev calls are required.

## Release dates and eligibility

[model_releases.json](model_releases.json) is a separately sourced registry of
release reference dates. Dates come from public model announcements, original
paper submission histories, or a documented early-access release. Every date
has a primary-source link and an explicit basis. These dates do not necessarily
equal public checkpoint availability. For example, pi0 was announced October 31,
2024 and its code and weights were released February 4, 2025. The registry records
both dates for pi0 and the chart uses the announcement as its release reference.
Other models' checkpoint dates have not been systematically curated.

The first version of the chart has 23 sourced release rows. Other evaluated
models remain in the shared denominator but have no aligned curve until a
release reference is curated. Unspecified model-family rows are not assigned a
guessed release date. The website explicitly lists omitted models and sources.

For this chart only, an evaluated paper/model pair is eligible if:

1. Its final evaluation decision qualifies as a confirmed evaluation, including
   directly evaluated diagnostic targets and cases with an unclear outcome.
2. The paper's first-submission **date** is on or after the model's release
   reference date. The gate uses the exact day, not just year or month.
3. The paper is not the registered paper introducing that model. This prevents
   a self-introduction from being mistaken for subsequent baseline adoption.

The original mention and evaluation charts remain unchanged. Some pre-release
comparisons arise from later paper revisions or ambiguous names; those pairs
are counted and reported as exclusions in the lifecycle output. Post-release
gating does not establish the date on which experiments were performed.

## Axes and denominator

The default horizontal axis is calendar-month offset from release: the release
calendar month is zero. Calendar time is available to show which generations
overlap in actual publication time. A curve ends at the last scanned corpus
month, regardless of when the model was last evaluated. It is never padded with
future zeroes. The dataset begins January 2023, so early histories of older
models such as CLIPort, R3M, and RT-1 are unobserved and explicitly identified.

The default vertical measure is the number of papers evaluating the model
divided by the number of **distinct papers evaluating any tracked model** in
that same calendar month. A paper evaluating several models counts once in the
denominator and once in each applicable numerator. The denominator remains the
existing full evaluation-paper population, independent of which release dates
have been curated; it is not restricted to the displayed or selected models.
Shares can overlap and need not sum to 100%.

The default trailing-three-month series pools numerators and denominators across
the current and preceding two observed months. It does not average percentages.
At the beginning of a series, the available one or two months are used. Tooltips
show window length and raw counts. Count mode plots a monthly average over the
same window; individual-month counts are also available. Peak-relative mode
divides the selected share series by that model's maximum observed share. This
can amplify noise for rarely evaluated models, so counts remain in tooltips.

Unscanned months are missing values, never zero usage. A scanned month with no
evaluation papers has undefined share. Curves break at missing values, and a
smoothing window crossing an unscanned month is also missing. The table's
descriptive peak requires a full three-month window and at least 20 evaluation papers to avoid
calling a one-paper result the peak. The last-use and peak dates are observations,
not estimates of a model's retirement or future lifetime.

## Interpretation

A falling share can coincide with increasing absolute paper counts when the
literature grows. A recent model's short curve is a shorter observation window,
not a short lifespan. Closed access, task mix, publication delays, unresolved
evaluation evidence, and incomplete release coverage also affect these curves.
No recent observed evaluation is evidence about this corpus, not proof of
technical obsolescence or causal replacement by a successor.

## Reproduce

```bash
uv run python -m mentions.lifecycle
uv run python scripts/build_analysis_site.py
```

Inputs are `output/evaluations/papers.json`, `data/analysis-papers.sqlite` for
exact first-submission dates and coverage, and `docs/model_releases.json`.
Outputs are `output/baseline-lifecycle/summary.json` and `monthly.csv`.
The summary records hashes of the evaluation decisions and release registry.
