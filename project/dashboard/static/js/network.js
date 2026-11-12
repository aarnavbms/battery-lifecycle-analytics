(async () => {
  const N = await UI.get("/api/v1/network");
  const $ = (id) => document.getElementById(id);
  const ROLE_SLOT = { manufacturer: "--s1", oem: "--s2", bms: "--s4", assessor: "--s3", repurposer: "--s1", recycler: "--muted" };
  const short = (s) => s.replace(/\s*\(.*\)$/, "");

  const f = N.findings, h = N.handoff, p = N.process;
  $("netFigures").innerHTML = [
    [N.events, "Signed events", `on ${N.passports} passports`],
    [h.nodes.length, "Actors", `${h.stats.edges} hand-off links between them`],
    [h.stats.total_weight, "Hand-offs", "a different actor signs the next event"],
    [`${(h.stats.reciprocity * 100).toFixed(0)}<small>%</small>`, "Two-way links", "reciprocity of the actor network"],
  ].map(([v, k, d]) => `<div class="fig"><div class="v">${v}</div><div class="k">${k}</div><div class="d">${d}</div></div>`).join("");
  const idle = h.nodes.filter((n) => n.events === 0).map((n) => short(n.name));
  $("netFinding").innerHTML = `<b>${UI.esc(short(f.broker_name))} is the broker of this network.</b> It has the highest betweenness (${f.broker_betweenness.toFixed(2)}) and the highest PageRank: every battery passes through it between first life and second life, so the passport system depends on it most. The busiest lifecycle step is ${UI.esc(f.process_hub.replace(/_/g, " ").toLowerCase().replace("soh", "SOH").replace("rul", "RUL"))}.${idle.length ? ` ${UI.esc(idle.join(", "))} has signed nothing yet, because no battery in the study has reached final recycling.` : ""}`;

  $("netActorRows").innerHTML = h.nodes.slice().sort((a, b) => b.pagerank - a.pagerank).map((n) => `
    <tr><td><b>${UI.esc(n.id)}</b><br><span class="sub">${UI.esc(short(n.name))}</span></td>
      <td class="num">${n.batteries}</td><td class="num">${n.events}</td><td class="num">${n.in}</td><td class="num">${n.out}</td>
      <td class="num">${n.betweenness.toFixed(3)}</td><td class="num">${n.pagerank.toFixed(3)}</td></tr>`).join("");
  $("netActorStats").textContent = `Density ${h.stats.density.toFixed(2)}, reciprocity ${h.stats.reciprocity.toFixed(2)}, ${h.stats.edges} directed links.`;
  $("netPaths").innerHTML = N.paths.map((x) => `<li><b>${x.batteries} ${x.batteries === 1 ? "battery" : "batteries"}</b>
    <span>${x.path.split(" > ").map((s) => UI.esc(s.replace(/_/g, " ").toLowerCase())).join(" <i>→</i> ")}</span></li>`).join("");
  $("netProcStats").textContent = `${p.nodes.length} event types, ${p.stats.edges} kinds of transition, ${p.stats.total_weight} transitions in total. Density ${p.stats.density.toFixed(2)}.`;

  // Directed graph on a cartesian plot: one line per edge (offset sideways so A>B and B>A stay apart),
  // an arrowhead annotation near the target, and sized markers for nodes.
  function draw(el, G, opt) {
    const pos = Object.fromEntries(G.nodes.map((n) => [n.id, n]));
    const maxW = Math.max(...G.edges.map((e) => e.weight), 1);
    const ink = UI.css("--ink-2"), traces = [], ann = [];
    for (const e of G.edges) {
      const a = pos[e.source], b = pos[e.target];
      const dx = b.x - a.x, dy = b.y - a.y, L = Math.hypot(dx, dy) || 1, ox = (-dy / L) * 0.045, oy = (dx / L) * 0.045;
      const x0 = a.x + ox, y0 = a.y + oy, x1 = b.x + ox, y1 = b.y + oy;
      const w = 1 + 5 * (e.weight / maxW);
      traces.push({ x: [x0, x1], y: [y0, y1], mode: "lines", line: { color: ink, width: w }, opacity: 0.55, hoverinfo: "skip", showlegend: false });
      const t = 1 - opt.gap / L;                         // stop short of the target circle
      ann.push({ x: x0 + (x1 - x0) * t, y: y0 + (y1 - y0) * t, ax: x0 + (x1 - x0) * (t - 0.12), ay: y0 + (y1 - y0) * (t - 0.12),
                 xref: "x", yref: "y", axref: "x", ayref: "y", showarrow: true, arrowhead: 2, arrowsize: 1.1, arrowwidth: Math.max(1.4, w * 0.7),
                 arrowcolor: ink, opacity: 0.8, text: "" });
      traces.push({ x: [(x0 + x1) / 2], y: [(y0 + y1) / 2], mode: "markers", marker: { size: 14, color: "rgba(0,0,0,0)" }, showlegend: false,
        hovertemplate: `${UI.esc(opt.label(a))} → ${UI.esc(opt.label(b))}<br>${e.weight} time${e.weight === 1 ? "" : "s"}<extra></extra>` });
    }
    traces.push({ x: G.nodes.map((n) => n.x), y: G.nodes.map((n) => n.y), mode: "markers+text", text: G.nodes.map(opt.label),
      textposition: G.nodes.map((n) => (Math.abs(n.x) > 0.3 ? (n.x > 0 ? "middle right" : "middle left") : n.y > 0 ? "top center" : "bottom center")),
      textfont: { color: UI.css("--ink"), size: 12.5 }, cliponaxis: false, showlegend: false,
      marker: { size: G.nodes.map(opt.size), color: G.nodes.map(opt.color), line: { color: UI.css("--surface"), width: 2 } },
      customdata: G.nodes.map(opt.hover), hovertemplate: "%{customdata}<extra></extra>" });
    UI.plot(el, traces, { annotations: ann, margin: { l: 10, r: 10, t: 10, b: 10 }, hovermode: "closest",
      xaxis: { visible: false, range: [-opt.span, opt.span], fixedrange: true }, yaxis: { visible: false, range: [-1.35, 1.35], fixedrange: true } });
  }
  function render() {
    draw("netActors", h, { gap: 0.2, span: 2.0, label: (n) => n.id, size: (n) => 22 + 70 * n.pagerank,
      color: (n) => UI.css(ROLE_SLOT[n.role] || "--muted"),
      hover: (n) => `<b>${UI.esc(n.id)}</b> (${UI.esc(n.role)})<br>${n.events} events on ${n.batteries} batteries<br>in ${n.in}, out ${n.out}<br>betweenness ${n.betweenness.toFixed(3)}<br>PageRank ${n.pagerank.toFixed(3)}` });
    const maxDeg = Math.max(...p.nodes.map((n) => n.in + n.out), 1);
    draw("netProcess", p, { gap: 0.16, span: 2.3, label: (n) => n.name, size: (n) => 16 + 30 * ((n.in + n.out) / maxDeg),
      color: (n) => UI.css(n.access === "public" ? "--s1" : "--s3"),
      hover: (n) => `<b>${UI.esc(n.name)}</b><br>${n.access === "public" ? "public" : "restricted"} event, signed by ${UI.esc(n.roles.join(" or "))}<br>entered ${n.in} times, left ${n.out} times<br>betweenness ${n.betweenness.toFixed(3)}` });
  }
  render();
  UI.onTheme(render);
})();
