(async () => {
  // ---------------------------------------------------------------- cell model (port of batterylife/hardware/simulator.py)
  const ocv = (s) => { s = Math.min(Math.max(s, 0), 1); return 3.30 + 0.55 * s + 0.35 * s * s - 0.30 * Math.exp(-18 * s); };
  function makeSim(soh, rated = 2.0) {
    const m = { rated, soh, r0: 0.06 * (1 + 2.0 * Math.pow(1 - soh, 1.1) * 3), vmax: 4.2, vmin: 2.7, ic: 1.0, id: 1.0, cut: 0.05, rest: 300, amb: 25 };
    const cap = rated * soh;
    let soc = 0.05, temp = m.amb, t = 0, phase = "rest", phaseT = 0, cyc = 0;
    const order = ["rest0", "charge", "rest1", "discharge", "rest2"];
    let k = 0;
    const g = () => (Math.random() + Math.random() + Math.random() - 1.5) * 0.0025;
    return function step(dt) {
      const st = order[k];
      let i = 0, v = ocv(soc);
      if (st === "charge") {
        if (ocv(soc) + m.ic * m.r0 < m.vmax) { i = m.ic; v = ocv(soc) + i * m.r0; }
        else { i = Math.min((m.vmax - ocv(soc)) / m.r0, m.ic); v = m.vmax; if (i < m.cut) { k++; phaseT = 0; i = 0; v = ocv(soc); } }
      } else if (st === "discharge") {
        v = ocv(soc) - m.id * m.r0; i = -m.id;
        if (v <= m.vmin || soc <= 0) { k++; phaseT = 0; i = 0; v = ocv(soc); }
      } else {
        const lim = st === "rest1" ? m.rest : m.rest / 2;
        if (phaseT >= lim) { k = (k + 1) % order.length; phaseT = 0; if (k === 0) cyc++; }
      }
      soc += (i * dt) / 3600 / cap;
      temp += dt * (i * i * m.r0 * 0.15 - 0.012 * (temp - m.amb));
      t += dt; phaseT += dt;
      return { dev: "SIM-WEB", cell: "HW-WEB", t_s: t, v: v + g(), i: i + g() / 2, temp: temp + g() * 4 };
    };
  }

  // ---------------------------------------------------------------- live cycle extraction (port of cycler.py)
  const I_ACT = 0.02;
  function makeCycler(onCycle) {
    let phase = "rest", seg = [], lastRest = null, pendingCharge = null, n = 0, q = 0;
    const flush = () => {
      if (phase === "charge" && seg.length >= 10) pendingCharge = seg;
      if (phase === "discharge" && seg.length >= 10 && pendingCharge) {
        const ch = pendingCharge, dis = seg;
        const tcv = ch.find((s) => s.v >= 4.195);
        const below = tcv ? ch.filter((s) => s.v <= 3.9 && s.t_s <= tcv.t_s).at(-1) : null;
        let cap = 0, en = 0;
        for (let j = 1; j < dis.length; j++) { const dt = dis[j].t_s - dis[j - 1].t_s; cap += Math.abs(dis[j].i) * dt; en += Math.abs(dis[j].i * dis[j].v) * dt; }
        const first = dis.slice(0, 3), iAvg = first.reduce((a, s) => a + Math.abs(s.i), 0) / first.length;
        const vAvg = first.reduce((a, s) => a + s.v, 0) / first.length;
        n += 1;
        onCycle({ cycle: n, capacity_ah: cap / 3600, energy_wh: en / 3600,
          cc_charge_time_s: tcv ? tcv.t_s - ch[0].t_s : null, cv_charge_time_s: tcv ? ch.at(-1).t_s - tcv.t_s : null,
          charge_v_rise_s: tcv && below ? tcv.t_s - below.t_s : null,
          resistance_ohm: lastRest ? (lastRest.v - vAvg) / Math.max(iAvg, 1e-6) : null,
          temp_max_c: Math.max(...dis.map((s) => s.temp)) });
        pendingCharge = null;
      }
    };
    return {
      push(s, dt) {
        const p = s.i > I_ACT ? "charge" : s.i < -I_ACT ? "discharge" : "rest";
        if (p !== phase) { flush(); if (phase === "rest" && seg.length) lastRest = seg.at(-1); seg = []; phase = p; if (p === "discharge") q = 0; }
        if (p === "discharge") q += Math.abs(s.i) * dt / 3600;
        seg.push(s);
        return { phase: p, q };
      },
    };
  }

  // ---------------------------------------------------------------- UI
  const $ = (id) => document.getElementById(id);
  const status = (t) => ($("hwStatus").textContent = t);
  const buf = { t: [], v: [], i: [], temp: [] };
  const rated = 2.0;
  let running = false, raf = null, reader = null, port = null, lastPlot = 0, cyclesShown = 0, base_r = null;

  function initCharts() {
    const mk = (el, color, y, range) => UI.plot(el, [{ x: [], y: [], mode: "lines", line: { color: UI.css(color), width: 1.8 }, hovertemplate: `%{x:.2f} h<br>%{y:.3f}<extra></extra>` }],
      { margin: { l: 46, r: 10, t: 6, b: 36 }, xaxis: { title: { text: "Hours on test" } }, yaxis: { range, title: { text: y } }, showlegend: false });
    mk("hwV", "--s1", "V", [2.6, 4.3]); mk("hwI", "--s2", "A", [-1.3, 1.3]); mk("hwT", "--s3", "°C", null);
  }
  function redraw() {
    const x = buf.t.map((t) => t / 3600);
    Plotly.react("hwV", [{ x, y: buf.v, mode: "lines", line: { color: UI.css("--s1"), width: 1.8 }, hovertemplate: "%{x:.2f} h<br>%{y:.3f} V<extra></extra>" }], UI.layout({ margin: { l: 46, r: 10, t: 6, b: 36 }, xaxis: { title: { text: "Hours on test" } }, yaxis: { range: [2.6, 4.3], title: { text: "V" } }, showlegend: false }), { displayModeBar: false, responsive: true });
    Plotly.react("hwI", [{ x, y: buf.i, mode: "lines", line: { color: UI.css("--s2"), width: 1.8 }, hovertemplate: "%{x:.2f} h<br>%{y:+.3f} A<extra></extra>" }], UI.layout({ margin: { l: 46, r: 10, t: 6, b: 36 }, xaxis: { title: { text: "Hours on test" } }, yaxis: { range: [-1.3, 1.3], title: { text: "A" } }, showlegend: false }), { displayModeBar: false, responsive: true });
    Plotly.react("hwT", [{ x, y: buf.temp, mode: "lines", line: { color: UI.css("--s3"), width: 1.8 }, hovertemplate: "%{x:.2f} h<br>%{y:.2f} °C<extra></extra>" }], UI.layout({ margin: { l: 46, r: 10, t: 6, b: 36 }, xaxis: { title: { text: "Hours on test" } }, yaxis: { title: { text: "°C" } }, showlegend: false }), { displayModeBar: false, responsive: true });
  }
  function readout(s, ph, q) {
    $("roV").textContent = `${s.v.toFixed(3)} V`; $("roI").textContent = `${s.i >= 0 ? "+" : ""}${s.i.toFixed(3)} A`;
    $("roT").textContent = `${s.temp.toFixed(1)} °C`; $("roP").textContent = ph; $("roQ").textContent = `${q.toFixed(3)} Ah`;
    $("hwReadouts").dataset.phase = ph;
  }
  async function onCycle(c) {
    const soh = c.capacity_ah / rated;
    if (base_r == null && c.resistance_ohm) base_r = c.resistance_ohm;
    const rg = base_r && c.resistance_ohm ? c.resistance_ohm / base_r : null;
    let a = null;
    try { a = await UI.post("/api/assess", { soh, halfwidth: 0.01, resistance_growth: rg }); } catch (e) { /* grading optional */ }
    if (!cyclesShown) $("hwCycles").innerHTML = "";
    cyclesShown++;
    $("hwCycles").insertAdjacentHTML("afterbegin", `<tr><td class="num">${c.cycle}</td><td class="num">${c.capacity_ah.toFixed(3)} Ah</td>
      <td class="num">${UI.pct(soh)}</td><td class="num">${c.cc_charge_time_s ? (c.cc_charge_time_s / 60).toFixed(0) + " min" : "–"}</td>
      <td class="num">${c.resistance_ohm ? (c.resistance_ohm * 1000).toFixed(0) + " mΩ" : "–"}</td><td>${a ? UI.gradeChip(a.grade) : "–"}</td></tr>`);
    $("hwEvent").textContent = JSON.stringify({
      type: "SOH_ASSESSMENT", actor_id: "BMS-01", role: "bms",
      data: { cycle: c.cycle, soh: +soh.toFixed(4), soh_lo: +(soh - 0.01).toFixed(4), soh_hi: +(soh + 0.01).toFixed(4),
              resistance_growth: rg ? +rg.toFixed(3) : null, capacity_ah: +c.capacity_ah.toFixed(4), temp_max_c: +c.temp_max_c.toFixed(2),
              method: "coulomb counting on board telemetry" },
      grade_if_retired_now: a ? `${a.grade}: ${a.application}` : null,
    }, null, 2);
  }
  function reset() {
    buf.t.length = buf.v.length = buf.i.length = buf.temp.length = 0;
    cyclesShown = 0; base_r = null;
    $("hwCycles").innerHTML = '<tr><td colspan="6" class="empty">No completed cycle yet. A cycle needs one full charge and one full discharge.</td></tr>';
    $("hwEvent").textContent = "Waiting for the first complete cycle.";
  }
  function setRunning(on) {
    running = on;
    $("hwSim").disabled = on; $("hwSerial").disabled = on; $("hwStop").disabled = !on;
  }
  function record(s, cyc, dt) {
    const r = cyc.push(s, dt);
    const last = buf.t.at(-1);
    if (last == null || s.t_s - last >= 20) { buf.t.push(s.t_s); buf.v.push(s.v); buf.i.push(s.i); buf.temp.push(s.temp); }
    return r;
  }

  function runSim() {
    reset(); setRunning(true);
    const step = makeSim(+$("hwSoh").value, rated), cyc = makeCycler(onCycle);
    const speed = +$("hwSpeed").value;
    status(`Simulated board running at ${speed}× real time. Cell set to ${Math.round(+$("hwSoh").value * 100)}% SOH; watch the measured SOH converge to it.`);
    let prev = performance.now();
    const loop = (now) => {
      if (!running) return;
      const sim = Math.min((now - prev) / 1000, 0.25) * speed; prev = now;
      let s, r;
      for (let k = 0; k < sim; k++) { s = step(1); r = record(s, cyc, 1); }
      if (s) readout(s, r.phase, r.q);
      if (now - lastPlot > 300) { redraw(); lastPlot = now; }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
  }

  async function runSerial() {
    if (!("serial" in navigator)) {
      status("USB connection needs Chrome or Edge on a computer (Web Serial). The simulated board works in any browser.");
      return;
    }
    try {
      port = await navigator.serial.requestPort();
      await port.open({ baudRate: 115200 });
    } catch (e) { status(`No board connected: ${e.message}`); return; }
    reset(); setRunning(true); status("Board connected. Reading one JSON line per second…");
    const cyc = makeCycler(onCycle);
    const dec = new TextDecoderStream();
    port.readable.pipeTo(dec.writable).catch(() => {});
    reader = dec.readable.getReader();
    let rest = "", prevT = null, bad = 0;
    try {
      while (running) {
        const { value, done } = await reader.read();
        if (done) break;
        rest += value;
        const lines = rest.split("\n"); rest = lines.pop();
        for (const line of lines) {
          let d; try { d = JSON.parse(line); } catch (e) { bad++; continue; }
          if (!["t_ms", "v", "i", "temp"].every((k) => typeof d[k] === "number")) { bad++; continue; }
          const s = { t_s: d.t_ms / 1000, v: d.v, i: d.i, temp: d.temp };
          const dt = prevT == null ? 1 : Math.max(0, s.t_s - prevT); prevT = s.t_s;
          const r = record(s, cyc, dt); readout(s, r.phase, r.q);
        }
        redraw();
        if (bad) status(`Board connected. ${bad} malformed lines skipped.`);
      }
    } catch (e) { status(`Connection closed: ${e.message}`); }
  }

  async function stop() {
    setRunning(false); cancelAnimationFrame(raf);
    try { if (reader) { await reader.cancel(); reader = null; } if (port) { await port.close(); port = null; } } catch (e) {}
    status("Stopped. Results above stay until you start again.");
    redraw();
  }

  $("hwSim").addEventListener("click", runSim);
  $("hwSerial").addEventListener("click", runSerial);
  $("hwStop").addEventListener("click", stop);
  initCharts();

  // ---------------------------------------------------------------- bench run recorded by the Python pipeline
  const H = await UI.get("/api/hardware");
  const bp = H.bench_passport;
  $("benchCard").innerHTML = bp ? `<h3>Passport ${UI.esc(bp.passport_id)}</h3>
    <dl class="kv"><dt>Source</dt><dd>${UI.esc(bp.source)}</dd><dt>Cycles ingested</dt><dd>${H.cycles.length}</dd>
      <dt>Signed events</dt><dd>${bp.events}</dd><dt>Verification</dt><dd>${UI.verdict(bp.valid, "Signatures verified", "Broken")}</dd>
      <dt>Grade now</dt><dd>${UI.gradeChip(bp.grade)} ${UI.esc(bp.application || "")}</dd></dl>
    <p style="margin:14px 0 0"><a href="/passports?id=${encodeURIComponent(bp.passport_id)}" data-go-passport="${UI.esc(bp.passport_id)}">Open this passport</a></p>`
    : '<p class="empty">No bench run recorded yet. Run: python -m batterylife.hardware ingest --log FILE</p>';
  const link = document.querySelector("[data-go-passport]");
  if (link && window.APP) link.addEventListener("click", (e) => { e.preventDefault(); APP.go("passports", { id: link.dataset.goPassport }); });
  const drawBench = () => {
    if (!H.cycles.length) return;
    UI.plot("benchChart", [{ type: "bar", x: H.cycles.map((c) => `Cycle ${c.cycle}`), y: H.cycles.map((c) => c.capacity_ah),
      marker: { color: UI.css("--s1") }, text: H.cycles.map((c) => UI.pct(c.soh)), textposition: "outside", cliponaxis: false,
      textfont: { color: UI.css("--ink-2"), size: 11 }, hovertemplate: "%{x}<br>%{y:.3f} Ah<extra></extra>" }],
      { margin: { l: 50, r: 10, t: 22, b: 36 }, yaxis: { title: { text: "Capacity (Ah)" }, range: [0, 2.0] }, showlegend: false });
  };
  drawBench();
  UI.onTheme(() => { redraw(); drawBench(); });
})();
