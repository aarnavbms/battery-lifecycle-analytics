(async () => {
  const [M, S] = await Promise.all([UI.get("/api/models"), UI.get("/api/summary")]);
  let fs = "full";
  const DS = [["nasa", "NASA", "--s1"], ["calce", "CALCE", "--s2"]];
  const LABEL = { cc_charge_time_s: "CC charge time", cv_charge_time_s: "CV charge time", charge_v_rise_s: "3.9-4.2 V rise",
                  resistance_ohm: "Resistance", cycle: "Cycle count", cc_charge_time_rel: "CC charge time",
                  cv_charge_time_rel: "CV charge time", charge_v_rise_rel: "3.9-4.2 V rise", resistance_rel: "Resistance",
                  temp_rise_c: "Temperature rise" };

  document.querySelectorAll("button[data-fs]").forEach((b) => b.addEventListener("click", () => {
    fs = b.dataset.fs;
    document.querySelectorAll("button[data-fs]").forEach((x) => x.setAttribute("aria-pressed", x === b));
    drawBars();
  }));

  function drawBars() {
    const models = Object.keys(M.soh.nasa.summary);
    const src = (ds) => (fs === "full" ? M.soh[ds].summary : M.soh[ds].partial_charge.summary);
    document.getElementById("fsNote").textContent = fs === "full"
      ? "Inputs: CC and CV charge time, 3.9-4.2 V rise time, resistance, cycle count."
      : "Inputs without CC charge time, as when a charge starts part-way. Errors rise but stay usable for tree models.";
    UI.plot("sohBars", DS.map(([ds, name, c]) => ({
      type: "bar", name, x: models, y: models.map((m) => src(ds)[m].rmse * 100), marker: { color: UI.css(c) },
      text: models.map((m) => (src(ds)[m].rmse * 100).toFixed(2)), textposition: "outside", cliponaxis: false,
      textfont: { color: UI.css("--ink-2"), size: 11 },
      hovertemplate: `${name} %{x}<br>RMSE %{y:.2f} %-points<extra></extra>` })),
      { barmode: "group", bargap: 0.3, bargroupgap: 0.08, yaxis: { title: { text: "RMSE (SOH %-points)" }, rangemode: "tozero" },
        margin: { t: 30 } });
  }

  // per-cell table
  const rows = [];
  for (const [ds] of DS) {
    const pm = M.soh[ds].primary_model;
    for (const [cid, v] of Object.entries(M.soh[ds].per_cell)) {
      const m = v[pm];
      rows.push(`<tr><td><b>${cid}</b></td><td>${pm}</td><td class="num">${(m.rmse * 100).toFixed(2)}%</td>
        <td class="num">${(m.mae * 100).toFixed(2)}%</td><td class="num">${(m.max_abs * 100).toFixed(1)}%</td>
        <td class="num">${UI.pct(M.soh[ds].coverage_per_cell[cid], 1)}</td></tr>`);
    }
  }
  document.getElementById("perCell").innerHTML = rows.join("");

  function drawImp() {
    const feats = Object.keys(M.soh.nasa.feature_importance_gbr);
    UI.plot("imp", DS.map(([ds, name, c]) => ({
      type: "bar", orientation: "h", name, y: feats.map((f) => LABEL[f] || f),
      x: feats.map((f) => M.soh[ds].feature_importance_gbr[f] * 100), marker: { color: UI.css(c) },
      hovertemplate: `${name} %{y}: %{x:.1f}%<extra></extra>` })),
      { barmode: "group", margin: { l: 120, t: 26, b: 36 }, xaxis: { title: { text: "Importance (%)" } }, yaxis: { autorange: "reversed" } });
  }

  function drawCorr() {
    const C = S.correlations;
    const feats = ["cc_charge_time_rel", "charge_v_rise_rel", "cv_charge_time_rel", "resistance_rel", "cycle"];
    UI.plot("corr", DS.map(([ds, name, c]) => ({
      type: "bar", orientation: "h", name, y: feats.map((f) => LABEL[f]), x: feats.map((f) => C[ds][f]),
      marker: { color: UI.css(c) }, hovertemplate: `${name} %{y}: r = %{x:.2f}<extra></extra>` })),
      { barmode: "group", margin: { l: 120, t: 26, b: 36 }, xaxis: { range: [-1, 1], title: { text: "Correlation with SOH" }, zeroline: true, zerolinecolor: UI.css("--axis") },
        yaxis: { autorange: "reversed" } });
  }

  // RUL
  const METHODS = [["linear_trend", "Linear trend"], ["fade_model", "Empirical fade model"], ["quantile_gbr", "Quantile GBR"]];
  function drawRul() {
    UI.plot("rulBars", DS.map(([ds, name, c]) => {
      const fl = M.rul[ds].first_life;
      return { type: "bar", name, x: METHODS.map((m) => m[1]),
        y: METHODS.map(([k]) => (fl[k].mae / fl.mean_life_to_threshold) * 100), marker: { color: UI.css(c) },
        text: METHODS.map(([k]) => `${((fl[k].mae / fl.mean_life_to_threshold) * 100).toFixed(0)}%`),
        textposition: "outside", cliponaxis: false, textfont: { color: UI.css("--ink-2"), size: 11 },
        hovertemplate: `${name} %{x}<br>MAE = %{y:.1f}% of life<extra></extra>` };
    }), { barmode: "group", bargap: 0.35, margin: { t: 30 }, yaxis: { title: { text: "MAE / mean life (%)" }, rangemode: "tozero" } });
  }
  const rr = [];
  for (const [ds, name] of DS) {
    const fl = M.rul[ds].first_life;
    for (const [k, label] of METHODS) {
      const m = fl[k];
      rr.push(`<tr><td>${name}</td><td>${label}</td><td class="num">${UI.num(m.mae, 1)}</td>
        <td class="num">${UI.num(m["25pct_life_mae"])}</td><td class="num">${UI.num(m["50pct_life_mae"])}</td>
        <td class="num">${UI.num(m["75pct_life_mae"])}</td><td class="num">${m.coverage_cqr_80 == null ? "–" : UI.pct(m.coverage_cqr_80, 1)}</td></tr>`);
    }
  }
  document.getElementById("rulRows").innerHTML = rr.join("");

  // explainability: permutation importance on held-out cells
  let X = null;
  try { X = await UI.get("/api/v1/explain"); } catch (e) { /* optional */ }
  function drawPerm() {
    if (!X) { document.getElementById("perm").innerHTML = '<p class="empty">Run <code>python -m batterylife explain</code> to compute this.</p>'; return; }
    UI.plot("perm", DS.map(([ds, name, c]) => ({
      type: "bar", orientation: "h", name: `${name} (${X.datasets[ds].model})`, y: X.features.map((f) => LABEL[f] || f),
      x: X.features.map((f) => X.datasets[ds].mean[f]), marker: { color: UI.css(c) },
      error_x: { type: "data", array: X.features.map((f) => X.datasets[ds].spread_across_cells[f]), color: UI.css("--ink-2"), thickness: 1, width: 3 },
      hovertemplate: `${name} %{y}<br>error rises by %{x:.2f} points<extra></extra>` })),
      { barmode: "group", margin: { l: 120, t: 26, b: 40 }, xaxis: { title: { text: "Rise in RMSE when shuffled (SOH %-points)" }, rangemode: "tozero" }, yaxis: { autorange: "reversed" } });
  }
  if (X) {
    const top = (ds) => LABEL[X.datasets[ds].top_signal].toLowerCase(), v = (ds) => X.datasets[ds].mean[X.datasets[ds].top_signal].toFixed(1);
    document.getElementById("permText").textContent = `For the NASA cells the model leans most on ${top("nasa")} (error rises by ${v("nasa")} points when it is shuffled). For the CALCE cells it is ${top("calce")} (${v("calce")} points). Whiskers show the spread across the four held-out cells.`;
  }

  const draw = () => { drawBars(); drawPerm(); drawImp(); drawCorr(); drawRul(); };
  draw();
  UI.onTheme(draw);
})();
