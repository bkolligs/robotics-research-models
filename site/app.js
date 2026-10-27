const COUNTRY_NAMES = {
  usa: "United States",
  china: "China",
  uk: "United Kingdom",
  france: "France",
  "south korea": "South Korea",
};

const COLORS = [
  "#2258C3", "#E83030", "#E88532", "#105257", "#7A5195",
  "#70B8DB", "#81B135", "#C96442", "#333333", "#D7A800",
  "#9C27B0", "#0F62FE",
];

const state = {
  summary: null,
  papers: [],
  view: "variants",
  rate: "scanned",
  hidden: new Set(),
  query: "",
};

function nameOf(id) {
  if (state.view === "countries") return COUNTRY_NAMES[id] || id;
  if (state.view === "companies") return id;
  const row = state.summary.variants.find((item) => item.id === id);
  return row ? row.label : id;
}

function seriesKeys() {
  const summary = state.summary;
  if (state.view === "variants") return summary.variants.map((row) => row.id);
  if (state.view === "countries") return summary.countries.map((row) => row.id);
  return summary.companies.slice(0, 8).map((row) => row.id);
}

function percent(month, key) {
  const block = state.summary.monthly[month];
  if (!block) return null;
  const count = (block[state.view] || {})[key] || 0;
  const denom = state.rate === "model" ? block.any : block.papers;
  if (!denom) return null;
  return (100 * count) / denom;
}

function renderStatus() {
  const summary = state.summary;
  const source = summary.source === "scan"
    ? "Local scan, still running. GitHub Pages uses the committed corpus."
    : "Committed corpus.";
  document.getElementById("status").textContent =
    `${summary.papers_scanned.toLocaleString()} papers scanned through ${summary.through}. ${source}`;
  document.getElementById("stats").innerHTML = [
    ["Papers scanned", summary.papers_scanned.toLocaleString()],
    ["Name a tracked model", summary.any_model_papers.toLocaleString()],
    ["Share", summary.papers_scanned
      ? `${(100 * summary.any_model_papers / summary.papers_scanned).toFixed(1)}%`
      : "—"],
  ].map(([label, value]) => `<div class="stat"><b>${value}</b><span>${label}</span></div>`).join("");
}

function renderChart() {
  const months = state.summary.months;
  const keys = seriesKeys().filter((key) => !state.hidden.has(key));
  const width = 1000;
  const height = 360;
  const pad = { l: 48, r: 16, t: 16, b: 46 };
  const innerW = width - pad.l - pad.r;
  const innerH = height - pad.t - pad.b;
  const values = [];
  keys.forEach((key) => months.forEach((month) => {
    const value = percent(month, key);
    if (value != null) values.push(value);
  }));
  const max = Math.max(5, ...values, 0);
  const x = (index) => pad.l + (months.length <= 1 ? innerW / 2 : (index / (months.length - 1)) * innerW);
  const y = (value) => pad.t + innerH - (value / max) * innerH;
  const ticks = 4;
  let grid = "";
  for (let tick = 0; tick <= ticks; tick += 1) {
    const value = (max * tick) / ticks;
    const yy = y(value);
    grid += `<line x1="${pad.l}" x2="${width - pad.r}" y1="${yy}" y2="${yy}" stroke="#e4ddd2"/>`;
    grid += `<text x="${pad.l - 8}" y="${yy + 4}" text-anchor="end" font-size="11" fill="#5c564c">${value.toFixed(0)}%</text>`;
  }
  months.forEach((month, index) => {
    if (index % 3 !== 0 && index !== months.length - 1) return;
    grid += `<text x="${x(index)}" y="${height - 16}" text-anchor="middle" font-size="11" fill="#5c564c">${month}</text>`;
  });
  const lines = keys.map((key, index) => {
    const color = COLORS[seriesKeys().indexOf(key) % COLORS.length];
    const points = months.map((month, monthIndex) => {
      const value = percent(month, key);
      return value == null ? null : `${x(monthIndex).toFixed(1)},${y(value).toFixed(1)}`;
    }).filter(Boolean).join(" ");
    return `<polyline fill="none" stroke="${color}" stroke-width="2" points="${points}"/>`;
  }).join("");
  document.getElementById("chart").innerHTML =
    `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Mention rate by month">${grid}${lines}</svg>` +
    `<div class="legend">${seriesKeys().map((key, index) => {
      const color = COLORS[index % COLORS.length];
      const off = state.hidden.has(key) ? "off" : "on";
      return `<button type="button" class="${off}" data-series="${escapeAttr(key)}"><span class="swatch" style="background:${color}"></span>${escapeHtml(nameOf(key))}</button>`;
    }).join("")}</div>`;
  document.getElementById("chart-note").textContent = state.rate === "model"
    ? "Among papers that name at least one tracked model. Shares can overlap."
    : "Among every scanned paper that month. Shares can overlap.";
  document.querySelectorAll("[data-series]").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.series;
      if (state.hidden.has(key)) state.hidden.delete(key);
      else state.hidden.add(key);
      render();
    });
  });
}

