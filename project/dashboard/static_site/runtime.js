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
  async function get(url) {
    if (!(url in D.get)) throw new Error(`No data for ${url}`);
    return clone(D.get[url]);
  }
  async function post(url, body) {
    if (url === "/api/assess") return assess(body || {});
    let m = url.match(/^\/api\/passport\/([^/]+)\/verify$/);
    if (m) return verify(clone(D.get[`/api/passport/${m[1]}?access=full`]), D.bodies[m[1]]);
    m = url.match(/^\/api\/passport\/([^/]+)\/tamper$/);
    if (m) return tamper(m[1], (body || {}).attack || "edit");
    throw new Error(`Unknown action ${url}`);
  }

  // ------------------------------------------------------------ views (hash routing)
  const VIEWS = ["overview", "cells", "models", "second-life", "passports", "hardware", "reports"];
  const inits = {}, started = {}, params = {};
  const register = (name, fn) => { inits[name] = fn; };
  const param = (k) => params[k];
  function show(name) {
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

  return { get, post, register, param, go, verify, tamper, assess };
})();
