(async () => {
  const CELLS = { nasa: ["B0005", "B0006", "B0007", "B0018"], calce: ["CS2_35", "CS2_36", "CS2_37", "CS2_38"] };
  let current = new URLSearchParams(location.search).get("cell") || "B0005";
  let D = null;

  function picker() {
    for (const [ds, el] of [["nasa", "pickNasa"], ["calce", "pickCalce"]]) {
      document.getElementById(el).innerHTML = CELLS[ds].map((id) =>
        `<button class="seg" type="button" data-cell="${id}" aria-pressed="${id === current}">
           <span class="dot" style="background:${UI.cellColor(id)}"></span>${id}</button>`).join("");
    }
    document.querySelectorAll("button[data-cell]").forEach((b) => b.addEventListener("click", () => load(b.dataset.cell)));
  }

  async function load(id) {
    current = id;
    history.replaceState(null, "", `?cell=${id}`);
    picker();
    D = await UI.get(`/api/cell/${id}`);
    draw();
  }

  function draw() {
    const s = D.series, e = D.estimate, col = UI.cellColor(D.cell_id);
    const ink2 = UI.css("--ink-2"), muted = UI.css("--muted");
    const decRet = D.decisions.find((d) => Math.abs(d.retire_soh_level - 0.8) < 1e-6);
    document.getElementById("cellTitle").textContent = `Cell ${D.cell_id}`;
    document.getElementById("cellLede").textContent =
      `${D.dataset.toUpperCase()} cell, rated ${D.rated_capacity_ah} Ah, ${s.cycle.length} cycles. SOH estimated by ${D.soh_model} trained on the other three cells of its dataset; this cell was never seen during training.`;

    const m = D.metrics;
    document.getElementById("cellFigures").innerHTML = [
      [`${(m.soh.rmse * 100).toFixed(2)}<small>%</small>`, "SOH error (RMSE)", `max error ${(m.soh.max_abs * 100).toFixed(1)}%-points`],
      [`${UI.num(m.soh_coverage * 100)}<small>%</small>`, "Inside 95% interval", "share of cycles covered by the band"],
      [m.rul_mae == null ? "–" : UI.num(m.rul_mae), "RUL error, cycles", "mean error before 80% is reached"],
      [decRet ? UI.gradeChip(decRet.grade_pred) : "–", "Grade at 80%", decRet ? `${UI.esc(decRet.application)}, ${decRet.confidence} confidence` : "never retired"],
      [`${UI.num(s.soh_raw.filter((_, i) => s.is_outlier[i]).length)}`, "Cycles removed", "interrupted or partial discharges"],
    ].map(([v, k, d]) => `<div class="fig"><div class="v">${v}</div><div class="k">${k}</div><div class="d">${d}</div></div>`).join("");

    // ---- SOH
    const outX = [], outY = [];
    s.cycle.forEach((c, i) => { if (s.is_outlier[i]) { outX.push(c); outY.push(s.soh_raw[i] * 100); } });
    const hline = (y, c, t) => ({ type: "line", xref: "paper", x0: 0, x1: 1, y0: y, y1: y, line: { color: c, width: 1, dash: "dash" } });
    UI.plot("sohChart", [
      { x: e.cycle.concat(e.cycle.slice().reverse()), y: e.soh_hi.map((v) => v * 100).concat(e.soh_lo.map((v) => v * 100).reverse()),
        fill: "toself", fillcolor: col + "2e", line: { width: 0 }, name: "95% interval", hoverinfo: "skip" },
      { x: s.cycle, y: s.soh.map((v) => v * 100), name: "Measured (cleaned)", mode: "lines",
        line: { color: UI.css("--ink"), width: 1.3 }, hovertemplate: "cycle %{x}<br>measured %{y:.1f}%<extra></extra>" },
      { x: e.cycle, y: e.soh_pred.map((v) => v * 100), name: `AI estimate (${D.soh_model})`, mode: "lines",
        line: { color: col, width: 2 }, customdata: e.soh_lo.map((lo, i) => [lo * 100, e.soh_hi[i] * 100]),
        hovertemplate: "cycle %{x}<br>estimate %{y:.1f}%<br>95%: %{customdata[0]:.1f} to %{customdata[1]:.1f}%<extra></extra>" },
      { x: outX, y: outY, name: "Removed cycles", mode: "markers", marker: { color: muted, size: 7, symbol: "x-thin", line: { width: 1.6, color: muted } },
        hovertemplate: "cycle %{x}<br>raw %{y:.1f}% (interrupted)<extra></extra>" },
    ], {
      yaxis: { title: { text: "SOH (%)" }, ticksuffix: "%" }, xaxis: { title: { text: "Cycle" } }, hovermode: "x unified",
      shapes: [hline(80, UI.css("--zone-first-ink")), hline(60, UI.css("--zone-end-ink"))],
      annotations: [
        { xref: "paper", x: 1, y: 80, text: "80%: retire from first life", showarrow: false, xanchor: "right", yanchor: "bottom", font: { size: 11, color: UI.css("--zone-first-ink") } },
        { xref: "paper", x: 1, y: 60, text: "60%: recycle", showarrow: false, xanchor: "right", yanchor: "bottom", font: { size: 11, color: UI.css("--zone-end-ink") } }],
    });

    // ---- RUL
    const rulPlot = (el, r, label) => {
      if (!r.cycle || !r.cycle.length) {
        document.getElementById(el).innerHTML = `<p class="empty">This cell never reaches ${label} in the test data, so there is no ground truth to compare against.</p>`;
        return;
      }
      const traces = [];
      if (r.rul_gbr && r.rul_gbr.some((v) => v != null)) {
        traces.push({ x: r.cycle.concat(r.cycle.slice().reverse()), y: r.rul_gbr_hi.concat(r.rul_gbr_lo.slice().reverse()),
          fill: "toself", fillcolor: col + "2e", line: { width: 0 }, name: "80% band", hoverinfo: "skip" });
      }
      traces.push({ x: r.cycle, y: r.rul_true, name: "True", mode: "lines", line: { color: UI.css("--ink"), width: 1.6 },
        hovertemplate: "cycle %{x}<br>true %{y:.0f} cycles left<extra></extra>" });
      if (r.rul_gbr && r.rul_gbr.some((v) => v != null))
        traces.push({ x: r.cycle, y: r.rul_gbr, name: "Quantile GBR", mode: "lines", line: { color: col, width: 2 },
          hovertemplate: "cycle %{x}<br>predicted %{y:.0f} cycles<extra></extra>" });
      const top = Math.max(...r.rul_true) * 1.6;
      traces.push({ x: r.cycle, y: r.rul_fade.map((v) => Math.min(v, top)), name: "Fade-model baseline", mode: "lines",
        line: { color: muted, width: 1.2, dash: "dot" }, hovertemplate: "cycle %{x}<br>fade model %{y:.0f}<extra></extra>" });
      UI.plot(el, traces, { yaxis: { title: { text: "Cycles left" }, range: [0, top] }, xaxis: { title: { text: "Prediction cycle" } }, hovermode: "x unified" });
    };
    rulPlot("rul80", D.rul80, "80%");
    rulPlot("rul60", D.rul60, "60%");

    // ---- health indicators
    const small = (el, y, title, fmt) => UI.plot(el, [{ x: s.cycle, y, mode: "lines", line: { color: col, width: 1.6 },
      hovertemplate: `cycle %{x}<br>%{y:${fmt}}<extra></extra>`, showlegend: false }],
      { margin: { l: 48, r: 10, t: 6, b: 36 }, xaxis: { title: { text: "Cycle" } }, yaxis: { title: { text: title } } });
    small("hi1", s.cc_charge_time_s.map((v) => v / 60), "minutes", ".0f");
    small("hi2", s.charge_v_rise_s.map((v) => v / 60), "minutes", ".0f");
    small("hi3", s.cv_charge_time_s.map((v) => v / 60), "minutes", ".0f");
    small("hi4", s.resistance_growth, "× fresh", ".3f");

    // ---- decisions
    document.getElementById("decRows").innerHTML = D.decisions.map((d) => `
      <tr><td class="num">${UI.pct(d.retire_soh_level, 1)}</td><td class="num">${d.cycle}</td>
      <td class="num">${UI.pct(d.soh_true)}</td><td class="num">${UI.pct(d.soh_est)}</td><td class="num">${UI.pct(d.soh_lo)}</td>
      <td class="num">×${UI.num(d.resistance_growth, 2)}</td>
      <td class="num">${d.cycles_to_floor_true == null ? "–" : UI.num(d.cycles_to_floor_true)}</td>
      <td class="num">${d.cycles_to_floor_pred == null ? "–" : UI.num(d.cycles_to_floor_pred)}</td>
      <td>${UI.gradeChip(d.grade_pred)}</td><td>${UI.gradeChip(d.grade_true)}</td>
      <td>${d.grade_pred === d.grade_true ? "" : `<span class="bad" title="AI grade differs from lab grade">${UI.ICON.bad}</span>`} ${d.confidence === "low" ? `<span class="warn">${UI.ICON.warn}low</span>` : "high"}</td></tr>`).join("");
  }

  UI.onTheme(() => { if (D) { picker(); draw(); } });
  load(current);
})();
