(async () => {
  const [S, F] = await Promise.all([UI.get("/api/summary"), UI.get("/api/fleet")]);
  const cells = S.cells;
  const ret = Object.fromEntries(S.retirement.map((r) => [r.cell_id, r]));

  // ---------- headline figures
  const soh = S.soh, rul = S.rul, sl = S.second_life;
  document.getElementById("figures").innerHTML = [
    [UI.num(S.data.cycles), "Cycles analysed", `${S.data.cells} cells, ${UI.num(S.data.outliers_removed)} interrupted cycles removed`],
    [`${(soh.nasa.rmse * 100).toFixed(1)}<small>%</small> / ${(soh.calce.rmse * 100).toFixed(1)}<small>%</small>`,
     "SOH error (RMSE)", "NASA / CALCE, on cells never seen in training"],
    [`${UI.num(rul.nasa.mae_cycles)} / ${UI.num(rul.calce.mae_cycles)}`, "RUL error, cycles",
     `life to 80% is ${UI.num(rul.nasa.mean_life)} / ${UI.num(rul.calce.mean_life)} cycles`],
    [`${UI.num(sl.agreement * 100)}<small>%</small>`, "Grades match lab truth",
     `${UI.num(sl.agreement_high_conf * 100)}% when confidence is high`],
    [`${S.passports.valid}<small>/${S.passports.issued}</small>`, "Passports verified",
     `${UI.num(S.passports.events)} signed events`],
  ].map(([v, k, d]) => `<div class="fig"><div class="v">${v}</div><div class="k">${k}</div><div class="d">${d}</div></div>`).join("");

  // ---------- how it works (real numbers from the pipeline)
  document.getElementById("steps").innerHTML = [
    ["Ingest", `${UI.num(S.data.cycles)} cycles`, "from 8 real cells (NASA, CALCE)"],
    ["Clean", `${UI.num(S.data.outliers_removed)} removed`, "interrupted cycles, Hampel filter"],
    ["Estimate health", `${(soh.nasa.rmse * 100).toFixed(1)}% / ${(soh.calce.rmse * 100).toFixed(1)}%`, "SOH error from charging data only"],
    ["Predict life", `${UI.num(rul.nasa.mae_cycles)} / ${UI.num(rul.calce.mae_cycles)} cycles`, "error in remaining-life forecasts"],
    ["Decide second life", `${UI.num(sl.agreement * 100)}% match`, "AI grade vs lab grade, A to D"],
    ["Sign the passport", `${S.passports.valid}/${S.passports.issued} verified`, `${UI.num(S.passports.events)} Ed25519-signed events`],
  ].map(([k, v, d]) => `<li><span class="step-k">${k}</span><b>${v}</b><span class="step-d">${d}</span></li>`).join("");

  // ---------- cells table
  document.getElementById("cellRows").innerHTML = cells.map((c) => `
    <tr class="link" tabindex="0" data-cell="${c.cell_id}">
      <td><span class="seg-dot" style="display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:8px;background:${UI.cellColor(c.cell_id)}"></span><b>${c.cell_id}</b></td>
      <td>${c.dataset.toUpperCase()}</td><td class="num">${UI.num(c.cycles)}</td>
      <td class="num">${UI.pct(c.soh_start)}</td><td class="num">${UI.pct(c.soh_end)}</td>
      <td>${UI.gradeChip(c.grade)}</td><td>${UI.esc(c.application || "–")}</td>
      <td>${UI.statusChip(c.status)}</td><td class="num">${c.events}</td>
      <td>${UI.verdict(c.passport_valid, "Verified", "Broken")}</td></tr>`).join("");
  document.querySelectorAll("tr[data-cell]").forEach((tr) => {
    const go = () => (location.href = `/cells?cell=${tr.dataset.cell}`);
    tr.addEventListener("click", go);
    tr.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  });

  function drawBand() {
    const order = cells.map((c) => c.cell_id).reverse();      // NASA on top
    const ink = UI.css("--ink"), ink2 = UI.css("--ink-2");
    const zone = (x0, x1, v) => ({ type: "rect", xref: "x", yref: "paper", x0, x1, y0: 0, y1: 1,
      fillcolor: UI.css(v), line: { width: 0 }, layer: "below" });
    const traces = [];
    const annotations = [
      { x: 92, y: 1.06, xref: "x", yref: "paper", text: "<b>First life</b>", showarrow: false, font: { color: UI.css("--zone-first-ink"), size: 13 } },
      { x: 70, y: 1.06, xref: "x", yref: "paper", text: "<b>Second-life window</b>", showarrow: false, font: { color: UI.css("--zone-second-ink"), size: 13 } },
      { x: 35, y: 1.06, xref: "x", yref: "paper", text: "<b>Recycling</b>", showarrow: false, font: { color: UI.css("--zone-end-ink"), size: 13 } },
    ];
    cells.forEach((c) => {
      const r = ret[c.cell_id];
      traces.push({ x: [c.soh_start * 100, c.soh_end * 100], y: [c.cell_id, c.cell_id], mode: "lines",
        line: { color: ink, width: 3 }, hoverinfo: "skip", showlegend: false });
      traces.push({ x: [c.soh_start * 100], y: [c.cell_id], mode: "markers", showlegend: false,
        marker: { size: 10, color: UI.css("--surface"), line: { color: ink, width: 2 } },
        hovertemplate: `<b>${c.cell_id}</b><br>First cycle: SOH %{x:.1f}%<extra></extra>` });
      traces.push({ x: [c.soh_end * 100], y: [c.cell_id], mode: "markers", showlegend: false,
        marker: { size: 11, symbol: "square", color: ink },
        hovertemplate: `<b>${c.cell_id}</b><br>Last cycle (${UI.num(c.cycles)}): SOH %{x:.1f}%<br>Passport status: ${c.status}<extra></extra>` });
      if (r) {
        traces.push({ x: [r.soh_true * 100], y: [c.cell_id], mode: "markers", showlegend: false,
          marker: { size: 20, symbol: "diamond", color: UI.gradeColor(r.grade_pred), line: { color: UI.css("--surface"), width: 2 } },
          hovertemplate: `<b>${c.cell_id}</b> retired at cycle ${r.cycle}<br>AI estimate ${UI.pct(r.soh_est)}<br>Grade ${r.grade_pred}: ${UI.esc(r.application)}<br>Confidence: ${r.confidence}<extra></extra>` });
        annotations.push({ x: r.soh_true * 100, y: c.cell_id, text: `<b>${r.grade_pred}</b>`, showarrow: false,
          font: { color: r.grade_pred === "D" ? "#0d2230" : "#fff", size: 11 } });
      }
      annotations.push({ x: c.soh_end * 100, y: c.cell_id, xshift: 12, xanchor: "left", text: c.status,
        showarrow: false, font: { color: ink2, size: 12 } });
    });
    UI.plot("band", traces, {
      margin: { l: 70, r: 20, t: 30, b: 44 }, hovermode: "closest",
      xaxis: { range: [106, 8], title: { text: "State of health (%)  ← healthier · more aged →" }, dtick: 10,
               ticksuffix: "%", showgrid: false },
      yaxis: { categoryorder: "array", categoryarray: order, showgrid: false, ticks: "", linecolor: "rgba(0,0,0,0)",
               tickfont: { color: ink, size: 13 } },
      shapes: [zone(80, 106, "--zone-first"), zone(60, 80, "--zone-second"), zone(8, 60, "--zone-end"),
               { type: "line", xref: "paper", yref: "y", x0: 0, x1: 1, y0: 3.5, y1: 3.5, line: { color: UI.css("--hair"), width: 1 } }],
      annotations,
    });
  }

  function drawFleet(ds, el) {
    const ids = cells.filter((c) => c.dataset === ds).map((c) => c.cell_id);
    const traces = ids.map((id) => ({ x: F[id].cycle, y: F[id].soh.map((v) => v * 100), name: id, mode: "lines",
      line: { color: UI.cellColor(id), width: 1.6 }, hovertemplate: `${id}<br>cycle %{x}<br>SOH %{y:.1f}%<extra></extra>` }));
    const maxX = Math.max(...ids.map((id) => F[id].cycle.at(-1)));
    const line = (y, c) => ({ type: "line", xref: "paper", x0: 0, x1: 1, y0: y, y1: y, line: { color: c, width: 1, dash: "dash" } });
    UI.plot(el, traces, {
      yaxis: { title: { text: "SOH (%)" }, ticksuffix: "%" }, xaxis: { title: { text: "Cycle" }, range: [0, maxX * 1.12] },
      shapes: [line(80, UI.css("--zone-first-ink")), line(60, UI.css("--zone-end-ink"))],
      annotations: [
        { xref: "paper", x: 1, y: 80, text: "80% retire", showarrow: false, xanchor: "right", yanchor: "bottom", font: { size: 11, color: UI.css("--zone-first-ink") } },
        { xref: "paper", x: 1, y: 60, text: "60% recycle", showarrow: false, xanchor: "right", yanchor: "bottom", font: { size: 11, color: UI.css("--zone-end-ink") } },
        ...UI.dodge(ids.map((id) => ({ x: F[id].cycle.at(-1), y: F[id].soh_smooth.at(-1) * 100, text: id })), ds === "nasa" ? 2.6 : 5)
          .map((a) => ({ ...a, showarrow: false, xanchor: "left", xshift: 6, font: { size: 11, color: UI.css("--ink-2") } })),
      ],
    });
  }

  // ---------- hero: the fleet draining through its recorded life
  const fleetEl = document.getElementById("fleet");
  const stageOf = (s) => (s >= 0.8 ? ["first", "First life"] : s >= 0.6 ? ["second", "Second life"] : ["end", "Recycling"]);
  fleetEl.innerHTML = cells.map((c) => `
    <li data-cell="${c.cell_id}">
      <span class="fid">${c.cell_id}<small>${c.dataset.toUpperCase()}</small></span>
      <span class="glyph" aria-hidden="true"><span class="fill"></span><span class="mark80"></span><span class="mark60"></span></span>
      <span class="fsoh"></span>
      <span class="fstage"></span>
      <span class="fgrade"></span>
    </li>`).join("");
  const rows = [...fleetEl.children];
  const scrub = document.getElementById("lifeScrub"), out = document.getElementById("lifeOut");
  function setLife(t) {
    out.textContent = `${Math.round(t * 100)}%`;
    rows.forEach((li) => {
      const id = li.dataset.cell, s = F[id].soh_smooth, cyc = F[id].cycle;
      const i = Math.min(s.length - 1, Math.round(t * (s.length - 1)));
      const soh = s[i], [stage, label] = stageOf(soh), r = ret[id];
      li.dataset.stage = stage;
      li.querySelector(".fill").style.width = `${Math.max(0, Math.min(1, soh / 1.05)) * 100}%`;
      li.querySelector(".fsoh").textContent = `${(soh * 100).toFixed(1)}%`;
      li.querySelector(".fstage").textContent = `${label} · cycle ${cyc[i]}`;
      li.querySelector(".fgrade").innerHTML = r && cyc[i] >= r.cycle ? UI.gradeChip(r.grade_pred) : "";
    });
  }
  let anim = null;
  function play() {
    cancelAnimationFrame(anim);
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) { scrub.value = 1000; setLife(1); return; }
    const t0 = performance.now(), dur = 5200;
    const step = (now) => {
      const t = Math.min(1, (now - t0) / dur);
      scrub.value = Math.round(t * 1000); setLife(t);
      if (t < 1) anim = requestAnimationFrame(step);
    };
    anim = requestAnimationFrame(step);
  }
  scrub.addEventListener("input", () => { cancelAnimationFrame(anim); setLife(scrub.value / 1000); });
  document.getElementById("replay").addEventListener("click", play);
  setLife(1);
  play();

  const draw = () => { drawBand(); drawFleet("nasa", "fleetNasa"); drawFleet("calce", "fleetCalce"); };
  draw();
  UI.onTheme(draw);
})();
