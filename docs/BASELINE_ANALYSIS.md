# Baseline and performance analysis

Status: proposed analysis; no extracted performance results yet.

This extends mention counting. A mention, including a reference, does not establish experimental use or a performance comparison. Existing mention charts remain unchanged.

## Extraction

Read full paper text and tables, retaining paper version, text checksum, page or section, table identifier, and verbatim evidence for each result. Record the extraction tool/model and prompt version. "Jev" integration is pending clarification.

Classify each tracked model independently as:
- citation or related-work mention;
- experimentally evaluated baseline;
- backbone or component of the proposed method;
- proposed method;
- unclear.

Roles may coexist. Distinguish results evaluated by the paper's authors from scores quoted from prior work. Preserve exact model variant and checkpoint when available; use family-only or unspecified rather than guessing.

For each comparison record:
- paper ID/version, proposed method, tracked baseline model/variant/family;
- benchmark, task, dataset/split, evaluation setting, number of trials/seeds;
- metric, units, higher/lower-is-better direction;
- proposed-method and baseline scores, uncertainty if reported;
- same-setting comparability, evidence passages and table cells;
- claimed improvement versus independently computed improvement;
- extraction confidence, review status, and unresolved ambiguity.

Use explicit unknown/null values for missing information. Do not infer baseline use from proximity to "outperform." Table headers, row labels, units, and evaluation conditions must be linked to their values. Keep ACT acronym disambiguation as a separate validated matching change.

## Improvement calculations

For comparable scores P (proposed) and B (baseline), define direction d as +1 for higher-is-better and -1 for lower-is-better.
- Direction-adjusted absolute improvement: d * (P - B), in the metric's original units.
- Relative improvement: 100 * d * (P - B) / abs(B), only when B is nonzero and a ratio is meaningful.
- For success rates expressed as percentages, absolute differences are percentage points, not percent improvements.

Positive means proposed method is better; negative means worse; zero means tied. Do not infer statistical significance from a positive difference. Retain ties, losses, and unquantified claims. Separate incompatible tasks and metrics; never average percentages across unrelated benchmarks.

## Charts

1. Baseline-use bar chart: distinct papers experimentally evaluating each tracked model, with institution and country labels. Provide variant/family toggle; family counts deduplicate papers.
2. Performance comparison plot: signed improvements over a selected baseline, filtered by benchmark, task, metric, and evaluation setting. Show paper-level observations, original score pairs, units, and evidence on inspection.
3. Comparison coverage: evaluated baselines, comparable numeric results, unquantified claims, and excluded/unclear observations.

Clearly distinguish paper counts from comparison counts: one paper can report many tasks and metrics. Avoid an unconditional cross-benchmark "best model" ranking.

## Validation and inputs

Require full paper text/tables rather than abstracts or existing mention totals. Pilot on a manually reviewed sample containing ACT, Diffusion Policy, wins, ties, losses, quoted results, and ambiguous tables. Measure role-classification precision/recall and numeric/metric extraction accuracy before a corpus-wide run. Chart only reviewed or explicitly designated validated records, and report missing/excluded evidence.

No costs, remote extraction jobs, or corpus-wide inference have been initiated.
