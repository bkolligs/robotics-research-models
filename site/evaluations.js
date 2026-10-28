const EVALUATION_OUTCOMES = {
  beaten: ["Paper beats baseline", "#2f8060"],
  mixed: ["Mixed results", "#d49b36"],
  tied: ["Comparable / tied", "#6488b4"],
  baseline_wins: ["Baseline wins", "#b85e62"],
  unclear: ["Outcome unclear", "#99948a"],
  no_proposed_method: ["Evaluation only", "#8a76a2"],
};
const evaluationState = { summary: null, papers: [], year: "all", scale: "count", selected: null };

function evaluationRows() {
  const summary = evaluationState.summary;
  if (evaluationState.year === "all") return summary.totals;
  return summary.totals.map((total) => {
    const rows = summary.monthly.filter((r) => r.model_id === total.model_id && r.month.startsWith(evaluationState.year));
    const outcomes = {};
    for (const row of rows) for (const [key, count] of Object.entries(row.outcomes)) outcomes[key] = (outcomes[key] || 0) + count;
    return { ...total, evaluations: rows.reduce((sum, r) => sum + r.evaluations, 0), outcomes };
  });
}

function renderEvaluationPapers() {
  const target = document.getElementById("evaluation-papers");
  if (!evaluationState.selected) { target.innerHTML = ""; return; }
  const model = evaluationState.summary.totals.find((r) => r.model_id === evaluationState.selected);
  const papers = evaluationState.papers.filter((r) => r.model_id === model.model_id && r.outcome !== "uncertain_baseline" &&
    (evaluationState.year === "all" || r.month.startsWith(evaluationState.year))).sort((a, b) => b.paper_id.localeCompare(a.paper_id));
  target.innerHTML = `<h3>${escapeHtml(model.label)}: ${papers.length.toLocaleString()} evaluation papers</h3>` +
    '<p class="note">Outcomes describe each paper’s proposed method relative to this baseline. Consult the linked paper for exact tasks and metrics.</p>' +
    `<div class="table-wrap evaluation-paper-scroll"><table><thead><tr><th>Paper</th><th>Reported outcome</th><th>Baseline evidence probability</th></tr></thead><tbody>${papers.map((p) =>
      `<tr><td><a href="https://arxiv.org/abs/${encodeURIComponent(p.paper_id)}" target="_blank" rel="noopener">${escapeHtml(p.title)}</a><small class="meta"> ${escapeHtml(p.paper_id)}</small></td><td>${escapeHtml(EVALUATION_OUTCOMES[p.outcome]?.[0] || p.outcome)}</td><td>${p.source_reviewed ? "Source reviewed" : `${(p.baseline_probability * 100).toFixed(0)}%`}</td></tr>`
    ).join("")}</tbody></table></div>`;
}

