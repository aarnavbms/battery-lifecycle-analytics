(async () => {
  await UI.ready;
  const $ = (id) => document.getElementById(id);
  const [S, H, RL] = await Promise.all([UI.get("/api/v1/openapi.json"), UI.get("/api/v1/health"), UI.get("/api/v1/auth/roles")]);
  const ops = [];
  for (const [path, item] of Object.entries(S.paths)) for (const [method, op] of Object.entries(item)) ops.push({ path, method, ...op });
  const locked = (o) => (o.security || []).some((s) => s.bearer) && !(o.security || []).some((s) => !Object.keys(s).length);

  $("apiFigures").innerHTML = [
    [ops.length, "Endpoints", `in ${S.tags.length} groups`],
    [`v${S.info.version}`, "API version", "OpenAPI 3.0 described"],
    [RL.roles.length, "Roles", "public, five actors, regulator, admin"],
    [Object.values(H.database).reduce((a, b) => a + b, 0).toLocaleString("en-US"), "Database rows", `${Object.keys(H.database).length} tables`],
  ].map(([v, k, d]) => `<div class="fig"><div class="v">${v}</div><div class="k">${k}</div><div class="d">${d}</div></div>`).join("");

  const origin = UI.isStatic ? "http://127.0.0.1:8050" : location.origin;
  $("apiCurl").textContent = [
    "# 1. sign in (demo accounts are in batterylife/service/demo_users.json)",
    `curl -X POST ${origin}/api/v1/auth/login \\`,
    `     -H "Content-Type: application/json" \\`,
    `     -d '{"username": "assessor", "password": "..."}'`,
    "",
    "# 2. assess a file of battery cycles",
    `curl -X POST ${origin}/api/v1/uploads \\`,
    `     -H "Authorization: Bearer <token>" \\`,
    `     -F file=@my_cells.csv -F rated_capacity_ah=2.5`,
    "",
    "# 3. anyone can verify a passport",
    `curl -X POST ${origin}/api/v1/passports/DBP-CALCE-CS2_36/verify`,
  ].join("\n");
  if (UI.isStatic) $("apiSpecLink").removeAttribute("href");

  $("apiRoles").innerHTML = RL.roles.map((r) => `<tr><td><b>${UI.esc(UI.ROLE_LABEL[r.role] || r.role)}</b></td>
    <td>${r.permissions.includes("passport:read_full") ? "Full" : "Public tier"}</td>
    <td>${r.may_sign.length ? r.may_sign.map((e) => UI.esc(e.replace(/_/g, " ").toLowerCase())).join(", ") : "–"}</td>
    <td>${[r.permissions.includes("upload:create") && "assess uploads", r.permissions.includes("audit:read") && "audit log"].filter(Boolean).join(", ") || "–"}</td></tr>`).join("");

  $("apiTryNote").textContent = UI.isStatic
    ? "This hosted copy has no server behind it, so requests cannot be sent from here. Run the project locally to try them."
    : `Requests are sent as the role chosen under "Viewing as" (now: ${UI.ROLE_LABEL[UI.user.role]}).`;
  UI.onUser(() => { if (!UI.isStatic) $("apiTryNote").textContent = `Requests are sent as the role chosen under "Viewing as" (now: ${UI.ROLE_LABEL[UI.user.role]}).`; });

  const example = (o) => { const c = o.requestBody && o.requestBody.content["application/json"]; return c ? c.example : null; };
  const isForm = (o) => o.requestBody && o.requestBody.content["multipart/form-data"];
  $("apiEndpoints").innerHTML = S.tags.map((t) => {
    const list = ops.filter((o) => o.tags[0] === t.name);
    return `<div class="api-group"><h3>${UI.esc(t.name)}</h3>${list.map((o) => {
      const i = ops.indexOf(o), ex = example(o), params = o.parameters || [];
      const codes = Object.keys(o.responses).join(" · ");
      return `<details class="ep" data-i="${i}">
        <summary><span class="verb ${o.method}">${o.method.toUpperCase()}</span><code class="path">${UI.esc(o.path)}</code>
          <span class="sum">${UI.esc(o.summary)}</span>${locked(o) ? `<span class="lock" title="Needs a signed-in role">${UI.ICON.lock}</span>` : ""}</summary>
        <div class="ep-body">
          ${o.description ? `<p class="prose">${UI.esc(o.description).replace(/`([^`]+)`/g, "<code>$1</code>")}</p>` : ""}
          ${params.length ? `<div class="ep-params">${params.map((p) => `<label class="field"><span class="row">${UI.esc(p.name)} <small>${p.in}${p.required ? ", required" : ""}${p.description ? ` · ${UI.esc(p.description)}` : ""}</small></span>
            ${p.schema.enum ? `<select data-p="${p.name}" data-in="${p.in}"><option value="">(not set)</option>${p.schema.enum.map((v) => `<option>${UI.esc(v)}</option>`).join("")}</select>`
              : `<input type="text" data-p="${p.name}" data-in="${p.in}" value="${UI.esc(p.example ?? "")}">`}</label>`).join("")}</div>` : ""}
          ${ex ? `<label class="field"><span class="row">Request body (JSON)</span><textarea rows="${Math.min(8, JSON.stringify(ex, null, 2).split("\n").length)}" spellcheck="false">${UI.esc(JSON.stringify(ex, null, 2))}</textarea></label>` : ""}
          ${isForm(o) ? `<p class="note">This endpoint takes a file. Use the <a href="assess" data-nav-go="assess">Assess your data</a> page, or curl as shown above.</p>` : ""}
          <p class="note">Responses: ${codes}</p>
          ${UI.isStatic || isForm(o) || o.path.endsWith("/pdf") ? "" : `<div class="toolbar"><button class="ghost try" type="button">Send request</button><span class="status-line" role="status"></span></div><pre class="code out" hidden></pre>`}
        </div></details>`;
    }).join("")}</div>`;
  }).join("");

  document.querySelectorAll(".ep .try").forEach((btn) => btn.addEventListener("click", async () => {
    const ep = btn.closest(".ep"), o = ops[+ep.dataset.i], out = ep.querySelector(".out"), line = ep.querySelector(".status-line");
    let url = `/api/v1${o.path}`; const q = [];
    ep.querySelectorAll("[data-p]").forEach((el) => {
      if (el.dataset.in === "path") url = url.replace(`{${el.dataset.p}}`, encodeURIComponent(el.value));
      else if (el.value) q.push(`${el.dataset.p}=${encodeURIComponent(el.value)}`);
    });
    if (q.length) url += `?${q.join("&")}`;
    let body; const ta = ep.querySelector("textarea");
    if (ta) { try { body = JSON.parse(ta.value); } catch (e) { line.textContent = "The request body is not valid JSON."; return; } }
    btn.disabled = true; line.textContent = "Sending…";
    const t0 = performance.now();
    try {
      const r = await UI.request(o.method.toUpperCase(), url, body);
      line.innerHTML = `<span class="ok">${UI.ICON.ok}Success</span> in ${Math.round(performance.now() - t0)} ms`;
      const txt = JSON.stringify(r, null, 2) || "(no content)";
      out.textContent = txt.length > 6000 ? `${txt.slice(0, 6000)}\n… (${txt.length.toLocaleString("en-US")} characters in total)` : txt;
    } catch (e) {
      line.innerHTML = `<span class="bad">${UI.ICON.bad}${e.status || "Error"}</span>`;
      out.textContent = e.message;
    } finally { out.hidden = false; btn.disabled = false; }
  }));

  const T = [["datasets", "Data sources", "dataset_key", "–"], ["cells", "One row per battery", "cell_id", "datasets, uploads"],
    ["cycles", "One row per cycle, with model estimates", "cell_id + cycle", "cells"],
    ["assessments", "Second-life grading decisions", "assessment_id", "cells"],
    ["actors", "Passport actors and public keys", "actor_id", "–"], ["passports", "One row per passport", "passport_id", "–"],
    ["events", "Signed, hash-chained passport events", "passport_id + idx", "passports, actors"],
    ["users", "API accounts with one role each", "username", "–"], ["uploads", "Files assessed through the API", "upload_id", "users"],
    ["audit_log", "Who did what, and when", "audit_id", "users"]];
  $("apiTables").innerHTML = T.map(([n, d, k, l]) => `<tr><td><code>${n}</code></td><td>${d}</td><td><code>${k}</code></td><td>${l}</td><td class="num">${UI.num(H.database[n])}</td></tr>`).join("");
})();
