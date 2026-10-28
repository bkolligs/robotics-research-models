const LIFE_COLORS = ["#2258c3", "#df493f", "#178066", "#8b58a1", "#b36b1e", "#16899b", "#b6487d", "#718d21", "#6d6f91", "#7b5540", "#30669d", "#bb8062"];
const lifecycleState = { summary: null, axis: "age", metric: "count", smooth: "3", selected: new Set(["pi0", "pi05", "rt2", "openvla", "openvla_oft", "diffusion_policy"]) };

function lifecycleValue(row) {
  if (lifecycleState.metric === "count") return lifecycleState.smooth === "3" ? row.window_monthly_papers : row.papers;
  return lifecycleState.smooth === "3" ? row.window_share : row.share;
}

function renderLifecycle() {
  const summary = lifecycleState.summary;
  const selected = summary.models.filter((m) => lifecycleState.selected.has(m.model_id));
  const series = new Map(selected.map((m) => [m.model_id, summary.monthly.filter((r) => r.model_id === m.model_id)]));
  const color = (mid) => LIFE_COLORS[summary.models.findIndex((m) => m.model_id === mid) % LIFE_COLORS.length];
  const calendarIndex = (month) => { const [year, number] = month.split("-").map(Number); return year*12+number-1; };
  const position = (row) => lifecycleState.axis === "age" ? row.months_since_release : calendarIndex(row.month);
  const all = [...series.values()].flat();
  const minX = lifecycleState.axis === "age" || !all.length ? 0 : Math.min(...all.map(position));
  const maxX = Math.max(minX+1, ...all.map(position));
  const peaks = new Map([...series].map(([mid, rows]) => [mid, Math.max(0, ...rows.map(lifecycleValue).filter((v) => v !== null))]));
  const value = (row) => {
    const raw = lifecycleValue(row);
    if (raw === null) return null;
    if (lifecycleState.metric === "peak") return peaks.get(row.model_id) ? 100*raw/peaks.get(row.model_id) : null;
    return lifecycleState.metric === "share" ? 100*raw : raw;
  };
  const rawMax = Math.max(1, ...all.map(value).filter((v) => v !== null));
  const magnitude = 10**Math.floor(Math.log10(rawMax));
  const maxY = lifecycleState.metric === "peak" ? 100 : Math.ceil(rawMax/magnitude*2)/2*magnitude;
  const width = 1050, height = 450, pad = { l: 68, r: 25, t: 32, b: 65 };
  const x = (v) => pad.l+(width-pad.l-pad.r)*(v-minX)/Math.max(1,maxX-minX);
  const y = (v) => pad.t+(height-pad.t-pad.b)*(1-v/maxY);
  let marks = "";
  for (let i=0; i<=5; i++) {
    const tick=maxY*i/5;
    marks += `<line x1="${pad.l}" x2="${width-pad.r}" y1="${y(tick)}" y2="${y(tick)}" stroke="#e4ddd2"/><text x="${pad.l-9}" y="${y(tick)+4}" text-anchor="end" font-size="12" fill="#5c564c">${tick.toFixed(maxY<10?1:0)}${lifecycleState.metric === "count" ? "" : "%"}</text>`;
  }
  const step = Math.max(1, Math.ceil((maxX-minX)/9));
  const ticks=[];
  for (let tick=minX; tick<=maxX; tick+=step) ticks.push(tick);
  if (ticks[ticks.length-1] !== maxX) {
    if (maxX-ticks[ticks.length-1] < step*.6) ticks.pop();
    ticks.push(maxX);
  }
  for (const tick of ticks) {
    const label = lifecycleState.axis === "age" ? tick : `${Math.floor(tick/12)}-${String(tick%12+1).padStart(2,"0")}`;
    marks += `<text x="${x(tick)}" y="${height-35}" text-anchor="middle" font-size="12" fill="#5c564c">${label}</text>`;
  }
  for (const model of selected) {
    let path = "", drawing = false;
    const rows = series.get(model.model_id);
    for (const row of rows) {
      const v = value(row);
      if (v === null) { drawing = false; continue; }
      path += `${drawing?"L":"M"}${x(position(row)).toFixed(2)},${y(v).toFixed(2)} `;
      drawing = true;
    }
    marks += `<path d="${path}" fill="none" stroke="${color(model.model_id)}" stroke-width="2.5"/>`;
    for (const row of rows) {
      const v=value(row);
      if (v === null) continue;
      const detail = `${model.label} · ${row.month} · month ${row.months_since_release} after release · ${row.papers} evaluations this month / ${row.evaluation_papers} papers evaluating any tracked model. ${row.window_months}-month window: ${row.window_papers} / ${row.window_evaluation_papers} (${row.window_share === null ? "—" : (100*row.window_share).toFixed(1)+"%"}).`;
      marks += `<circle class="trend-point" tabindex="0" cx="${x(position(row))}" cy="${y(v)}" r="3.5" fill="${color(model.model_id)}" data-lifecycle-detail="${escapeAttr(detail)}" aria-label="${escapeAttr(detail)}"><title>${escapeHtml(detail)}</title></circle>`;
    }
  }
  const metricLabel = lifecycleState.metric === "count" ? (lifecycleState.smooth === "3" ? "Evaluations per month, trailing average" : "Evaluation papers per month") : lifecycleState.metric === "peak" ? "Share relative to each model’s observed peak (100%)" : "Share of papers evaluating any tracked model";
  const axisLabel = lifecycleState.axis === "age" ? "Calendar months after release reference (release month = 0)" : "Paper first-submission month";
  document.getElementById("lifecycle-chart").innerHTML = selected.length ?
    `<div class="stack-scroll"><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Baseline usage lifecycle by release age or calendar month"><text x="${pad.l}" y="17" font-size="12" fill="#5c564c">${escapeHtml(metricLabel)}</text>${marks}<text x="${width/2}" y="${height-7}" text-anchor="middle" font-size="12" fill="#5c564c">${escapeHtml(axisLabel)}</text></svg></div>` : '<p class="note">Select at least one model below to compare usage.</p>';
  document.getElementById("lifecycle-method-counts").textContent =
    `${summary.models.length} releases with sourced dates; ${summary.eligible_post_release_pairs.toLocaleString()} confirmed post-release evaluations through ${summary.through}. Each month’s denominator counts distinct papers evaluating any tracked model (${summary.source_evaluation_papers.toLocaleString()} such papers overall). ${summary.excluded_pre_release_pairs} pre-release comparisons and ${summary.excluded_introduction_pairs} introducing-paper comparisons are excluded from the model curves.`;
  document.getElementById("lifecycle-key").innerHTML = selected.map((m) => `<span><i class="swatch" style="background:${color(m.model_id)}"></i>${escapeHtml(m.label)}</span>`).join("");
  document.getElementById("lifecycle-legend").innerHTML = selectedFirst(summary.models, (m) => lifecycleState.selected.has(m.model_id), (m) => m.evaluations).map((m) =>
    `<button type="button" data-lifecycle-model="${escapeAttr(m.model_id)}" aria-pressed="${lifecycleState.selected.has(m.model_id)}" class="${lifecycleState.selected.has(m.model_id)?"":"off"}"><span class="swatch" style="background:${color(m.model_id)}"></span><span><strong>${escapeHtml(m.label)}</strong><small>Released ${m.released} · ${m.evaluations} later evaluations</small></span></button>`
  ).join("");
  document.getElementById("lifecycle-table-body").innerHTML = selected.map((m) => {
    const latest=m.latest_window, peak=m.supported_peak;
    return `<tr><td>${escapeHtml(m.label)}<small>${m.evaluations} total qualifying papers</small></td><td><a href="${escapeAttr(m.source)}" target="_blank" rel="noopener">${m.released}</a></td><td>${m.last_use_month||"None observed"}${m.last_use_age_months === null ? "" : ` <small>(${m.last_use_age_months} months after release)</small>`}</td><td>${latest.window_papers ?? "—"} / ${latest.window_evaluation_papers ?? "—"} (${latest.window_share === null ? "—" : (100*latest.window_share).toFixed(1)+"%"})</td><td>${peak ? `${(100*peak.window_share).toFixed(1)}% · ${peak.month}` : "Insufficient volume"}</td></tr>`;
  }).join("");
  document.getElementById("lifecycle-population").textContent = `${summary.models.length} releases · ${summary.eligible_post_release_pairs.toLocaleString()} post-release evaluations · through ${summary.through}.`;
  const older=selected.filter((m) => m.missing_early_history).map((m) => m.label);
  document.getElementById("lifecycle-observation").textContent =
    `Every curve ends at the observed corpus boundary (${summary.through}). Its endpoint is not a retirement date.` +
    (older.length ? ` The early history of ${older.join(", ")} precedes this corpus (${summary.corpus_start}) and is unobserved.` : "");
  document.querySelectorAll("[data-lifecycle-model]").forEach((button) => button.addEventListener("click", () => {
    const mid=button.dataset.lifecycleModel;
    if (lifecycleState.selected.has(mid)) lifecycleState.selected.delete(mid); else lifecycleState.selected.add(mid);
    renderLifecycle();
  }));
  document.querySelectorAll("[data-lifecycle-detail]").forEach((point) => {
    for (const event of ["mouseenter","focus","click"]) point.addEventListener(event, () => {
      document.getElementById("lifecycle-detail").textContent=point.dataset.lifecycleDetail;
    });
  });
}

