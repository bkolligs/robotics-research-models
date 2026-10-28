const ARCH_COLORS = [
  "#2258C3", "#E83030", "#E88532", "#105257", "#7A5195", "#70B8DB",
  "#81B135", "#C96442", "#333333", "#D7A800", "#9C27B0", "#0F62FE",
  "#A3445D", "#557A46", "#6C5B7B", "#7F8C8D",
];

const architectureState = {
  summary: null,
  rate: "population",
  measure: "count",
  hidden: new Set(),
};

function architecturePercent(row) {
  if (!row || !row.population) return null;
  if (architectureState.measure === "count") return row.papers;
  const denominator = architectureState.rate === "relevant"
    ? row.trend_positive
    : row.population;
  return denominator ? 100 * row.papers / denominator : null;
}

function renderArchitectureChart() {
  const summary = architectureState.summary;
  const counts = architectureState.measure === "count";
  document.getElementById("architecture-rate-controls").hidden = counts;
  const section = document.getElementById("architecture-section");
  section.hidden = false;
  const definitions = summary.trend_definitions;
  const totals = summary.multi_label_trends;
  const trends = totals.map((row) => row.trend);
  const months = [...new Set(summary.monthly.map((row) => row.month))];
  const rows = new Map(summary.monthly.map((row) => [`${row.month}\0${row.trend}`, row]));
  const visible = trends.filter((trend) => !architectureState.hidden.has(trend));
  const width = 1050, height = 430;
  const pad = { l: 60, r: 20, t: 22, b: 52 };
  const innerW = width - pad.l - pad.r, innerH = height - pad.t - pad.b;
  const values = [];
  for (const month of months) for (const trend of visible) {
    const value = architecturePercent(rows.get(`${month}\0${trend}`));
    if (value !== null) values.push(value);
  }
  const rawMax = Math.max(5, ...values);
  const tickSize = counts ? Math.max(1, 10 ** Math.floor(Math.log10(rawMax / 5))) * 5 : rawMax > 20 ? 10 : 5;
  const max = Math.ceil(rawMax / tickSize) * tickSize;
  const x = (index) => pad.l + innerW * index / Math.max(1, months.length - 1);
  const y = (value) => pad.t + innerH * (1 - value / max);
  const color = (trend) => ARCH_COLORS[trends.indexOf(trend) % ARCH_COLORS.length];
  let marks = "";
  for (let tick = 0; tick <= 5; tick++) {
    const value = max * tick / 5;
    marks += `<line x1="${pad.l}" x2="${width-pad.r}" y1="${y(value)}" y2="${y(value)}" stroke="#e4ddd2"/><text x="${pad.l-8}" y="${y(value)+4}" text-anchor="end" font-size="12" fill="#5c564c">${value.toFixed(0)}${counts ? "" : "%"}</text>`;
  }
  months.forEach((month, index) => {
    if (index % 4 === 0 || index === months.length - 1) {
      marks += `<text x="${x(index)}" y="${height-22}" text-anchor="middle" font-size="12" fill="#5c564c">${month}</text>`;
    }
  });
  for (const trend of visible) {
    const points = months.map((month, index) => {
      const row = rows.get(`${month}\0${trend}`);
      const value = architecturePercent(row);
      return value === null ? null : { month, row, value, x: x(index), y: y(value) };
    });
    let path = "";
    let drawing = false;
    for (const point of points) {
      if (!point) { drawing = false; continue; }
      path += `${drawing ? "L" : "M"}${point.x.toFixed(2)},${point.y.toFixed(2)} `;
      drawing = true;
    }
    marks += `<path d="${path}" fill="none" stroke="${color(trend)}" stroke-width="2.5"/>`;
    for (const point of points.filter(Boolean)) {
      const denominator = architectureState.rate === "relevant"
        ? point.row.trend_positive : point.row.population;
      const denominatorLabel = architectureState.rate === "relevant"
        ? "trend-positive papers" : "surveyed model papers";
      const detail = `${point.month} · ${definitions[trend].label} · ${counts ? `${point.row.papers.toLocaleString()} papers` : `${point.value.toFixed(1)}%`} · ${point.row.papers.toLocaleString()} of ${denominator.toLocaleString()} ${denominatorLabel}`;
      marks += `<circle class="trend-point" tabindex="0" data-detail="${escapeAttr(detail)}" aria-label="${escapeAttr(detail)}" cx="${point.x}" cy="${point.y}" r="3.5" fill="${color(trend)}"><title>${escapeHtml(detail)}</title></circle>`;
    }
  }
  const denominatorText = architectureState.rate === "relevant"
    ? "papers Jev judged positive for at least one architecture trend"
    : "all model-mention papers in the survey";
  document.getElementById("architecture-population").textContent =
    `${summary.papers_classified.toLocaleString()} papers classified from titles and abstracts; ${summary.trend_positive.toLocaleString()} were positive for at least one architecture trend. ${counts ? "The chart counts papers per trend each month." : `Each trend is divided by ${denominatorText} that month.`}`;
  document.getElementById("architecture-chart").innerHTML =
    `<div class="stack-scroll"><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Monthly architecture trend ${counts ? "paper counts" : "percentages"}"><text x="${pad.l}" y="14" font-size="11" fill="#5c564c">${counts ? "Papers per month" : "Share of papers"} above trend threshold</text>${marks}</svg></div>` +
    '<p class="stack-detail" id="architecture-detail" aria-live="polite">Hover, tap, or focus a point for its month, trend, percentage, and paper count.</p>' +
    `<div class="legend trend-legend">${selectedFirst(trends, (trend) => !architectureState.hidden.has(trend), (trend) => totals.find((row) => row.trend === trend).papers).map((trend) => `<button type="button" data-architecture-series="${escapeAttr(trend)}" aria-pressed="${!architectureState.hidden.has(trend)}" class="${architectureState.hidden.has(trend) ? "off" : ""}"><span class="swatch" style="background:${color(trend)}"></span><span><strong>${escapeHtml(definitions[trend].label)}</strong><small>${totals.find((row) => row.trend === trend).papers.toLocaleString()} papers overall</small></span></button>`).join("")}</div>`;
  document.getElementById("architecture-method").textContent = `Trend threshold: ${(100 * summary.threshold).toFixed(0)}%. ${summary.papers_classified.toLocaleString()} papers assessed; ${summary.trend_positive.toLocaleString()} positive for at least one trend.`;
  document.getElementById("architecture-note").textContent =
    "We track overlapping trends: one paper can address several.";
  document.querySelectorAll("#architecture-chart .trend-point").forEach((point) => {
    for (const event of ["mouseenter", "focus", "click"]) point.addEventListener(event, () => {
      document.getElementById("architecture-detail").textContent = point.dataset.detail;
    });
  });
  document.querySelectorAll("[data-architecture-series]").forEach((button) => button.addEventListener("click", () => {
    const trend = button.dataset.architectureSeries;
    if (architectureState.hidden.has(trend)) architectureState.hidden.delete(trend);
    else architectureState.hidden.add(trend);
    renderArchitectureChart();
  }));
}

document.getElementById("architecture-measure").addEventListener("change", (event) => {
  architectureState.measure = event.target.value;
  if (architectureState.summary) renderArchitectureChart();
});

document.querySelectorAll("[data-architecture-rate]").forEach((button) => {
  button.addEventListener("click", () => {
    architectureState.rate = button.dataset.architectureRate;
    document.querySelectorAll("[data-architecture-rate]").forEach((item) => {
      item.classList.toggle("on", item === button);
      item.setAttribute("aria-pressed", String(item === button));
    });
    renderArchitectureChart();
  });
});

fetch("analysis/architecture-survey/summary.json").then((response) => {
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
}).then((summary) => {
  architectureState.summary = summary;
  const required = new Set(["vision_language_action", "world_action_model", "agentic_robotics"]);
  for (const row of summary.multi_label_trends) {
    if (required.size >= 6) break;
    if (row.trend === "other_architecture") continue;
    required.add(row.trend);
  }
  architectureState.hidden = new Set(
    summary.multi_label_trends.map((row) => row.trend).filter((trend) => !required.has(trend)),
  );
  renderArchitectureChart();
}).catch(() => {
  document.getElementById("architecture-section").hidden = true;
});