function renderEvaluations() {
  const summary = evaluationState.summary;
  const rows = evaluationRows().filter((r) => r.evaluations > 0).sort((a, b) => b.evaluations - a.evaluations);
  const width = 1050, rowHeight = 34, left = 235, right = 75, top = 45;
  const height = top + rows.length * rowHeight + 30, inner = width - left - right;
  const max = evaluationState.scale === "share" ? 100 : Math.max(1, ...rows.map((r) => r.evaluations));
  let marks = "";
  for (let tick = 0; tick <= 4; tick++) {
    const value = max * tick / 4, x = left + inner * tick / 4;
    marks += `<line x1="${x}" x2="${x}" y1="28" y2="${height-20}" stroke="#e4ddd2"/><text x="${x}" y="18" text-anchor="middle" font-size="12" fill="#5c564c">${Math.round(value)}${evaluationState.scale === "share" ? "%" : ""}</text>`;
  }
  rows.forEach((row, index) => {
    const y = top + index * rowHeight;
    marks += `<text x="${left-10}" y="${y+15}" text-anchor="end" font-size="12" fill="#292720">${escapeHtml(row.label)}</text>`;
    let offset = 0;
    for (const [outcome, [label, color]] of Object.entries(EVALUATION_OUTCOMES)) {
      const count = row.outcomes[outcome] || 0;
      if (!count) continue;
      const value = evaluationState.scale === "share" ? count / row.evaluations * 100 : count;
      const w = inner * value / max;
      const detail = `${row.label} · ${label} · ${count.toLocaleString()} of ${row.evaluations.toLocaleString()} evaluation papers (${(100*count/row.evaluations).toFixed(1)}%)`;
      marks += `<rect class="stack-segment" tabindex="0" role="button" aria-label="${escapeAttr(detail)}; show papers" data-evaluation-model="${escapeAttr(row.model_id)}" data-evaluation-detail="${escapeAttr(detail)}" x="${left+offset}" y="${y}" width="${w}" height="23" fill="${color}"><title>${escapeHtml(detail)}</title></rect>`;
      offset += w;
    }
    marks += `<text x="${left+offset+7}" y="${y+15}" font-size="12" fill="#5c564c">${row.evaluations.toLocaleString()}</text>`;
  });
  const total = rows.reduce((sum, r) => sum + r.evaluations, 0);
  document.getElementById("evaluation-population").textContent =
    `${summary.complete ? "Complete corpus assessment" : "Partial assessment"}: ${summary.papers_classified.toLocaleString()} papers assessed across ${summary.paper_model_pairs.toLocaleString()} model mentions. This selection contains ${total.toLocaleString()} confirmed paper–model evaluations; a paper can evaluate several models. Jev evidence threshold: ${(100*summary.threshold).toFixed(0)}%; source-reviewed decisions take precedence.`;
  document.getElementById("evaluation-audit").textContent = summary.source_audit
    ? `${summary.source_audit.cases} sampled cases were checked against original paper text, including positive, negative, and borderline judgments. Unresolved execution provenance is excluded. ${summary.execution_verification.release_recheck_pending || 0} Gemini release checks remain pending and are excluded unless source reviewed.`
    : "Source-text spot check is pending.";
  document.getElementById("evaluation-chart").innerHTML = rows.length ?
    `<div class="stack-scroll"><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Experimental baseline frequency and reported comparative outcomes">${marks}</svg></div>` : '<p class="note">No confident baseline evaluations in this selection.</p>';
  document.getElementById("evaluation-legend").innerHTML = Object.values(EVALUATION_OUTCOMES).map(([label, color]) => `<span><i class="swatch" style="background:${color}"></i>${escapeHtml(label)}</span>`).join("");
  document.querySelectorAll("[data-evaluation-model]").forEach((mark) => {
    const show = () => { evaluationState.selected = mark.dataset.evaluationModel; renderEvaluationPapers(); };
    mark.addEventListener("click", show);
    mark.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); show(); } });
    for (const event of ["mouseenter", "focus"]) mark.addEventListener(event, () => {
      document.getElementById("evaluation-detail").textContent = mark.dataset.evaluationDetail;
    });
  });
  renderEvaluationPapers();
}

Promise.all(["summary.json", "papers.json"].map((name) => fetch(`analysis/evaluations/${name}`).then((r) => {
  if (!r.ok) throw new Error(String(r.status));
  return r.json();
}))).then(([summary, papers]) => {
  evaluationState.summary = summary;
  evaluationState.papers = papers;
  const years = [...new Set(summary.monthly.map((r) => r.month.slice(0, 4)))].sort();
  const year = document.getElementById("evaluation-year");
  year.innerHTML = '<option value="all">All years</option>' + years.map((value) => `<option value="${value}">${value}</option>`).join("");
  year.addEventListener("change", () => { evaluationState.year = year.value; renderEvaluations(); });
  document.getElementById("evaluation-scale").addEventListener("change", (event) => { evaluationState.scale = event.target.value; renderEvaluations(); });
  renderEvaluations();
}).catch((error) => {
  document.getElementById("evaluation-population").textContent = "Evaluation survey data is not available yet.";
  console.warn("Evaluation survey unavailable", error);
});