function renderTable() {
  const body = document.querySelector("#totals tbody");
  const rows = state.view === "variants"
    ? state.summary.variants
    : state.view === "countries"
      ? state.summary.countries
      : state.summary.companies;
  body.innerHTML = rows.map((row) => {
    const origin = state.view === "variants"
      ? `${row.company} · ${COUNTRY_NAMES[row.country] || row.country}`
      : "";
    const scanned = state.summary.papers_scanned
      ? (100 * row.papers / state.summary.papers_scanned).toFixed(2)
      : "0";
    const model = (100 * (row.share_of_model_papers || 0)).toFixed(1);
    return `<tr class="${state.hidden.has(row.id) ? "off" : ""}">
      <td>${escapeHtml(nameOf(row.id))}</td>
      <td>${escapeHtml(origin)}</td>
      <td class="num">${row.papers.toLocaleString()}</td>
      <td class="num">${scanned}%</td>
      <td class="num">${model}%</td>
    </tr>`;
  }).join("");
}

function renderPapers() {
  const query = state.query.trim().toLowerCase();
  const visible = new Set(seriesKeys().filter((key) => !state.hidden.has(key)));
  const matches = state.papers.filter((paper) => {
    if (state.view === "variants" && !paper.variants.some((id) => visible.has(id))) return false;
    if (!query) return true;
    const names = paper.variants.map((id) => nameOf(id)).join(" ");
    return `${paper.title} ${names} ${paper.id}`.toLowerCase().includes(query);
  });
  document.getElementById("paper-count").textContent = `${matches.length.toLocaleString()} papers`;
  document.getElementById("papers").innerHTML = matches.slice(0, 40).map((paper) => {
    const tags = paper.variants.map((id) => nameOf(id)).join(", ");
    return `<li>
      <a href="https://arxiv.org/abs/${paper.id}">${escapeHtml(paper.title)}</a>
      <div class="meta">${paper.month} · ${paper.id} · ${escapeHtml(tags)}</div>
    </li>`;
  }).join("");
}

function render() {
  renderStatus();
  renderChart();
  renderTable();
  renderPapers();
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

function escapeAttr(value) {
  return escapeHtml(value);
}

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => {
    state.view = button.dataset.view;
    state.hidden = new Set();
    document.querySelectorAll("[data-view]").forEach((item) => item.classList.toggle("on", item === button));
    render();
  });
});

document.querySelectorAll("[data-rate]").forEach((button) => {
  button.addEventListener("click", () => {
    state.rate = button.dataset.rate;
    document.querySelectorAll("[data-rate]").forEach((item) => item.classList.toggle("on", item === button));
    render();
  });
});

document.getElementById("query").addEventListener("input", (event) => {
  state.query = event.target.value;
  renderPapers();
});

Promise.all([
  fetch("data/summary.json").then((response) => response.json()),
  fetch("data/papers.json").then((response) => response.json()),
]).then(([summary, papers]) => {
  state.summary = summary;
  state.papers = papers;
  render();
}).catch((error) => {
  document.getElementById("status").textContent = `Could not load site data: ${error}`;
});
