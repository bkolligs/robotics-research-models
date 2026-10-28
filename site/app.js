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
  if (state.view === "companies" || state.view === "families") return id;
  const row = state.summary.variants.find((item) => item.id === id);
  return row ? row.label : id;
}

function seriesKeys() {
  const summary = state.summary;
  if (state.view === "variants") return summary.variants.map((row) => row.id);
  if (state.view === "families") return summary.families.map((row) => row.id);
  if (state.view === "countries") return summary.countries.map((row) => row.id);
  return summary.companies.map((row) => row.id);
}

function percent(month, key) {
  const block = state.summary.monthly[month];
  if (!block) return null;
  const count = (block[state.view] || {})[key] || 0;
  const denom = state.rate === "model" ? block.any : block.papers;
  if (!denom) return null;
  return (100 * count) / denom;
}

function buildFamilies() {
  const families = new Map();
  const variants = new Map(state.summary.variants.map((row) => [row.id, row]));
  for (const row of variants.values()) {
    if (!families.has(row.family)) families.set(row.family, {
      id: row.family, papers: 0, companies: new Set(), countries: new Set(),
    });
    const family = families.get(row.family);
    if (row.company) family.companies.add(row.company);
    if (row.country) family.countries.add(COUNTRY_NAMES[row.country] || row.country);
  }
  for (const block of Object.values(state.summary.monthly)) block.families = {};
  for (const paper of state.papers) {
    const uniqueFamilies = new Set(paper.variants.map((id) => variants.get(id)?.family).filter(Boolean));
    for (const name of uniqueFamilies) {
      families.get(name).papers += 1;
      const monthly = state.summary.monthly[paper.month]?.families;
      if (monthly) monthly[name] = (monthly[name] || 0) + 1;
    }
  }
  state.summary.families = [...families.values()].map((row) => ({
    id: row.id, papers: row.papers, company: [...row.companies].join(" / "),
    country: [...row.countries].join(" / "),
    share_of_model_papers: state.summary.any_model_papers ? row.papers / state.summary.any_model_papers : 0,
  })).sort((a, b) => b.papers - a.papers);
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
  const modelOnly = state.rate === "model";
  document.getElementById("chart-title").textContent = modelOnly
    ? "Model mentions among model papers only"
    : "Model mentions among all robotics papers";
  const population = modelOnly ? state.summary.any_model_papers : state.summary.papers_scanned;
  document.getElementById("chart-population").textContent = modelOnly
    ? `Within the cs.RO corpus, only papers mentioning at least one tracked model are included: ${population.toLocaleString()} papers across all months. Each month uses its own model-paper count as the denominator.`
    : `All ${population.toLocaleString()} successfully scanned cs.RO papers are included, even those naming no tracked model. Each month uses its own scanned-paper count as the denominator.`;
  const months = state.summary.months;
  const allKeys = seriesKeys();
  const keys = allKeys.filter((key) => !state.hidden.has(key));
  const width = 1050, height = 430;
  const pad = { l: 60, r: 16, t: 22, b: 52 };
  const innerW = width - pad.l - pad.r, innerH = height - pad.t - pad.b;
  const totals = months.map((month) => keys.reduce((sum, key) => sum + (percent(month, key) || 0), 0));
  const max = Math.ceil(Math.max(10, ...totals) / 10) * 10;
  const y = (value) => pad.t + innerH * (1 - value / max);
  const step = innerW / Math.max(1, months.length);
  const color = (key) => {
    const index = allKeys.indexOf(key);
    return index < COLORS.length ? COLORS[index] : `hsl(${(index * 137.508) % 360} 60% 48%)`;
  };
  const origin = (key) => {
    if (!["variants", "families"].includes(state.view)) return "";
    const row = state.summary[state.view].find((item) => item.id === key);
    return [row?.company, COUNTRY_NAMES[row?.country] || row?.country].filter(Boolean).join(" · ");
  };
  let marks = "";
  for (let tick = 0; tick <= 5; tick++) {
    const value = max * tick / 5;
    marks += `<line x1="${pad.l}" x2="${width-pad.r}" y1="${y(value)}" y2="${y(value)}" stroke="#e4ddd2"/><text x="${pad.l-8}" y="${y(value)+4}" text-anchor="end" font-size="12" fill="#5c564c">${value.toFixed(0)}%</text>`;
  }
  months.forEach((month, index) => {
    const block = state.summary.monthly[month];
    const denom = state.rate === "model" ? block.any : block.papers;
    let bottom = 0;
    keys.forEach((key) => {
      const value = percent(month, key);
      if (value == null || value === 0) return;
      const count = (block[state.view] || {})[key] || 0;
      const detail = `${month} · ${nameOf(key)}${origin(key) ? ` · ${origin(key)}` : ""} · ${value.toFixed(2)}% · ${count.toLocaleString()} of ${denom.toLocaleString()} papers`;
      marks += `<rect class="stack-segment" tabindex="0" data-detail="${escapeAttr(detail)}" aria-label="${escapeAttr(detail)}" x="${pad.l+index*step+step*0.08}" y="${y(bottom+value)}" width="${step*0.84}" height="${innerH*value/max}" fill="${color(key)}"><title>${escapeHtml(detail)}</title></rect>`;
      bottom += value;
    });
    if (!denom) {
      marks += `<text x="${pad.l+(index+0.5)*step}" y="${y(0)-6}" text-anchor="middle" font-size="12" fill="#5c564c"><title>${month}: no eligible papers</title>—</text>`;
    }
    if (index % 4 === 0 || index === months.length-1) {
      marks += `<text x="${pad.l+(index+0.5)*step}" y="${height-22}" text-anchor="middle" font-size="12" fill="#5c564c">${month}</text>`;
    }
  });
  document.getElementById("chart").innerHTML =
    `<div class="stack-scroll"><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Monthly stacked mention percentages"><text x="${pad.l}" y="14" font-size="11" fill="#5c564c">Sum of mention percentages</text>${marks}</svg></div>` +
    '<p class="stack-detail" id="stack-detail" aria-live="polite">Hover, tap, or focus a segment for its model or family, institution, country, and paper count.</p>' +
    `<div class="legend">${allKeys.map((key) => `<button type="button" data-series="${escapeAttr(key)}" aria-pressed="${!state.hidden.has(key)}" class="${state.hidden.has(key) ? "off" : ""}"><span class="swatch" style="background:${color(key)}"></span><span><strong>${escapeHtml(nameOf(key))}</strong>${origin(key) ? `<small>${escapeHtml(origin(key))}</small>` : ""}</span></button>`).join("")}</div>`;
  document.getElementById("chart-note").textContent =
    `${state.rate === "model" ? "Each segment is a percentage of papers naming at least one tracked model that month." : "Each segment is a percentage of all scanned papers that month."} Each family counts a paper once, even when it names multiple variants. A paper can mention multiple models or institutions: stacks sum overlapping percentages and can exceed 100%. They are not shares of an exclusive whole. — means no eligible papers. Click a legend entry to hide or show it.`;
  document.querySelectorAll(".stack-segment").forEach((segment) => {
    for (const event of ["mouseenter", "focus", "click"]) segment.addEventListener(event, () => {
      document.getElementById("stack-detail").textContent = segment.dataset.detail;
    });
  });
  document.querySelectorAll("[data-series]").forEach((button) => button.addEventListener("click", () => {
    const key = button.dataset.series;
    if (state.hidden.has(key)) state.hidden.delete(key); else state.hidden.add(key);
    render();
  }));
}

