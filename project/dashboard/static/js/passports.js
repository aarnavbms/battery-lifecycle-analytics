(async () => {
  await UI.ready;
  let list = await UI.get("/api/passports");
  const attacks = await UI.get("/api/attacks");
  let current = new URLSearchParams(location.search).get("id") || list[0].passport_id;
  if (!list.some((p) => p.passport_id === current)) current = list[0].passport_id;
  const mayFull = () => UI.can("passport:read_full");
  let access = mayFull() ? "full" : "public";
  let P = null, flagged = new Set();

  const CHECK_TEXT = {
    chain: ["Chain links", "every event points to the hash of the one before"],
    content: ["Content integrity", "hashes match the stored data"],
    signatures: ["Signatures", "each event signed by its actor's key"],
    roles: ["Authorisation", "actor's role may issue that event"],
    fields: ["Required fields", "mandatory data is present"],
    chronology: ["Chronology", "dates never go backwards"],
  };
  const EVENT_TEXT = {
    MANUFACTURED: "Manufactured", CARBON_FOOTPRINT_DECLARED: "Carbon footprint declared",
    FIRST_LIFE_START: "Entered first life", SOH_ASSESSMENT: "State of health assessed",
    RUL_PREDICTION: "Remaining life predicted", FIRST_LIFE_RETIRED: "Retired from first life",
    SECOND_LIFE_GRADING: "Graded for second life", REPURPOSED: "Repurposed",
    SENT_TO_RECYCLING: "Sent to recycling", RECYCLED: "Recycled",
  };
  const SECTION_TEXT = {
    general_information: "General information", carbon_footprint: "Carbon footprint",
    performance_and_durability: "Performance and durability", battery_status: "Battery status",
    state_of_health: "State of health", lifecycle_decision: "Lifecycle decision",
  };

  const ORIGIN_TEXT = { lab: "Laboratory cells", hardware: "Bench hardware", upload: "Uploaded batteries" };
  function drawList() {
    let last = null;
    // show the newest upload only; older ones stay available through the API
    const ups = list.filter((p) => p.origin === "upload");
    const newest = ups.reduce((a, p) => (!a || p.updated_at > a.updated_at ? p : a), null);
    const batch = (p) => p.passport_id.split("-")[2];
    const shown = list.filter((p) => p.origin !== "upload" || p.passport_id === current || batch(p) === batch(newest));
    const hiddenN = list.length - shown.length;
    document.getElementById("ppList").innerHTML = shown.map((p) => {
      const head = p.origin !== last && list.some((x) => x.origin !== list[0].origin) ? `<span class="pp-group">${ORIGIN_TEXT[p.origin] || ""}</span>` : "";
      last = p.origin;
      return `${head}
      <button class="pp-item" type="button" data-id="${p.passport_id}" aria-pressed="${p.passport_id === current}">
        <span class="id">${p.passport_id}</span>
        <span class="meta">${UI.statusChip(p.status)} ${p.grade ? UI.gradeChip(p.grade) : ""} <span>${p.events} events</span></span>
        <span class="meta">${UI.verdict(p.valid, "Signatures verified", "Verification failed")}</span>
      </button>`; }).join("") + (hiddenN ? `<span class="pp-group">${hiddenN} passports from older uploads are available through the API.</span>` : "");
    document.querySelectorAll(".pp-item").forEach((b) => b.addEventListener("click", () => { current = b.dataset.id; flagged = new Set(); load(); }));
  }

  async function load() {
    history.replaceState(null, "", `?id=${current}`);
    drawList();
    if (access === "full" && !mayFull()) access = "public";
    P = await UI.get(`/api/passport/${current}?access=${access === "public" ? "public" : "full"}`);
    render();
  }

  const fmtVal = (k, v) => {
    if (v == null) return "–";
    if (typeof v === "number") {
      if (/soh|lo$|hi$/.test(k) && v <= 1.3) return UI.pct(v, 1);
      return UI.num(v, Number.isInteger(v) ? 0 : 3);
    }
    if (typeof v === "object") return Object.entries(v).map(([a, b]) => `${a}: ${fmtVal(a, b)}`).join(", ");
    return UI.esc(v);
  };
  const kv = (obj) => obj ? `<dl class="kv">${Object.entries(obj).filter(([, v]) => v != null)
    .map(([k, v]) => `<dt>${UI.esc(k.replace(/_/g, " "))}</dt><dd>${fmtVal(k, v)}</dd>`).join("")}</dl>` : `<p class="note">No data yet.</p>`;

  function eventLine(e) {
    const d = e.data;
    switch (e.type) {
      case "SOH_ASSESSMENT": return `Cycle ${d.cycle}: SOH ${UI.pct(d.soh)} (95%: ${UI.pct(d.soh_lo)} to ${UI.pct(d.soh_hi)}), resistance ×${UI.num(d.resistance_growth, 2)}`;
      case "RUL_PREDICTION": return `Cycle ${d.cycle}: ${UI.num(d.rul_cycles)} cycles left to ${UI.pct(d.threshold, 0)} (80% band ${UI.num(d.rul_lo)} to ${UI.num(d.rul_hi)})`;
      case "SECOND_LIFE_GRADING": return `Grade ${d.grade}: ${UI.esc(d.application)}, ${d.confidence} confidence`;
      case "MANUFACTURED": return `${UI.esc(d.chemistry)}, rated ${d.rated_capacity_ah} Ah, initial ${UI.num(d.initial_capacity_ah, 3)} Ah`;
      case "CARBON_FOOTPRINT_DECLARED": return `${d.kgco2e_per_kwh} kg CO2e per kWh, ${UI.num(d.total_kgco2e, 3)} kg for this cell`;
      case "FIRST_LIFE_RETIRED": case "SENT_TO_RECYCLING": return `${d.cycle == null ? "" : `Cycle ${d.cycle}: `}${UI.esc(d.reason || "")}`;
      case "REPURPOSED": return `${d.cycle == null ? "" : `Cycle ${d.cycle}: `}now ${UI.esc(d.application || "")}`;
      case "RECYCLED": return UI.esc([d.recovered, d.facility].filter(Boolean).join(", "));
      default: return UI.esc(d.application || "");
    }
  }

  function render() {
    const s = P.sections, st = s.battery_status;
    const actorName = (id) => (P.actors[id] ? P.actors[id].name : id);
    const sohEvents = P.events.filter((e) => e.type === "SOH_ASSESSMENT");
    const sectionCard = (key) => {
      const restricted = P.section_access[key] !== "public";
      const body = key in s ? (key === "battery_status" ? `<p style="margin:0 0 6px">${UI.statusChip(st.status)}</p>${kv({ events: st.events, last_event: EVENT_TEXT[st.last_event] || st.last_event })}`
        : key === "state_of_health" ? kv({ ...(s.state_of_health.latest_assessment || {}), method: undefined })
        : key === "lifecycle_decision" && s.lifecycle_decision ? `<p style="margin:0 0 8px">${UI.gradeChip(s.lifecycle_decision.grade)} ${UI.esc(s.lifecycle_decision.application)}</p>${kv({ ...s.lifecycle_decision, grade: undefined, application: undefined })}`
        : kv(s[key])) : `<p class="locked">${UI.ICON.lock}Hidden in the public view. Readable by repairers, repurposers, recyclers and authorities.</p>`;
      return `<div class="panel"><h3>${SECTION_TEXT[key]} <span class="pill">${restricted ? "restricted" : "public"}</span></h3>${body}</div>`;
    };

    const g = s.general_information || {};
    const latest = s.state_of_health && s.state_of_health.latest_assessment;
    const fillSoh = latest ? latest.soh : null;
    const role = UI.user.role, signable = (UI.user.may_sign || []).filter((t) => t !== "MANUFACTURED" && t !== "CARBON_FOOTPRINT_DECLARED");
    const banner = mayFull() ? "" : `<div class="callout pp-banner"><p><b>You are seeing the public tier</b>, the part a QR code on the battery shows to anyone. Health records and the second-life decision are restricted to roles with a legitimate interest.</p>
      <button class="ghost" type="button" data-signin="recycler">View as Recycler</button> <button class="ghost" type="button" data-signin="regulator">View as Regulator</button></div>`;
    document.getElementById("ppDetail").innerHTML = `${banner}
      <article class="passport" aria-label="Passport document ${P.passport_id}">
        <header class="pp-doc-head">
          <div><span class="pp-issuer">Regulation (EU) 2023/1542, Annex XIII</span>
            <h2>Digital Battery Passport</h2></div>
          <span class="pp-type" title="Document type">DBP</span>
        </header>
        <div class="pp-doc-body">
          <div class="pp-portrait" aria-hidden="true">
            <svg viewBox="0 0 120 64"><rect x="4" y="8" width="102" height="48" rx="7" class="cell-shell"/><rect x="106" y="22" width="9" height="20" rx="2.5" class="cell-tip"/>
              <rect x="10" y="14" width="${fillSoh == null ? 0 : Math.max(0, Math.min(1, fillSoh / 1.05)) * 90}" height="36" rx="3" class="cell-fill ${fillSoh == null ? "" : stageClass(fillSoh)}"/></svg>
            <span>${fillSoh == null ? "Health restricted" : `SOH ${UI.pct(fillSoh)}`}</span>
          </div>
          <dl class="pp-fields">
            <div><dt>Passport no.</dt><dd class="mono">${P.passport_id}</dd></div>
            <div><dt>Battery</dt><dd>${UI.esc(P.battery_id)}</dd></div>
            <div><dt>Chemistry</dt><dd>${UI.esc(g.chemistry || "–")}</dd></div>
            <div><dt>Rated capacity</dt><dd>${g.rated_capacity_ah ?? "–"} Ah</dd></div>
            <div><dt>Manufactured</dt><dd>${UI.esc(g.manufacture_date || "–")}</dd></div>
            <div><dt>Status</dt><dd>${UI.statusChip(P.status)}</dd></div>
            <div><dt>Signed events</dt><dd>${P.events.length}${access === "public" ? " public" : ""}</dd></div>
            <div><dt>Reader access</dt><dd>${access === "public" ? "Public (QR code)" : `Legitimate interest (${UI.esc(UI.ROLE_LABEL[role] || role)})`}</dd></div>
          </dl>
        </div>
        <p class="pp-hash">Chain head <span class="mono">${P.head_hash}</span></p>
        <div class="mrz" aria-label="Machine-readable zone">${mrz(P, g).map(UI.esc).join("<br>")}</div>
        <div class="stamp" id="ppStamp" hidden></div>
      </article>

      <div class="pp-controls">
        <div class="toolbar" role="group" aria-label="Access level">
          <button class="seg" type="button" data-access="full" aria-pressed="${access === "full"}" ${mayFull() ? "" : 'disabled title="Needs a signed-in role with a legitimate interest"'}>${mayFull() ? "" : UI.ICON.lock}Full view</button>
          <button class="seg" type="button" data-access="public" aria-pressed="${access === "public"}">Public view (QR code)</button>
          <button class="ghost" type="button" id="btnPdf">PDF with QR code</button>
        </div>
        <div class="toolbar">
          <button class="primary" type="button" id="btnVerify">Verify passport</button>
          <select id="attack" aria-label="Attack to simulate">${Object.entries(attacks).map(([k, v]) => `<option value="${k}">${UI.esc(v)}</option>`).join("")}</select>
          <button class="ghost" type="button" id="btnTamper">Simulate tampering</button>
        </div>
      </div>
      <div id="verifyOut" aria-live="polite"></div>

      ${sohEvents.length ? `<div class="panel" style="margin-top:16px"><h3>Health recorded in this passport</h3><p class="note">Signed SOH assessments with their 95% interval. Thresholds at 80% and 60%.</p><div id="ppSoh" class="chart short"></div></div>` : ""}

      <div class="sections" style="margin-top:16px">
        ${["general_information", "battery_status", "performance_and_durability", "carbon_footprint", "state_of_health", "lifecycle_decision"].map(sectionCard).join("")}
      </div>

      <div class="panel" style="margin-top:16px">
        <h3>Event ledger</h3>
        <p class="note">Oldest first. Each row is signed by the actor shown.</p>
        <ol class="timeline" id="timeline">
        ${P.events.map((e) => `<li data-i="${e.index}" class="${flagged.has(e.index) ? "flag" : ""}">
          <span class="n">${e.index}</span><span class="when">${e.timestamp.replace("T", " ").slice(0, 16)}</span>
          <span class="what"><b>${EVENT_TEXT[e.type] || e.type}</b> <span class="d">by ${UI.esc(actorName(e.actor_id))} (${e.role})</span><br>
            <span class="d">${eventLine(e)}</span><br><span class="hash">hash ${e.hash.slice(0, 24)}… signature ${e.signature.slice(0, 16)}…</span></span>
          <span class="acc"><span class="pill">${P.event_meta[e.type].access === "public" ? "public" : "restricted"}</span></span></li>`).join("")}
        </ol>
      </div>
      ${!UI.isStatic && P.origin !== "lab" && signable.length ? `<form class="panel event-form" id="evForm" style="margin-top:16px">
        <h3>Record a lifecycle event</h3>
        <p class="note">As ${UI.esc(UI.ROLE_LABEL[role] || role)} you may sign the event types listed. The server signs with your role's key and appends it to the chain.</p>
        <label class="field"><span class="row">Event type</span><select id="evType">${signable.map((t) => `<option value="${t}">${EVENT_TEXT[t] || t}</option>`).join("")}</select></label>
        <label class="field"><span class="row">Event data (JSON)</span><textarea id="evData" rows="4" spellcheck="false"></textarea></label>
        <div class="toolbar"><button class="primary" type="submit">Sign and append</button><span class="status-line" id="evMsg" role="status"></span></div>
      </form>` : ""}
      ${!UI.isStatic && P.origin === "lab" && signable.length ? `<p class="note" style="margin-top:12px">Laboratory passports are archived results and read-only. To record events as ${UI.esc(UI.ROLE_LABEL[role] || role)}, open a passport created from an upload.</p>` : ""}`;

    document.querySelectorAll("button[data-signin]").forEach((b) => b.addEventListener("click", () => UI.signIn(b.dataset.signin)));
    document.getElementById("btnPdf").addEventListener("click", () => UI.openPdf(current, access).catch((e) => { document.getElementById("verifyOut").textContent = e.message; }));
    const evForm = document.getElementById("evForm");
    if (evForm) {
      const TEMPLATE = { SOH_ASSESSMENT: { cycle: 0, soh: 0.8, soh_lo: 0.78, soh_hi: 0.82, resistance_growth: 1.1, method: "manual capacity test" },
        RUL_PREDICTION: { cycle: 0, threshold: 0.6, rul_cycles: 200, rul_lo: 150, rul_hi: 260, method: "manual estimate" },
        SECOND_LIFE_GRADING: { grade: "B", application: "Grid / home energy storage", confidence: "high", recommendation: "Repurpose" },
        FIRST_LIFE_START: { application: "EV traction" }, FIRST_LIFE_RETIRED: { cycle: 0, reason: "SOH reached 80%" },
        REPURPOSED: { application: "Home energy storage", new_status: "repurposed" },
        SENT_TO_RECYCLING: { reason: "end of second life" }, RECYCLED: { recovered: "Co, Li, Ni, Cu recovered", facility: "certified recycler" } };
      const fill = () => { document.getElementById("evData").value = JSON.stringify(TEMPLATE[document.getElementById("evType").value] || {}, null, 2); };
      document.getElementById("evType").addEventListener("change", fill); fill();
      evForm.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const m = document.getElementById("evMsg");
        let data; try { data = JSON.parse(document.getElementById("evData").value); } catch (e) { m.textContent = "The event data is not valid JSON."; return; }
        try {
          const r = await UI.request("POST", `/api/v1/passports/${encodeURIComponent(current)}/events`, { type: document.getElementById("evType").value, data });
          list = await UI.get("/api/passports"); await load();
          document.getElementById("verifyOut").innerHTML = `<div class="callout good" style="margin-top:14px">${UI.verdict(r.valid, `Event ${r.event.index} signed by ${UI.esc(r.event.actor_id)} and appended. The chain still verifies.`, "Appended, but verification failed")}</div>`;
        } catch (e) { m.textContent = e.message; }
      });
    }

    document.querySelectorAll("button[data-access]").forEach((b) => b.addEventListener("click", () => { access = b.dataset.access; flagged = new Set(); load(); }));
    document.getElementById("btnVerify").addEventListener("click", doVerify);
    document.getElementById("btnTamper").addEventListener("click", doTamper);
    drawSoh();
  }

  function drawSoh() {
    const ev = P.events.filter((e) => e.type === "SOH_ASSESSMENT");
    if (!ev.length) return;
    const x = ev.map((e) => e.data.cycle), y = ev.map((e) => e.data.soh * 100);
    const col = UI.cellColor(P.battery_id);
    const ret = P.events.find((e) => e.type === "FIRST_LIFE_RETIRED");
    const hline = (v, c) => ({ type: "line", xref: "paper", x0: 0, x1: 1, y0: v, y1: v, line: { color: c, width: 1, dash: "dash" } });
    UI.plot("ppSoh", [{ x, y, mode: "lines+markers", line: { color: col, width: 2 }, marker: { size: 8, color: col },
      error_y: { type: "data", symmetric: false, array: ev.map((e) => (e.data.soh_hi - e.data.soh) * 100),
                 arrayminus: ev.map((e) => (e.data.soh - e.data.soh_lo) * 100), color: col, thickness: 1.2, width: 4 },
      customdata: ev.map((e) => [e.index]), hovertemplate: "event %{customdata[0]}, cycle %{x}<br>SOH %{y:.1f}%<extra></extra>", showlegend: false }],
      { margin: { l: 52, r: 12, t: 8, b: 40 }, xaxis: { title: { text: "Cycle" } }, yaxis: { title: { text: "SOH (%)" }, ticksuffix: "%" },
        shapes: [hline(80, UI.css("--zone-first-ink")), hline(60, UI.css("--zone-end-ink")),
          ...(ret ? [{ type: "line", yref: "paper", y0: 0, y1: 1, x0: ret.data.cycle, x1: ret.data.cycle, line: { color: UI.css("--muted"), width: 1 } }] : [])],
        annotations: ret ? [{ x: ret.data.cycle, yref: "paper", y: 1, text: "retired", showarrow: false, xanchor: "left", xshift: 4, yanchor: "top", font: { size: 11, color: UI.css("--ink-2") } }] : [] });
  }

  function stageClass(soh) { return soh >= 0.8 ? "first" : soh >= 0.6 ? "second" : "end"; }

  // Machine-readable zone in the style of ICAO 9303, with 7-3-1 check digits
  function checkDigit(str) {
    const val = (c) => (c === "<" ? 0 : /\d/.test(c) ? +c : c.charCodeAt(0) - 55);
    return String([...str].reduce((s, c, i) => s + val(c) * [7, 3, 1][i % 3], 0) % 10);
  }
  function mrz(P, g) {
    const clean = (x) => String(x || "").toUpperCase().replace(/[^A-Z0-9]/g, "<");
    const pad = (x, n) => (x + "<".repeat(n)).slice(0, n);
    const chem = /LICOO2|LCO/i.test(g.chemistry || "") ? "LCO" : "LIB";
    const date = (g.manufacture_date || "").replace(/-/g, "").slice(2) || "000000";
    const id = pad(clean(P.battery_id), 9), status = pad(clean(P.status), 10);
    const line1 = pad(`DBP<EU<${clean(P.battery_id)}<<${clean(g.chemistry).replace(/<+/g, "<").slice(0, 26)}`, 44);
    const body = `${id}${checkDigit(id)}${chem}${date}${checkDigit(date)}${status}${pad(clean(g.rated_capacity_ah + "AH"), 6)}`;
    const line2 = pad(body, 43) + checkDigit(pad(body, 43));
    return [line1, line2];
  }
  function stamp(ok, big, small) {
    const el = document.getElementById("ppStamp");
    el.className = `stamp ${ok ? "ok" : "bad"}`;
    el.innerHTML = `<b>${big}</b><small>${small}</small>`;
    el.hidden = false;
    el.style.animation = "none"; void el.offsetWidth; el.style.animation = "";
  }

  function checksHTML(r) {
    return `<ul class="checks">${Object.entries(r.checks).map(([k, ok]) =>
      `<li>${ok ? `<span class="ok">${UI.ICON.ok}</span>` : `<span class="bad">${UI.ICON.bad}</span>`}<span><b>${CHECK_TEXT[k][0]}</b><small>${CHECK_TEXT[k][1]}</small></span></li>`).join("")}</ul>`;
  }
  function markFlags(r) {
    flagged = new Set(r.issues.map((i) => i.index));
    document.querySelectorAll("#timeline li").forEach((li) => li.classList.toggle("flag", flagged.has(+li.dataset.i)));
  }

  async function doVerify() {
    const out = document.getElementById("verifyOut");
    const r = await UI.post(`/api/passport/${current}/verify`);
    markFlags(r);
    stamp(r.valid, r.valid ? "Verified" : "Invalid", r.valid ? `${r.events} events · SHA-256 · Ed25519` : `first bad event ${r.first_bad_index}`);
    out.innerHTML = `<div class="callout ${r.valid ? "good" : ""}" style="margin-top:14px">
      ${UI.verdict(r.valid, `Passport verified: all ${r.events} events intact and correctly signed`, "Verification failed")}
      ${checksHTML(r)}</div>`;
  }

  async function doTamper() {
    const out = document.getElementById("verifyOut");
    const btn = document.getElementById("btnTamper");
    btn.disabled = true;
    try {
      const t = await UI.post(`/api/passport/${current}/tamper`, { attack: document.getElementById("attack").value });
      const r = t.result;
      if (access === "full") markFlags(r);
      const failed = Object.entries(r.checks).filter(([, ok]) => !ok).map(([k]) => CHECK_TEXT[k][0].toLowerCase());
      stamp(r.valid, r.valid ? "Not detected" : "Tampering detected", r.valid ? "" : `event ${r.first_bad_index} · ${failed.join(", ")}`);
      out.innerHTML = `<div class="callout" style="margin-top:14px;border-left-color:var(--critical)">
        <p style="margin:0 0 4px"><b>Attack:</b> ${UI.esc(t.detail)}.</p>
        ${UI.verdict(r.valid, "Not detected", `Detected at event ${r.first_bad_index}: ${failed.join(", ")} check${failed.length > 1 ? "s" : ""} failed`)}
        ${checksHTML(r)}
        <p class="note">${UI.esc(t.note)}</p></div>`;
    } finally { btn.disabled = false; }
  }

  UI.onTheme(() => { if (P) drawSoh(); });
  UI.onUser(async () => { access = mayFull() ? "full" : "public"; flagged = new Set(); list = await UI.get("/api/passports"); load(); });
  load();
})();
