(async () => {
  const D = await UI.get("/api/second-life");
  const G = ["A", "B", "C", "D"];
  const s = D.summary.all;

  document.getElementById("agreeText").textContent =
    `${UI.pct(s.agreement)} of ${s.decisions} decisions match. When the system reports high confidence, ${UI.pct(s.agreement_when_high_confidence)} match, ` +
    `and ${UI.pct(s.errors_flagged_low_confidence, 0)} of its mistakes were already flagged for a lab test.`;

  // ---------- assessor
  const ids = ["soh", "hw", "rg", "cy", "cl"];
  const el = Object.fromEntries(ids.map((i) => [i, document.getElementById(i)]));
  const out = (i, t) => (document.getElementById(`o_${i}`).textContent = t);
  let timer = null;
  function update() {
    if (+el.cl.value > +el.cy.value) el.cl.value = el.cy.value;
    out("soh", UI.pct(+el.soh.value, 1)); out("hw", `±${(+el.hw.value * 100).toFixed(1)}%-points`);
    out("rg", `×${(+el.rg.value).toFixed(2)}`); out("cy", `${el.cy.value} cycles`); out("cl", `${el.cl.value} cycles`);
    clearTimeout(timer);
    timer = setTimeout(run, 120);
  }
  async function run() {
    const box = document.getElementById("verdict");
    try {
      const r = await UI.post("/api/assess", { soh: +el.soh.value, halfwidth: +el.hw.value, resistance_growth: +el.rg.value,
                                               cycles: +el.cy.value, cycles_lo: +el.cl.value });
      const v = r.value;
      box.innerHTML = `
        <div class="verdict"><div class="big ${r.grade}" aria-label="Grade ${r.grade}">${r.grade}</div>
          <div><h3 style="font-size:20px;margin-bottom:2px">${UI.esc(r.application)}</h3>
            <div class="${r.confidence === "high" ? "ok" : "warn"}">${r.confidence === "high" ? UI.ICON.ok : UI.ICON.warn}
              ${r.confidence === "high" ? "High confidence" : `Low confidence: the lower bound gives grade ${r.grade_at_lower_bound}`}</div>
            <ul>${r.reasons.map((x) => `<li>${UI.esc(x)}</li>`).join("")}</ul></div></div>
        <div class="callout ${r.confidence === "high" ? "good" : ""}">${UI.esc(r.recommendation)}</div>
        <dl class="kv" style="margin-top:14px">
          <dt>Service in that use</dt><dd>${r.service_years == null ? "–" : `${r.service_years} years at its cycling rate`}</dd>
          <dt>Usable energy, 60 kWh pack</dt><dd>${v.usable_kwh_pack} kWh</dd>
          <dt>CO2e avoided, 60 kWh pack</dt><dd>${UI.num(v.co2_avoided_kg_pack)} kg (upper bound)</dd>
          <dt>Value, 60 kWh pack</dt><dd>USD ${UI.num(v.value_usd_pack)} (${v.route})</dd>
        </dl>`;
    } catch (e) {
      box.innerHTML = `<p class="bad">${UI.esc(e.message)}</p>`;
    }
  }
  ids.forEach((i) => el[i].addEventListener("input", update));
  update();

  // ---------- confusion matrix
  function drawConfusion() {
    const c = s.confusion;                     // {pred: {true: n}}
    const z = G.map((t) => G.map((p) => (c[p] && c[p][t]) || 0));
    const max = Math.max(...z.flat());
    const ann = [];
    z.forEach((row, i) => row.forEach((n, j) => ann.push({ x: G[j], y: G[i], text: `<b>${n}</b>`, showarrow: false,
      font: { size: 14, color: n > max * 0.55 ? "#ffffff" : UI.css("--ink") } })));
    UI.plot("confusion", [{ type: "heatmap", x: G, y: G, z, showscale: false, xgap: 3, ygap: 3,
      colorscale: [[0, UI.css("--surface-2")], [0.001, "#cde2fb"], [0.5, "#5598e7"], [1, "#184f95"]],
      hovertemplate: "Lab grade %{y}, AI grade %{x}: %{z} decisions<extra></extra>" }],
      { xaxis: { title: { text: "AI grade" }, side: "bottom", showgrid: false, ticks: "" },
        yaxis: { title: { text: "Lab grade" }, autorange: "reversed", showgrid: false, ticks: "" }, annotations: ann,
        margin: { l: 64, t: 10 } });
  }

  // ---------- second-life scatter
  function drawScatter() {
    const rows = D.assessments.filter((a) => a.dataset === "calce" && a.cycle_criterion_used && a.retire_soh_level > 0.6);
    const cells = [...new Set(rows.map((r) => r.cell_id))];
    const max = Math.max(...rows.map((r) => Math.max(r.cycles_to_floor_true, r.cycles_to_floor_pred))) * 1.05;
    UI.plot("slScatter", [
      ...cells.map((id) => {
        const r = rows.filter((x) => x.cell_id === id);
        return { type: "scatter", mode: "markers", name: id, x: r.map((x) => x.cycles_to_floor_true), y: r.map((x) => x.cycles_to_floor_pred),
          marker: { size: 9, color: UI.cellColor(id), line: { color: UI.css("--surface"), width: 1.5 } },
          customdata: r.map((x) => [x.retire_soh_level * 100]),
          hovertemplate: `${id} retired at %{customdata[0]:.1f}%<br>true %{x:.0f} cycles, predicted %{y:.0f}<extra></extra>` };
      }),
      { x: [0, max], y: [0, max], mode: "lines", name: "Perfect prediction", line: { color: UI.css("--muted"), dash: "dash", width: 1 }, hoverinfo: "skip" },
    ], { xaxis: { title: { text: "True cycles to 60%" }, range: [0, max] }, yaxis: { title: { text: "Predicted cycles to 60%" }, range: [0, max] } });
  }

  document.getElementById("appRows").innerHTML = D.applications.map((a) => `
    <tr><td>${UI.gradeChip(a.grade)}</td><td>${UI.esc(a.name)}</td><td class="num">${UI.pct(a.min_soh, 0)}</td>
    <td class="num">×${a.max_resistance_growth.toFixed(2)}</td><td class="num">${a.min_remaining_cycles}</td>
    <td class="num">${a.cycles_per_year}</td></tr>`).join("") +
    `<tr><td>${UI.gradeChip("D")}</td><td>Recycling / material recovery</td><td class="num" colspan="4" style="text-align:left">anything that fails C</td></tr>`;
  const A = D.assumptions;
  document.getElementById("assumptions").innerHTML = `
    <dt>Manufacturing footprint</dt><dd>${A.manufacturing_kgco2e_per_kwh} kg CO2e per kWh</dd>
    <dt>New storage battery</dt><dd>USD ${A.new_battery_usd_per_kwh} per kWh</dd>
    <dt>Repurposed price</dt><dd>${UI.pct(A.second_life_price_fraction, 0)} of new</dd>
    <dt>Recycling credit</dt><dd>USD ${A.recycling_credit_usd_per_kwh} per kWh</dd>
    <dt>Reference pack</dt><dd>${A.reference_pack_kwh} kWh</dd>`;

  const draw = () => { drawConfusion(); drawScatter(); };
  draw();
  UI.onTheme(draw);
})();
