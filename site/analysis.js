Promise.all([
  fetch('analysis/summary.json').then(r => { if (!r.ok) throw Error(r.status); return r.json(); }),
  fetch('analysis/date_diagnostics.json').then(r => { if (!r.ok) throw Error(r.status); return r.json(); }),
]).then(([summary, diagnostics]) => {
  const fmt = n => n.toLocaleString();
  document.getElementById('coverage-note').textContent = `${fmt(summary.papers_scanned)} of ${fmt(summary.papers_discovered)} discovered papers scanned. ${fmt(summary.papers_missing_from_snapshot)} lack PDFs in the bulk snapshot. Coverage: ${summary.months[0]} through ${summary.months.at(-1)}.`;
  const flagged = diagnostics.variants.reduce((n, r) => n + r.papers, 0);
  document.getElementById('date-note').textContent = `No release-date gate is applied. ${fmt(flagged)} paper–model pairs predate the taxonomy’s introduction year. Later revisions or ambiguous names may explain these; they have not been excluded.`;
  const body = document.querySelector('#coverage-table tbody');
  for (const row of summary.coverage) {
    const tr = document.createElement('tr');
    for (const value of [row.month, fmt(row.discovered), fmt(row.scanned), fmt(row.unavailable), fmt(row.model_papers), row.share_naming_any_model === null ? 'Unavailable' : `${(100 * row.share_naming_any_model).toFixed(1)}%`]) {
      const td = document.createElement('td'); td.textContent = value; tr.append(td);
    }
    body.append(tr);
  }
  const list = document.getElementById('analysis-downloads');
  for (const [label, file] of [['Coverage', 'coverage.csv'], ...['variant', 'family', 'country', 'company'].flatMap(k => [[`${k} totals`, `${k}_totals.csv`], [`${k} monthly rates`, `${k}_monthly.csv`]])]) {
    const li = document.createElement('li'), a = document.createElement('a');
    a.href = `analysis/${file}`; a.textContent = label; a.download = file; li.append(a); list.append(li);
  }
}).catch(error => { document.getElementById('coverage-note').textContent = `Could not load analysis: ${error.message}`; });