function renderTable() {
  const body = document.querySelector("#totals tbody");
  const modelView = ["variants", "families"].includes(state.view);
  const labels = {
    variants: ["Model mention totals and producers", "Model release"],
    families: ["Model family mention totals and producers", "Model family"],
    countries: ["Mention totals by model producer country", "Model producer headquarters country"],
    companies: ["Mention totals by model producer", "Model producer"],
  };
  document.getElementById("totals-title").textContent = labels[state.view][0];
  document.getElementById("totals-name-heading").textContent = labels[state.view][1];
  document.getElementById("totals-origin-heading").hidden = !modelView;
  document.getElementById("totals-context").textContent =
    `These totals belong to the original model-mentions chart above (${labels[state.view][1].toLowerCase()} grouping). Counts cover the full scanned corpus and include citations; a mention does not establish model use.`;
  const rows = state.view === "variants"
    ? state.summary.variants
    : state.view === "families"
      ? state.summary.families
      : state.view === "countries"
      ? state.summary.countries
      : state.summary.companies;
  body.innerHTML = rows.map((row) => {
    const origin = ["variants", "families"].includes(state.view)
      ? `${row.company} · ${COUNTRY_NAMES[row.country] || row.country}`
      : "";
    const scanned = state.summary.papers_scanned
      ? (100 * row.papers / state.summary.papers_scanned).toFixed(2)
      : "0";
    const model = (100 * (row.share_of_model_papers || 0)).toFixed(1);
    return `<tr class="${state.hidden.has(row.id) ? "off" : ""}">
      <td>${escapeHtml(nameOf(row.id))}</td>
      <td${modelView ? "" : " hidden"}>${escapeHtml(origin)}</td>
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
    if (["variants", "families"].includes(state.view) && !paper.variants.some((id) => {
      const key = state.view === "families" ? state.summary.variants.find((row) => row.id === id)?.family : id;
      return visible.has(key);
    })) return false;
    if (!query) return true;
    const names = paper.variants.map((id) => {
      const row = state.summary.variants.find((item) => item.id === id);
      return `${row?.label || id} ${row?.family || ""} ${row?.company || ""}`;
    }).join(" ");
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
    document.querySelectorAll("[data-rate]").forEach((item) => {
      item.classList.toggle("on", item === button);
      item.setAttribute("aria-pressed", String(item === button));
    });
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
  buildFamilies();
  render();
}).catch((error) => {
  document.getElementById("status").textContent = `Could not load site data: ${error}`;
});
