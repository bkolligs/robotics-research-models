const LLM_COLORS = ["#2258C3", "#E83030", "#7A5195", "#105257", "#E88532"];

const llmState = { summary: null, hidden: new Set() };

function llmPercent(row, metric) {
  const count = metric === "mention" ? row.mention_papers : row.usage_papers;
  return row.papers_scanned ? 100 * count / row.papers_scanned : null;
}

function llmTick(value) {
  if (value >= 10) return `${value.toFixed(0)}%`;
  if (value >= 1) return `${value.toFixed(1)}%`;
  return `${value.toFixed(2)}%`;
}

function renderLlmChart() {
  const summary = llmState.summary;
  const models = summary.models;
  const allMonths = [...new Set(summary.monthly.map((row) => row.month))];
  const firstHit = allMonths.findIndex((month) => summary.monthly.some(
    (row) => row.month === month && row.mention_papers > 0,
  ));
  const months = allMonths.slice(firstHit < 0 ? 0 : Math.max(0, firstHit - 2));
  const rows = new Map(summary.monthly.map((row) => [`${row.month}\0${row.model_id}`, row]));
  const visible = models.filter((model) => !llmState.hidden.has(model.model_id));
  const width = 1050, height = 430;
  const pad = { l: 68, r: 20, t: 30, b: 52 };
  const innerW = width - pad.l - pad.r, innerH = height - pad.t - pad.b;
  const values = [];
  for (const month of months) for (const model of visible) {
    const row = rows.get(`${month}\0${model.model_id}`);
    for (const metric of ["mention", "usage"]) {
      const value = llmPercent(row, metric);
      if (value !== null) values.push(value);
    }
  }
  const rawMax = Math.max(0.25, ...values);
  const magnitude = 10 ** Math.floor(Math.log10(rawMax));
  const max = Math.ceil(rawMax / magnitude * 2) / 2 * magnitude;
  const x = (index) => pad.l + innerW * index / Math.max(1, months.length - 1);
  const y = (value) => pad.t + innerH * (1 - value / max);
  const color = (modelId) => LLM_COLORS[models.findIndex((row) => row.model_id === modelId) % LLM_COLORS.length];
  let marks = "";
  for (let tick = 0; tick <= 5; tick++) {
    const value = max * tick / 5;
    marks += `<line x1="${pad.l}" x2="${width-pad.r}" y1="${y(value)}" y2="${y(value)}" stroke="#e4ddd2"/><text x="${pad.l-8}" y="${y(value)+4}" text-anchor="end" font-size="12" fill="#5c564c">${llmTick(value)}</text>`;
  }
  months.forEach((month, index) => {
    if (index % 2 === 0 || index === months.length - 1) {
      marks += `<text x="${x(index)}" y="${height-22}" text-anchor="middle" font-size="12" fill="#5c564c">${month}</text>`;
    }
  });
  for (const model of visible) {
    for (const metric of ["mention", "usage"]) {
      const points = months.map((month, index) => {
        const row = rows.get(`${month}\0${model.model_id}`);
        const value = llmPercent(row, metric);
        return value === null ? null : { month, row, value, x: x(index), y: y(value) };
      });
      let path = "", drawing = false;
      for (const point of points) {
        if (!point) { drawing = false; continue; }
        path += `${drawing ? "L" : "M"}${point.x.toFixed(2)},${point.y.toFixed(2)} `;
        drawing = true;
      }
      const dashed = metric === "mention" ? ' stroke-dasharray="7 5"' : "";
      marks += `<path d="${path}" fill="none" stroke="${color(model.model_id)}" stroke-width="${metric === "usage" ? 3 : 2}"${dashed}/>`;
      for (const point of points.filter(Boolean)) {
        const count = metric === "mention" ? point.row.mention_papers : point.row.usage_papers;
        const label = metric === "mention" ? "full-text mentions" : "Jev-judged uses";
        const detail = `${point.month} · ${model.label} · ${label} · ${llmTick(point.value)} · ${count.toLocaleString()} of ${point.row.papers_scanned.toLocaleString()} scanned papers`;
        marks += `<circle class="trend-point llm-point" style="--series-color:${color(model.model_id)}" tabindex="0" data-llm-detail="${escapeAttr(detail)}" aria-label="${escapeAttr(detail)}" cx="${point.x}" cy="${point.y}" r="${metric === "usage" ? 4 : 3}" fill="${metric === "usage" ? color(model.model_id) : "#fff"}" stroke-width="2"><title>${escapeHtml(detail)}</title></circle>`;
      }
    }
  }
  document.getElementById("llm-population").textContent =
    `${summary.papers_scanned.toLocaleString()} successfully scanned robotics papers; ${summary.papers_mentioning_tracked_llm.toLocaleString()} mention a tracked frontier LLM and ${summary.papers_using_tracked_llm.toLocaleString()} were judged to actively use or directly evaluate one.`;
  document.getElementById("llm-chart").innerHTML =
    `<div class="stack-scroll"><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Monthly LLM mention and usage rates"><text x="${pad.l}" y="16" font-size="11" fill="#5c564c">Share of all successfully scanned cs.RO papers</text>${marks}</svg></div>` +
    '<p class="stack-detail" id="llm-detail" aria-live="polite">Hover, tap, or focus a point for its month, model, rate, and paper count.</p>' +
    '<div class="llm-style-key"><span><i class="llm-line mention"></i>Full-text mention</span><span><i class="llm-line usage"></i>Jev-judged usage</span></div>' +
    `<div class="legend trend-legend">${models.map((model) => {
      const total = summary.totals.find((row) => row.model_id === model.model_id);
      return `<button type="button" data-llm-series="${escapeAttr(model.model_id)}" aria-pressed="${!llmState.hidden.has(model.model_id)}" class="${llmState.hidden.has(model.model_id) ? "off" : ""}"><span class="swatch" style="background:${color(model.model_id)}"></span><span><strong>${escapeHtml(model.label)}</strong><small>${total.mention_papers.toLocaleString()} mentioned · ${total.usage_papers.toLocaleString()} used</small></span></button>`;
    }).join("")}</div>`;
  document.getElementById("llm-note").textContent =
    "Dashed lines include bibliography-only citations. Solid lines require Jev evidence that the authors ran, integrated, or directly evaluated the named model; this still does not imply it was the paper’s backbone. Months use first submission, while the scan reads the latest available revision, so a later revision can create a pre-release-looking point. Click a model in the legend to hide or show it.";
  document.querySelectorAll("[data-llm-detail]").forEach((point) => {
    for (const event of ["mouseenter", "focus", "click"]) point.addEventListener(event, () => {
      document.getElementById("llm-detail").textContent = point.dataset.llmDetail;
    });
  });
  document.querySelectorAll("[data-llm-series]").forEach((button) => button.addEventListener("click", () => {
    const modelId = button.dataset.llmSeries;
    if (llmState.hidden.has(modelId)) llmState.hidden.delete(modelId);
    else llmState.hidden.add(modelId);
    renderLlmChart();
  }));
}

fetch("analysis/llm-survey/summary.json").then((response) => {
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
}).then((summary) => {
  llmState.summary = summary;
  document.getElementById("llm-section").hidden = false;
  renderLlmChart();
}).catch(() => {
  document.getElementById("llm-section").hidden = true;
});
