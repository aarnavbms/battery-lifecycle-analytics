(async () => {
  const R = await UI.get("/api/reports");
  const el = document.getElementById("reportList");
  if (!R.length) { el.innerHTML = '<li class="empty">Reports are being prepared.</li>'; return; }
  el.innerHTML = R.map((r) => `
    <li class="report">
      <div class="report-week"><span>Week</span><b>${r.week}</b></div>
      <div class="report-body">
        <h3>${UI.esc(r.title)}</h3>
        <p class="report-dates">${UI.esc(r.dates)} · ${UI.esc(r.progress)} complete</p>
        <p>${UI.esc(r.summary)}</p>
      </div>
      <a class="report-pdf" href="reports/${encodeURIComponent(r.file)}" target="_blank" rel="noopener">Open PDF<small>${UI.esc(r.size)}</small></a>
    </li>`).join("");
})();
