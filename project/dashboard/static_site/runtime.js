/* Browser runtime for the hosted (static) version of the dashboard.
   Replaces the Flask API: data is embedded, grading is ported from
   batterylife/lifecycle, and passport verification re-implements
   batterylife/passport/ledger.verify with WebCrypto (SHA-256 + Ed25519).

   Each event's exact signed bytes (the canonical JSON body that Python hashed)
   are embedded as `bodies`, so hashes are recomputed from the same bytes, and
   the displayed event fields are checked against them. */
const APP = (() => {
  const D = window.__STATIC__;
  const enc = new TextEncoder();
  const clone = (x) => JSON.parse(JSON.stringify(x));

  // ------------------------------------------------------------ crypto helpers
  const hex = (buf) => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
  const sha256 = async (s) => hex(await crypto.subtle.digest("SHA-256", enc.encode(s)));
  const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
  const toB64 = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf)));
  let edOK = null;
  async function ed25519Supported() {
    if (edOK !== null) return edOK;
    try { await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]); edOK = true; }
    catch (e) { edOK = false; }
    return edOK;
  }
  async function verifySig(pubB64, message, sigB64) {
    try {
      const key = await crypto.subtle.importKey("raw", b64(pubB64), { name: "Ed25519" }, false, ["verify"]);
      return await crypto.subtle.verify({ name: "Ed25519" }, key, b64(sigB64), enc.encode(message));
    } catch (e) { return false; }
  }

  function deepEqual(a, b) {
    if (a === b) return true;
    if (typeof a !== "object" || typeof b !== "object" || a === null || b === null) return false;
    if (Array.isArray(a) !== Array.isArray(b)) return false;
    const ka = Object.keys(a), kb = Object.keys(b);
    if (ka.length !== kb.length) return false;
    return ka.every((k) => deepEqual(a[k], b[k]));
  }
  const BODY_KEYS = ["index", "timestamp", "type", "actor_id", "role", "data", "prev_hash"];

  // ------------------------------------------------------------ verification
  async function verify(p, bodies) {
    const GENESIS = "0".repeat(64);
    const checks = { chain: true, content: true, signatures: true, roles: true, fields: true, chronology: true };
    const issues = [];
    const sigOK = await ed25519Supported();
    let prev = GENESIS, prevTs = "";
    for (let i = 0; i < p.events.length; i++) {
      const ev = p.events[i], body = bodies[i];
      const flag = (kind, msg) => { checks[kind] = false; issues.push({ index: i, type: ev.type, check: kind, problem: msg }); };
      if (ev.index !== i) flag("chain", `index ${ev.index} at position ${i} (event deleted or reordered)`);
      if (ev.prev_hash !== prev) flag("chain", "prev_hash does not match previous event");
      let parsed = null;
      try { parsed = JSON.parse(body); } catch (e) { /* handled below */ }
      const shown = Object.fromEntries(BODY_KEYS.map((k) => [k, ev[k]]));
      if (!parsed || (await sha256(body)) !== ev.hash || !deepEqual(parsed, shown))
        flag("content", "hash does not match event content (data was modified)");
      const actor = D.actors[ev.actor_id];
      if (!actor) flag("signatures", `unknown actor ${ev.actor_id}`);
      else {
        if (sigOK && !(await verifySig(actor.public_key, ev.hash, ev.signature)))
          flag("signatures", `invalid signature for actor ${actor.actor_id}`);
        if (actor.role !== ev.role) flag("roles", `event claims role '${ev.role}' but actor is '${actor.role}'`);
      }
      const meta = D.event_meta[ev.type];
      if (!meta) flag("roles", "unknown event type");
      else if (!meta.roles.includes(ev.role)) flag("roles", `role '${ev.role}' may not issue ${ev.type}`);
      const missing = (D.required_fields[ev.type] || []).filter((f) => !(f in (ev.data || {})));
      if (missing.length) flag("fields", `missing fields ${missing.join(", ")}`);
      const ts = String(ev.timestamp || "");
      if (ts < prevTs) flag("chronology", `timestamp ${ts} is earlier than previous event (${prevTs})`);
      prev = ev.hash; if (ts > prevTs) prevTs = ts;
    }
    return { passport_id: p.passport_id, valid: issues.length === 0, events: p.events.length, checks,
             first_bad_index: issues.length ? issues[0].index : null, issues,
             head_hash: p.events.length ? p.events.at(-1).hash : GENESIS, signatures_checked: sigOK };
  }

  // ------------------------------------------------------------ tamper simulations
  const fmt = (x) => `${(x * 100).toFixed(1)}%`;
  async function tamper(pid, attack) {
    const full = clone(D.get[`/api/passport/${pid}?access=full`]);
    const bodies = D.bodies[pid].slice();
    const ev = full.events;
    const sohIdx = ev.findIndex((e) => e.type === "SOH_ASSESSMENT");
    let target = sohIdx, detail = "";
    if (attack === "edit" || attack === "rehash") {
      const old = ev[sohIdx].data.soh;
      ev[sohIdx].data.soh = 0.99;
      bodies[sohIdx] = bodies[sohIdx].replace(/"soh":-?[0-9.eE+-]+/, '"soh":0.99');
      detail = `Event ${sohIdx}: SOH changed from ${fmt(old)} to 99.0%`;
      if (attack === "rehash") {
        let prev = ev[sohIdx - 1].hash;
        for (let j = sohIdx; j < ev.length; j++) {
          ev[j].prev_hash = prev;
          bodies[j] = bodies[j].replace(/"prev_hash":"[0-9a-f]{64}"/, `"prev_hash":"${prev}"`);
          ev[j].hash = await sha256(bodies[j]);
          prev = ev[j].hash;
        }
        detail += ", then every later hash recomputed";
      }
    } else if (attack === "delete") {
      ev.splice(sohIdx, 1); bodies.splice(sohIdx, 1);
      detail = `Event ${sohIdx} (SOH assessment) deleted`;
    } else if (attack === "backdate") {
      target = ev.length - 1;
      const ts = ev[target].timestamp, back = String(+ts.slice(0, 4) - 1) + ts.slice(4);
      ev[target].timestamp = back;
      bodies[target] = bodies[target].replace(`"timestamp":"${ts}"`, `"timestamp":"${back}"`);
      detail = `Event ${target} re-dated from ${ts.slice(0, 10)} to ${back.slice(0, 10)}`;
    } else if (attack === "impostor") {
      target = ev.findIndex((e) => e.type === "SECOND_LIFE_GRADING");
      if (target < 0) target = sohIdx;
      ev[target].data.grade = "A";
      bodies[target] = bodies[target].replace(/"grade":"[A-D]"/, '"grade":"A"');
      ev[target].hash = await sha256(bodies[target]);
      if (await ed25519Supported()) {
        const kp = await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]);
        ev[target].signature = toB64(await crypto.subtle.sign({ name: "Ed25519" }, kp.privateKey, enc.encode(ev[target].hash)));
      }
      detail = `Event ${target}: grade changed to A and re-signed with a key that does not belong to the assessor`;
    }
    if (!mayFull()) detail = detail.replace(/SOH changed from [0-9.]+% to/, "a restricted SOH value was raised to");
    const result = await verify(full, bodies);
    return { attack, description: D.attacks[attack], detail, target_index: target, result,
             note: "Applied to a copy in your browser. The original passport is unchanged." };
  }

  // ------------------------------------------------------------ grading (port of lifecycle/grading.py)
  function grade(soh, rg, cycles) {
    const reasons = [];
    for (const app of D.applications) {
      const fails = [];
      if (soh < app.min_soh) fails.push(`SOH ${(soh * 100).toFixed(1)}% < ${(app.min_soh * 100).toFixed(0)}%`);
      if (rg != null && rg > app.max_resistance_growth) fails.push(`resistance x${rg.toFixed(2)} > x${app.max_resistance_growth.toFixed(2)}`);
      if (cycles != null && cycles < app.min_remaining_cycles) fails.push(`${cycles.toFixed(0)} cycles left < ${app.min_remaining_cycles}`);
      if (!fails.length) { reasons.push(`meets ${app.name} requirements`); return [app.grade, app.name, reasons]; }
      reasons.push(`not ${app.grade}: ${fails.join("; ")}`);
    }
    return ["D", "Recycling / material recovery", reasons];
  }
  function value(g, soh) {
    const A = D.assumptions;
    const pack = soh * A.reference_pack_kwh;
    const reuse = g !== "D";
    return { route: reuse ? "re-use" : "recycle", usable_kwh_pack: Math.round(pack * 100) / 100,
             co2_avoided_kg_pack: reuse ? Math.round(pack * A.manufacturing_kgco2e_per_kwh * 10) / 10 : 0,
             value_usd_pack: Math.round(reuse ? pack * A.new_battery_usd_per_kwh * A.second_life_price_fraction
                                                : (pack / Math.max(soh, 1e-9)) * A.recycling_credit_usd_per_kwh) };
  }
  function assess(b) {
    const soh = +b.soh, hw = +(b.halfwidth || 0);
    if (!(soh > 0 && soh <= 1.2)) throw new Error("SOH must be between 0 and 1.2 (enter 0.78 for 78%).");
    const rg = b.resistance_growth === "" || b.resistance_growth == null ? null : +b.resistance_growth;
    const cyc = b.cycles === "" || b.cycles == null ? null : +b.cycles;
    const cycLo = b.cycles_lo === "" || b.cycles_lo == null ? cyc : +b.cycles_lo;
    const [g, app, reasons] = grade(soh, rg, cyc);
    const [gLo] = grade(soh - hw, rg, cycLo);
    const confident = gLo === g;
    const rec = g === "D" ? "Send to certified recycler; record SENT_TO_RECYCLING in passport"
      : confident ? `Repurpose for ${app}`
      : `Likely ${app}, but uncertainty spans grade ${gLo}: run a laboratory capacity test first`;
    let years = null;
    if (g !== "D" && cyc != null) {
      const cpy = D.applications.find((a) => a.grade === g).cycles_per_year;
      years = Math.round((cyc / cpy) * 100) / 100;
    }
    return { grade: g, application: app, reasons, confidence: confident ? "high" : "low", recommendation: rec,
             grade_at_lower_bound: gLo, service_years: years, value: value(g, soh) };
  }

  // ------------------------------------------------------------ API shim
  // The hosted copy has no server, so roles are simulated in the browser: the same views are shown
  // or hidden, but nothing is being protected (all data on this page is already public).
  const mayFull = () => typeof UI !== "undefined" && UI.can("passport:read_full");
  async function get(url) {
    if (/^\/api\/passport\/[^/]+\?access=full$/.test(url) && !mayFull())
      throw Object.assign(new Error("The full passport is restricted. Choose a role under Viewing as."), { status: 403 });
    if (!(url in D.get)) throw new Error(`No data for ${url}`);
    const out = clone(D.get[url]);
    if (url === "/api/passports" && !mayFull()) out.forEach((p) => { p.grade = null; });
    return out;
  }
  async function post(url, body) {
    if (url === "/api/assess") return assess(body || {});
    if (url === "/api/v1/auth/demo") {
      const r = D.get["/api/v1/auth/roles"].roles.find((x) => x.role === (body || {}).role);
      if (!r) throw new Error("Unknown role.");
      return { token: "hosted-demo", user: { username: r.role, name: r.description, role: r.role, permissions: r.permissions, may_sign: [] } };
    }
    let m = url.match(/^\/api\/passport\/([^/]+)\/verify$/);
    if (m) return verify(clone(D.get[`/api/passport/${m[1]}?access=full`]), D.bodies[m[1]]);
    m = url.match(/^\/api\/passport\/([^/]+)\/tamper$/);
    if (m) return tamper(m[1], (body || {}).attack || "edit");
    throw new Error(`Unknown action ${url}`);
  }

  // ------------------------------------------------------------ views (hash routing)
  const VIEWS = ["overview", "cells", "models", "second-life", "assess", "passports", "network", "api", "hardware", "reports"];
  const inits = {}, started = {}, params = {};
  const register = (name, fn) => { inits[name] = fn; };
  const param = (k) => params[k];
  function show(name) {
    const qi = name.indexOf("?");                      // #passports?id=DBP-...  (links from QR codes)
    if (qi >= 0) { new URLSearchParams(name.slice(qi + 1)).forEach((v, k) => { params[k] = v; }); name = name.slice(0, qi); }
    if (!VIEWS.includes(name)) name = "overview";
    document.querySelectorAll("[data-view]").forEach((s) => { s.hidden = s.dataset.view !== name; });
    document.querySelectorAll("nav a[data-nav]").forEach((a) => a.toggleAttribute("aria-current", a.dataset.nav === name));
    document.title = `${(document.querySelector(`nav a[data-nav="${name}"] span`) || {}).textContent || "Home"} · Battery Lifecycle Analytics`;
    if (!started[name] && inits[name]) { started[name] = true; inits[name](); }
    requestAnimationFrame(() => document.querySelectorAll(`[data-view="${name}"] .js-plotly-plot`)
      .forEach((el) => { try { Plotly.Plots.resize(el); } catch (e) {} }));
    window.scrollTo(0, 0);
  }
  function go(name, p = {}) {
    Object.assign(params, p);
    if (started[name]) {
      const sel = name === "cells" && p.cell ? `button[data-cell="${p.cell}"]`
        : name === "passports" && p.id ? `.pp-item[data-id="${p.id}"]` : null;
      if (sel) setTimeout(() => document.querySelector(sel)?.click(), 0);
    }
    if (location.hash !== `#${name}`) location.hash = name; else show(name);
  }
  window.addEventListener("hashchange", () => show(location.hash.slice(1)));
  document.addEventListener("DOMContentLoaded", () => show(location.hash.slice(1) || "overview"));

  // ------------------------------------------------------------ file assessment in the browser
  // Sample files return the server's stored result. Any other file gets a lighter analysis here:
  // measured health and a straight-line forecast (the server adds the fade model, the AI estimate
  // and signed passports).
  const ALIAS = { cycle: ["cycle", "cycle_index", "cycle_number", "cycle_no", "n"],
    capacity_ah: ["capacity_ah", "capacity", "discharge_capacity_ah", "discharge_capacity", "qd", "cap_ah"],
    cell_id: ["cell_id", "cell", "battery_id", "battery", "id"],
    resistance_ohm: ["resistance_ohm", "resistance", "ir", "internal_resistance_ohm", "r_ohm"] };
  const median = (a) => { const s = a.slice().sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
  const r4 = (x) => Math.round(x * 1e4) / 1e4;
  function linearRul(c, h, thr, window, horizon) {
    const n = Math.min(c.length, 2 * window), x = c.slice(-n), y = h.slice(-n);
    const mx = x.reduce((a, b) => a + b, 0) / n, my = y.reduce((a, b) => a + b, 0) / n;
    let sxy = 0, sxx = 0; for (let i = 0; i < n; i++) { sxy += (x[i] - mx) * (y[i] - my); sxx += (x[i] - mx) ** 2; }
    const slope = sxx ? sxy / sxx : 0, now = my + slope * (c.at(-1) - mx);
    if (now <= thr) return 0;
    if (slope >= 0) return horizon;
    return Math.min((thr - now) / slope, horizon);
  }
  function liteCell(id, rows, rated) {
    rows = rows.filter((r) => Number.isFinite(r.cycle) && r.capacity_ah > 0).sort((a, b) => a.cycle - b.cycle);
    if (!rows.length) throw new Error("no usable rows");
    const c = rows.map((r) => r.cycle), soh = rows.map((r) => r.capacity_ah / rated);
    if (Math.max(...soh) > 1.3) throw new Error("capacity is far above the rated capacity; check the rated capacity");
    const smooth = soh.map((_, i) => median(soh.slice(Math.max(0, i - 4), i + 5)));
    const resid = soh.map((v, i) => v - smooth[i]), mr = median(resid);
    const half = Math.max(0.01, soh.length >= 5 ? 1.96 * 1.4826 * median(resid.map((v) => Math.abs(v - mr))) : 0.01);
    const now = smooth.at(-1), res = rows.map((r) => r.resistance_ohm).filter((v) => Number.isFinite(v));
    const rg = res.length >= 2 && median(res.slice(0, 5)) > 0 ? median(res.slice(-5)) / median(res.slice(0, 5)) : null;
    const notes = ["Quick analysis in your browser: straight-line forecast only, and no outlier cleaning."], rul = {};
    const horizon = Math.min(Math.max(3 * c.at(-1), 500), 5000);
    if (rows.length >= 10 && c.at(-1) > c[0]) {
      const w = Math.max(5, Math.floor(rows.length / 6));
      for (const [k, thr] of [["to_80", 0.8], ["to_60", 0.6]]) {
        const v = Math.round(linearRul(c, smooth, thr, w, horizon));
        rul[k] = { cycles: v, lo: v, hi: v, beyond_horizon: v >= horizon, linear: v, fade_model: null };
      }
    } else notes.push("Fewer than 10 cycles, so no remaining-life forecast was made.");
    const left = rul.to_60 ? rul.to_60.cycles : null;
    const a = assess({ soh: now, halfwidth: half, resistance_growth: rg, cycles: left, cycles_lo: left });
    const step = Math.max(1, Math.floor(rows.length / 300)), idx = rows.map((_, i) => i).filter((i) => i % step === 0 || i === rows.length - 1);
    return { cell_id: id, cycles: rows.length, last_cycle: c.at(-1), rated_capacity_ah: rated, soh: r4(now), soh_lo: r4(now - half), soh_hi: r4(now + half),
      soh_source: "measured", soh_method: "measured capacity / rated capacity", stage: now >= 0.8 ? "First life" : now >= 0.6 ? "Second-life window" : "End of life",
      resistance_growth: rg == null ? null : Math.round(rg * 1000) / 1000, rul, model_check: null, grade: a.grade, application: a.application,
      confidence: a.confidence, recommendation: a.recommendation, reasons: a.reasons, grade_at_lower_bound: a.grade_at_lower_bound,
      service_years: a.service_years, value: a.value, notes,
      series: { cycle: idx.map((i) => c[i]), soh: idx.map((i) => r4(soh[i])), soh_smooth: idx.map((i) => r4(smooth[i])), soh_est: null } };
  }
  async function upload(form) {
    const file = form.get("file"), rated = +form.get("rated_capacity_ah");
    if (D.samples[file.name]) return clone(D.samples[file.name]);
    if (!(rated >= 0.01 && rated <= 1000)) throw new Error("Rated capacity must be between 0.01 and 1000 Ah.");
    if (file.size > 5 * 1024 * 1024) throw new Error("File is larger than 5 MB.");
    const lines = (await file.text()).split(/\r?\n/).filter((l) => l.trim() && !l.startsWith("#"));
    if (lines.length < 2) throw new Error("The file has no data rows.");
    const sep = [",", ";", "\t"].sort((a, b) => lines[0].split(b).length - lines[0].split(a).length)[0];
    const head = lines[0].split(sep).map((h) => h.trim().replace(/^"|"$/g, "").toLowerCase().replace(/ /g, "_"));
    const col = {}; for (const [std, names] of Object.entries(ALIAS)) { const i = head.findIndex((h) => names.includes(h)); if (i >= 0) col[std] = i; }
    if (col.cycle == null) throw new Error("No 'cycle' column found.");
    if (col.capacity_ah == null) throw new Error("This hosted copy needs a 'capacity_ah' column. The AI estimate from charging signals runs on the server version.");
    const groups = new Map();
    for (const l of lines.slice(1)) {
      const f = l.split(sep), id = col.cell_id == null ? "CELL-1" : f[col.cell_id].trim().replace(/^"|"$/g, "");
      if (!groups.has(id)) groups.set(id, []);
      groups.get(id).push({ cycle: +f[col.cycle], capacity_ah: +f[col.capacity_ah], resistance_ohm: col.resistance_ohm == null ? NaN : +f[col.resistance_ohm] });
    }
    if (groups.size > 200) throw new Error("More than 200 batteries in one file.");
    const results = [], failed = [];
    for (const [id, rows] of groups) { try { results.push(liteCell(id, rows, rated)); } catch (e) { failed.push({ cell_id: id, problem: e.message }); } }
    if (!results.length) throw new Error(`No battery in the file could be analysed: ${failed[0].problem}.`);
    const rank = { A: 0, B: 1, C: 2, D: 3 };
    results.sort((a, b) => rank[a.grade] - rank[b.grade] || b.soh - a.soh).forEach((r, i) => { r.rank = i + 1; });
    const grades = { A: 0, B: 0, C: 0, D: 0 }; results.forEach((r) => { grades[r.grade]++; });
    return { upload_id: "in your browser", filename: file.name, profile: "other", rated_capacity_ah: rated, batteries: results.length, rows: lines.length - 1,
      grades, low_confidence: results.filter((r) => r.confidence === "low").length,
      mean_soh: r4(results.reduce((a, r) => a + r.soh, 0) / results.length), results, failed };
  }
  const openPdf = async (pid, access) => { window.open(`passports/${encodeURIComponent(pid)}${access === "public" ? ".public" : ""}.pdf`, "_blank", "noopener"); };

  return { get, post, register, param, go, verify, tamper, assess, upload, openPdf };
})();
