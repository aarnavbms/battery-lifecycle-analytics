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

  async function get(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`${url}: ${r.status}`);
    return r.json();
  }
  async function post(url, body) {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
                                 body: JSON.stringify(body || {}) });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || r.status);
    return j;
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

  return { dodge, css, onTheme, cellColor, gradeColor, plot, layout, get, post, pct, num, esc, ICON, verdict,
           gradeChip, statusChip };
})();