fetch("analysis/baseline-lifecycle/summary.json").then((response) => {
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
}).then((summary) => {
  lifecycleState.summary=summary;
  state.lifecycle = summary;
  if (state.summary) renderStatus();
  document.getElementById("lifecycle-section").hidden=false;
  for (const [id,key] of [["lifecycle-axis","axis"],["lifecycle-metric","metric"],["lifecycle-smooth","smooth"]]) {
    document.getElementById(id).addEventListener("change", (event) => { lifecycleState[key]=event.target.value; renderLifecycle(); });
  }
  document.getElementById("lifecycle-releases").innerHTML = summary.models.map((m) =>
    `<tr><td>${escapeHtml(m.label)}</td><td>${m.released}</td><td><a href="${escapeAttr(m.source)}" target="_blank" rel="noopener">${escapeHtml(m.kind)}</a></td></tr>`
  ).join("");
  document.getElementById("lifecycle-undated").textContent =
    `Release dates are not yet verified for ${summary.unverified_releases.length} other evaluated model rows (${summary.unverified_releases.map((m) => `${m.label}: ${m.evaluation_pairs}`).join("; ")}). They are omitted from release-aligned curves and retained in the shared evaluation-paper denominator.`;
  renderLifecycle();
}).catch((error) => { console.warn("Baseline lifecycle unavailable",error); });
