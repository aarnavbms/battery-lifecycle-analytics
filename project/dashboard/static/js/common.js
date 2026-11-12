/* Shared helpers: theme, tokens, Plotly defaults, formatting. */
const UI = (() => {
  const root = document.documentElement;
  try { const t = localStorage.getItem("bla-theme"); if (t) root.dataset.theme = t; } catch (e) {}

  const css = (name) => getComputedStyle(root).getPropertyValue(name).trim();
  const renderers = [];
  const onTheme = (fn) => { renderers.push(fn); };

  document.addEventListener("DOMContentLoaded", () => {
    const btn = document.getElementById("themeToggle");
    if (btn) btn.addEventListener("click", () => {
      const dark = root.dataset.theme ? root.dataset.theme === "dark"
        : matchMedia("(prefers-color-scheme: dark)").matches;
      root.dataset.theme = dark ? "light" : "dark";
      try { localStorage.setItem("bla-theme", root.dataset.theme); } catch (e) {}
      renderers.forEach((fn) => fn());
    });
  });

  // fixed cell -> colour slot (colour follows the entity, never its rank)
  const CELL_SLOT = { B0005: 1, B0006: 2, B0007: 3, B0018: 4, CS2_35: 1, CS2_36: 2, CS2_37: 3, CS2_38: 4 };
  const cellColor = (id) => css(`--s${CELL_SLOT[id] || 1}`);
  const gradeColor = (g) => css(`--g${g}`);

  function layout(extra = {}) {
    const ink = css("--ink"), ink2 = css("--ink-2"), grid = css("--grid"), axis = css("--axis");
    const font = css("--text");
    const base = {
      paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
      font: { family: font, color: ink2, size: 12.5 },
      margin: { l: 56, r: 18, t: 12, b: 46 },
      hovermode: "closest",
      hoverlabel: { bgcolor: css("--surface"), bordercolor: css("--hair"), font: { color: ink, family: font, size: 13 } },
      legend: { orientation: "h", x: 0, y: 1.02, yanchor: "bottom", font: { color: ink2, size: 12.5 }, bgcolor: "rgba(0,0,0,0)" },
      xaxis: { gridcolor: grid, linecolor: axis, zeroline: false, tickcolor: axis, ticks: "outside", ticklen: 4,
               title: { font: { color: ink2, size: 12.5 } }, automargin: true },
      yaxis: { gridcolor: grid, linecolor: axis, zeroline: false, tickcolor: axis, ticks: "outside", ticklen: 4,
               title: { font: { color: ink2, size: 12.5 } }, automargin: true },
    };
    return deepMerge(base, extra);
  }

  function deepMerge(a, b) {
    const out = Array.isArray(a) ? a.slice() : { ...a };
    for (const [k, v] of Object.entries(b || {})) {
      out[k] = v && typeof v === "object" && !Array.isArray(v) && a[k] && typeof a[k] === "object"
        ? deepMerge(a[k], v) : v;
    }
    return out;
  }

  const config = { displayModeBar: false, responsive: true };
  function plot(el, traces, lay) {
    const node = typeof el === "string" ? document.getElementById(el) : el;
    if (typeof Plotly === "undefined") {
      node.innerHTML = '<p class="empty">The chart library did not load. Refresh the page; if it persists, check that plotly.min.js sits next to index.html.</p>';
      return Promise.resolve();
    }
    return Plotly.react(node, traces, layout(lay), config);
  }

  // ---------------------------------------------------------------- accounts and requests
  // A signed-in role is kept as a bearer token for this browser tab. Every request sends it,
  // and the server decides what that role may see or do.
  const PUBLIC_USER = { username: null, name: "Public visitor", role: "public", permissions: [], may_sign: [] };
  let token = null, user = PUBLIC_USER;
  try { token = sessionStorage.getItem("bla-token"); } catch (e) {}
  const userFns = [];
  const self = {};

  async function request(method, url, body) {
    const opt = { method, headers: token ? { Authorization: `Bearer ${token}` } : {} };
    if (body instanceof FormData) opt.body = body;
    else if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body || {}); }
    const r = await fetch(url, opt);
    if (r.status === 204) return null;
    let j = null;
    try { j = await r.json(); } catch (e) { /* not JSON */ }
    if (!r.ok) {
      const msg = j && j.error ? (j.error.message || j.error) : `${url}: ${r.status}`;
      throw Object.assign(new Error(msg), { status: r.status });
    }
    return j;
  }
  const get = (url) => request("GET", url);
  const post = (url, body) => request("POST", url, body || {});

  const can = (perm) => user.permissions.includes(perm);
  const onUser = (fn) => { userFns.push(fn); };
  function setUser(u, t) {
    user = u || PUBLIC_USER; token = t || null;
    try { t ? sessionStorage.setItem("bla-token", t) : sessionStorage.removeItem("bla-token");
          sessionStorage.setItem("bla-role", user.role); } catch (e) {}
    drawWho();
    userFns.forEach((fn) => fn(user));
  }
  async function signIn(role, username, password) {
    if (!role || role === "public") { setUser(null, null); return user; }
    const r = username ? await self.post("/api/v1/auth/login", { username, password })
                       : await self.post("/api/v1/auth/demo", { role });
    setUser(r.user, r.token);
    return user;
  }

  // "Viewing as" control in the sidebar
  let roleInfo = null;
  const ROLE_LABEL = { public: "Public visitor", manufacturer: "Manufacturer", oem: "Vehicle maker", assessor: "Assessor",
                       repurposer: "Repurposer", recycler: "Recycler", regulator: "Regulator", admin: "Administrator" };
  function drawWho() {
    const sel = document.getElementById("roleSelect");
    if (!sel || !roleInfo) return;
    sel.innerHTML = roleInfo.roles.map((r) => `<option value="${r.role}">${ROLE_LABEL[r.role] || r.role}</option>`).join("");
    sel.value = user.role;
    const hint = document.getElementById("whoHint");
    hint.textContent = user.role === "public" ? "Public tier: restricted passport data is hidden."
      : can("upload:create") ? "Full passports. May assess uploads and issue passports."
      : can("audit:read") ? "Full passports and the audit log. Read-only."
      : "Full passports. May sign events for this role.";
  }
  async function initWho() {
    const sel = document.getElementById("roleSelect");
    try { roleInfo = await self.get("/api/v1/auth/roles"); } catch (e) { return; }
    if (token && !self.isStatic) {
      try { const me = await self.get("/api/v1/auth/me"); user = me.role === "public" ? PUBLIC_USER : me; }
      catch (e) { token = null; user = PUBLIC_USER; }
    } else if (self.isStatic) {
      let role = null; try { role = sessionStorage.getItem("bla-role"); } catch (e) {}
      if (role && role !== "public") { try { const r = await self.post("/api/v1/auth/demo", { role }); user = r.user; token = r.token; } catch (e) {} }
    }
    drawWho();
    if (!sel) return;
    const form = document.getElementById("whoForm");
    sel.addEventListener("change", async () => {
      const role = sel.value;
      if (form) form.hidden = true;
      if (role !== "public" && !roleInfo.demo_sign_in && form) {       // real accounts: ask for the password
        form.hidden = false; form.elements.username.value = role; form.elements.password.focus(); return;
      }
      try { await signIn(role); } catch (e) { sel.value = user.role; document.getElementById("whoHint").textContent = e.message; }
    });
    if (form) form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      try { await signIn(sel.value, form.elements.username.value, form.elements.password.value); form.hidden = true; form.reset(); }
      catch (e) { document.getElementById("whoHint").textContent = e.message; }
    });
  }
  let readyResolve;
  const ready = new Promise((res) => { readyResolve = res; });
  document.addEventListener("DOMContentLoaded", () => { initWho().finally(readyResolve); });

  // multipart upload and PDF passports: the hosted (static) build replaces these
  const upload = (form) => request("POST", "/api/v1/uploads", form);
  async function openPdf(pid, access) {
    const r = await fetch(`/api/v1/passports/${encodeURIComponent(pid)}/pdf${access === "public" ? "?access=public" : ""}`,
                          { headers: token ? { Authorization: `Bearer ${token}` } : {} });
    if (!r.ok) throw new Error("Could not create the PDF.");
    window.open(URL.createObjectURL(await r.blob()), "_blank", "noopener");
  }

  const pct = (x, d = 1) => (x == null ? "–" : `${(x * 100).toFixed(d)}%`);
  const num = (x, d = 0) => (x == null ? "–" : Number(x).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d }));
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const ICON = {
    ok: '<svg class="icon" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7" fill="currentColor" opacity=".15"/><path d="M4.5 8.2l2.3 2.3 4.7-4.9" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    bad: '<svg class="icon" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7" fill="currentColor" opacity=".15"/><path d="M5.3 5.3l5.4 5.4M10.7 5.3l-5.4 5.4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
    warn: '<svg class="icon" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.8l6.6 12H1.4z" fill="currentColor" opacity=".18" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/><path d="M8 6.2v3.6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><circle cx="8" cy="11.9" r=".9" fill="currentColor"/></svg>',
    lock: '<svg class="icon" viewBox="0 0 16 16" aria-hidden="true"><rect x="3" y="7" width="10" height="7" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M5.5 7V5a2.5 2.5 0 015 0v2" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>',
  };
  const verdict = (ok, yes = "Valid", no = "Invalid") =>
    ok ? `<span class="ok">${ICON.ok}${yes}</span>` : `<span class="bad">${ICON.bad}${no}</span>`;
  const gradeChip = (g) => (g ? `<span class="grade ${g}" title="Grade ${g}">${g}</span>` : "–");
  const statusChip = (s) => `<span class="status ${esc(s)}">${esc(s)}</span>`;

  // spread end-of-line labels so they never overlap (minGap in y data units)
  function dodge(labels, minGap) {
    const s = labels.slice().sort((a, b) => a.y - b.y);
    for (let i = 1; i < s.length; i++) if (s[i].y - s[i - 1].y < minGap) s[i].y = s[i - 1].y + minGap;
    return s;
  }

  Object.assign(self, { dodge, css, onTheme, cellColor, gradeColor, plot, layout, get, post, request, pct, num, esc,
                        ICON, verdict, gradeChip, statusChip, can, onUser, signIn, ready, upload, openPdf,
                        isStatic: false, ROLE_LABEL });
  Object.defineProperty(self, "user", { get: () => user });
  return self;
})();
