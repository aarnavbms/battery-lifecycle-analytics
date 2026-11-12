(async () => {
  await UI.ready;
  const $ = (id) => document.getElementById(id);
  const form = $("upForm"), msg = $("upMsg");
  let R = null, picked = null;

  function gate() {
    const ok = UI.can("upload:create");
    $("upGate").hidden = ok;
    $("upRole").textContent = UI.user.role === "public" ? "a public visitor" : UI.ROLE_LABEL[UI.user.role] || UI.user.role;
    form.querySelectorAll("input, select, button").forEach((el) => { el.disabled = !ok; });
  }
  $("upSignIn").addEventListener("click", async () => {
    try { await UI.signIn("assessor"); } catch (e) { msg.textContent = e.message; }
  });
  UI.onUser(gate);
  gate();
  if (UI.isStatic) $("upIssue").closest("label").hidden = true;

  async function run(file, rated, profile) {
    if (!file) { msg.textContent = "Choose a CSV file first, or try a sample."; return; }
    const fd = new FormData();
    fd.append("file", file, file.name);
    fd.append("rated_capacity_ah", rated);
    fd.append("profile", profile);
    fd.append("issue_passports", $("upIssue").checked ? "true" : "false");
    $("upGo").disabled = true;
    msg.textContent = `Assessing ${file.name}…`;
    try {
      R = await UI.upload(fd);
      msg.textContent = `Done: ${R.batteries} ${R.batteries === 1 ? "battery" : "batteries"} from ${UI.num(R.rows)} rows.`;
      picked = R.results[0].cell_id;
      render();
      $("upResult").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) {
      msg.textContent = `Could not assess the file: ${e.message}`;
    } finally { $("upGo").disabled = !UI.can("upload:create"); }
  }
  form.addEventListener("submit", (ev) => { ev.preventDefault(); run($("upFile").files[0], $("upRated").value, $("upProfile").value); });
  document.querySelectorAll("button[data-sample]").forEach((b) => b.addEventListener("click", async () => {
    msg.textContent = "Loading the sample file…";
    try {
      const txt = UI.isStatic ? "" : await (await fetch(`samples/${b.dataset.sample}`)).text();
      $("upRated").value = b.dataset.rated; $("upProfile").value = b.dataset.profile;
      run(new File([txt], b.dataset.sample, { type: "text/csv" }), b.dataset.rated, b.dataset.profile);
    } catch (e) { msg.textContent = "Could not load the sample file."; }
  }));

  const cyc = (r) => {
    const x = r.rul && r.rul.to_60;
    if (!x) return "–";
    if (x.beyond_horizon) return `over ${UI.num(x.cycles)}`;
    return x.lo === x.hi ? UI.num(x.cycles) : `${UI.num(x.lo)} to ${UI.num(x.hi)}`;
  };

  function render() {
    const many = R.results.length > 1;
    $("upResult").hidden = false;
    $("upTitle").textContent = many ? `${R.batteries} batteries, ranked` : `Result for ${R.results[0].cell_id}`;
    $("upSub").textContent = `${R.filename} · rated ${R.rated_capacity_ah} Ah · upload ${R.upload_id}`;
    const reuse = R.grades.A + R.grades.B + R.grades.C;
    $("upFigures").innerHTML = [
      [R.batteries, many ? "Batteries assessed" : "Battery assessed", `${UI.num(R.rows)} cycle rows`],
      [UI.pct(R.mean_soh), many ? "Average health" : "Health now", many ? "state of health across the file" : UI.esc(R.results[0].stage)],
      [`${reuse}<small>/${R.batteries}</small>`, "Fit for a second life", `${R.grades.D} to recycle`],
      [R.low_confidence, "Need a lab test", "grade is uncertain"],
    ].map(([v, k, d]) => `<div class="fig"><div class="v">${v}</div><div class="k">${k}</div><div class="d">${d}</div></div>`).join("");
    $("upFleetRow").hidden = !many;
    $("upRows").innerHTML = R.results.map((r) => `
      <tr class="link" tabindex="0" data-cell="${UI.esc(r.cell_id)}" aria-selected="${r.cell_id === picked}">
        <td class="num">${r.rank}</td><td><b>${UI.esc(r.cell_id)}</b></td>
        <td class="num">${UI.pct(r.soh)} <span class="pm">±${((r.soh - r.soh_lo) * 100).toFixed(1)}</span></td>
        <td class="num">${r.resistance_growth == null ? "–" : `×${UI.num(r.resistance_growth, 2)}`}</td>
        <td class="num">${cyc(r)}</td><td>${UI.gradeChip(r.grade)}</td><td>${UI.esc(r.application)}</td>
        <td>${r.confidence === "high" ? "High" : `<span class="warn">${UI.ICON.warn}Lab test</span>`}</td>
        <td>${r.passport_id ? UI.verdict(r.passport_valid, "Signed", "Invalid") : "–"}</td></tr>`).join("");
    document.querySelectorAll("#upRows tr").forEach((tr) => {
      const go = () => { picked = tr.dataset.cell; render(); };
      tr.addEventListener("click", go);
      tr.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
    });
    $("upFailed").textContent = R.failed.length
      ? `Skipped ${R.failed.length}: ${R.failed.map((f) => `${f.cell_id} (${f.problem})`).join("; ")}.` : "";
    if (many) drawFleet();
    drawCell();
  }

  function drawFleet() {
    const G = ["A", "B", "C", "D"];
    UI.plot("upMap", G.map((g) => {
      const rs = R.results.filter((r) => r.grade === g && r.rul && r.rul.to_60);
      return { type: "scatter", mode: "markers", name: `Grade ${g}`, x: rs.map((r) => r.rul.to_60.cycles), y: rs.map((r) => r.soh * 100),
        text: rs.map((r) => r.cell_id), marker: { size: 13, color: UI.gradeColor(g), line: { color: UI.css("--surface"), width: 2 },
          symbol: ["circle", "square", "diamond", "x"][G.indexOf(g)] },
        hovertemplate: "%{text}<br>SOH %{y:.1f}%<br>%{x:.0f} cycles left<extra>Grade " + g + "</extra>" };
    }), { xaxis: { title: { text: "Forecast cycles left to 60%" }, rangemode: "tozero" }, yaxis: { title: { text: "Health (SOH %)" }, ticksuffix: "%" },
          margin: { t: 30 } });
    UI.plot("upGrades", [{ type: "bar", x: G, y: G.map((g) => R.grades[g]), marker: { color: G.map((g) => UI.gradeColor(g)) },
      text: G.map((g) => R.grades[g]), textposition: "outside", cliponaxis: false, textfont: { color: UI.css("--ink-2") },
      customdata: ["EV re-use", "Grid or home storage", "Backup power", "Recycle"], hovertemplate: "Grade %{x}: %{customdata}<br>%{y} batteries<extra></extra>" }],
      { xaxis: { title: { text: "Grade" }, type: "category" }, yaxis: { title: { text: "Batteries" }, rangemode: "tozero", dtick: 1 }, margin: { t: 30 }, showlegend: false });
  }

  function drawCell() {
    const r = R.results.find((x) => x.cell_id === picked) || R.results[0];
    const s = r.series, col = UI.css("--s1");
    $("upCellTitle").textContent = `${r.cell_id}: health over its recorded life`;
    $("upCellNote").textContent = r.soh_source === "measured"
      ? "Dots are measured capacity over rated capacity; the line is the nine-cycle median. Dashed lines mark 80% and 60%."
      : "Health estimated by the AI model from charging signals. Dashed lines mark 80% and 60%.";
    const tr = [];
    if (s.soh.some((v) => v != null)) tr.push({ x: s.cycle, y: s.soh.map((v) => (v == null ? null : v * 100)), mode: "markers", name: "Measured",
      marker: { size: 4, color: col, opacity: 0.45 }, hovertemplate: "cycle %{x}<br>%{y:.1f}%<extra>measured</extra>" });
    tr.push({ x: s.cycle, y: s.soh_smooth.map((v) => v * 100), mode: "lines", name: "Health (smoothed)", line: { color: col, width: 2.5 },
      hovertemplate: "cycle %{x}<br>%{y:.1f}%<extra>smoothed</extra>" });
    if (s.soh_est) tr.push({ x: s.cycle, y: s.soh_est.map((v) => v * 100), mode: "lines", name: "AI estimate", line: { color: UI.css("--s2"), width: 1.8, dash: "dot" },
      hovertemplate: "cycle %{x}<br>%{y:.1f}%<extra>AI estimate</extra>" });
    const hline = (v, c) => ({ type: "line", xref: "paper", x0: 0, x1: 1, y0: v, y1: v, line: { color: c, width: 1, dash: "dash" } });
    UI.plot("upChart", tr, { xaxis: { title: { text: "Cycle" } }, yaxis: { title: { text: "SOH (%)" }, ticksuffix: "%" }, margin: { t: 30 },
      shapes: [hline(80, UI.css("--zone-first-ink")), hline(60, UI.css("--zone-end-ink"))] });

    const mc = r.model_check, r80 = r.rul && r.rul.to_80;
    const facts = [
      ["Health now", `${UI.pct(r.soh)} (${UI.pct(r.soh_lo)} to ${UI.pct(r.soh_hi)})`],
      ["How it was obtained", UI.esc(r.soh_method)],
      ["Life stage", UI.esc(r.stage)],
      ["Resistance growth", r.resistance_growth == null ? "not in the file" : `×${UI.num(r.resistance_growth, 2)} since the first cycles`],
      ["Cycles left to 80%", r80 ? (r80.cycles === 0 ? "already below 80%" : `${UI.num(r80.lo)} to ${UI.num(r80.hi)}`) : "no forecast"],
      ["Cycles left to 60%", cyc(r)],
      ["Second-life length", r.service_years == null ? "–" : `about ${UI.num(r.service_years, 1)} years in this use`],
      ["Value at pack scale", `${r.value.route}, about USD ${UI.num(r.value.value_usd_pack)} and ${UI.num(r.value.co2_avoided_kg_pack)} kg CO2 avoided per 60 kWh pack`],
    ];
    if (mc) facts.splice(2, 0, ["AI estimate check", `model says ${UI.pct(mc.estimate_now)}; average gap to measured ${(mc.mae * 100).toFixed(2)} points (typical on unseen cells: ${(mc.rmse_on_unseen_cells * 100).toFixed(1)})`]);
    $("upCell").innerHTML = `
      <h3>${UI.gradeChip(r.grade)} ${UI.esc(r.application)}</h3>
      <p class="prose"><b>${UI.esc(r.recommendation)}.</b></p>
      <dl class="kv">${facts.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>
      <p class="note">Why this grade: ${r.reasons.map(UI.esc).join("; ")}.</p>
      ${r.notes.map((n) => `<p class="note">${UI.ICON.warn} ${UI.esc(n)}</p>`).join("")}
      ${r.passport_id ? `<div class="toolbar" style="margin-top:14px">
        <a class="btn" href="passports?id=${encodeURIComponent(r.passport_id)}" data-go-passport="${UI.esc(r.passport_id)}">Open passport</a>
        <button class="ghost" type="button" id="upPdf">Passport PDF with QR code</button>
        <span class="mono small">${UI.esc(r.passport_id)}</span></div>`
        : `<p class="note">${UI.isStatic ? "This hosted copy analyses the file in your browser. Signed passports are issued by the server version of the project." : "No passport was issued for this run."}</p>`}`;
    const pdf = $("upPdf");
    if (pdf) pdf.addEventListener("click", () => UI.openPdf(r.passport_id, "full").catch((e) => { msg.textContent = e.message; }));
  }
  UI.onTheme(() => { if (R) render(); });
})();
