/* Market Intelligence Engine — dashboard logic (vanilla JS, no build step) */

const state = { week: 8, view: "dashboard" };

const $ = (id) => document.getElementById(id);
const pad2 = (n) => String(n).padStart(2, "0");
const signed = (x) => (x >= 0 ? "+" : "−") + Math.abs(x).toFixed(3);
const titleCase = (s) => (s || "").replace(/_/g, " ");

// Live reward scale — must match config.REWARD_MIN / REWARD_MAX. A recorded
// result of 0% is a genuine loss (the build was wasted); 100% is a top performer.
const REWARD = { lo: -0.15, hi: 1.0 };
const pctToReward = (pct) => REWARD.lo + (REWARD.hi - REWARD.lo) * (pct / 100);

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function toast(html) {
  const t = $("toast");
  t.innerHTML = html;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 2600);
}

/* ---- the signature element: a value point with an uncertainty band ------- */
function convictionSVG(value, unc) {
  const lo = Math.max(0, value - unc), hi = Math.min(1, value + unc);
  const X = (v) => (10 + v * 280).toFixed(1);
  const grid = [0.25, 0.5, 0.75]
    .map((g) => `<line class="cv__grid" x1="${X(g)}" y1="7" x2="${X(g)}" y2="17"/>`)
    .join("");
  return `<svg class="cv" viewBox="0 0 300 24" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
    <line class="cv__track" x1="10" y1="12" x2="290" y2="12"/>
    ${grid}
    <rect class="cv__band" x="${X(lo)}" y="8" width="${(X(hi) - X(lo)).toFixed(1)}" height="8" rx="4"/>
    <circle class="cv__pt" cx="${X(value)}" cy="12" r="4"/>
  </svg>`;
}

/* update an existing card's conviction meter in place, so the dot + band visibly
   glide to the engine's revised belief after a result is recorded */
function setConviction(el, value, unc, roi) {
  const X = (v) => 10 + v * 280;
  const lo = Math.max(0, value - unc), hi = Math.min(1, value + unc);
  const band = el.querySelector(".cv__band");
  const pt = el.querySelector(".cv__pt");
  if (band) {
    band.setAttribute("x", X(lo).toFixed(1));
    band.setAttribute("width", (X(hi) - X(lo)).toFixed(1));
  }
  if (pt) pt.setAttribute("cx", X(value).toFixed(1));
  const roiEl = el.querySelector(".conv__roi");
  if (roiEl) roiEl.textContent = roi.toFixed(2);
  const readout = el.querySelector(".conv__readout");
  if (readout) readout.innerHTML = `est <b>${value.toFixed(2)}</b> ± ${unc.toFixed(2)}`;
}

/* ---- opportunity cards --------------------------------------------------- */
function cardEl(c) {
  const el = document.createElement("article");
  el.className = "card";
  el.dataset.id = c.id;
  el.style.animationDelay = (c.rank - 1) * 0.06 + "s";

  const chips = c.evidence
    .map((e) => {
      const warn = e === "reputation risk" || e === "single-channel only";
      return `<span class="chip${warn ? " chip--warn" : ""}">${e}</span>`;
    })
    .join("");

  const probe = c.exploring
    ? `<span class="probe" title="The engine is uncertain here and is probing to learn">probe</span>`
    : "";

  el.innerHTML = `
    <div class="card__rank">${pad2(c.rank)}</div>
    <div class="card__main">
      <h3 class="card__topic">${c.topic}</h3>
      <div class="card__meta">
        <span class="tag tag--action">${c.action}</span>
        <span class="tag tag--effort-${c.effort}">${c.effort} effort</span>
        ${probe}
      </div>
      <div class="chips">${chips}</div>
    </div>
    <div class="card__conv">
      <div class="conv__row">
        <span class="conv__label">value / effort</span>
        <span class="conv__roi">${c.roi.toFixed(2)}</span>
      </div>
      ${convictionSVG(c.value, c.uncertainty)}
      <div class="conv__readout">est <b>${c.value.toFixed(2)}</b> ± ${c.uncertainty.toFixed(2)}</div>
    </div>
    <div class="result">
      <span class="result__label">Record result</span>
      <input type="range" min="0" max="100" value="50" aria-label="Actual result for ${c.topic}">
      <span class="result__pct">50%</span>
      <button class="btn">Save result</button>
      <div class="result__hint">0% = flopped (the build was wasted) · 100% = a top performer — record what <em>actually</em> happened</div>
    </div>`;

  const range = el.querySelector("input");
  const pct = el.querySelector(".result__pct");
  const btn = el.querySelector(".btn");
  range.addEventListener("input", () => (pct.textContent = range.value + "%"));
  btn.addEventListener("click", () => recordOutcome(c.id, pctToReward(range.value), el, btn, range));
  return el;
}

async function recordOutcome(recId, reward, el, btn, range) {
  btn.disabled = true;
  try {
    const r = await api("/api/outcome", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rec_id: recId, reward }),
    });
    if (!r.ok) { toast(r.error || "Could not record that result."); btn.disabled = false; return; }
    el.classList.add("is-logged");
    btn.textContent = "Recorded ✓";
    if (range) range.disabled = true;          // lock the pick once its result is in
    toast(`Result fed back — the engine has now learned from <b>${r.model_updates}</b> outcomes`);
    // Watch it learn: weights, gauges, conviction meters AND the dashboard KPIs.
    await Promise.all([loadWeights(), loadStatus(), refreshBriefInPlace(), loadDashboard()]);
  } catch (e) {
    toast("Something went wrong recording that result.");
    btn.disabled = false;
  }
}

/* After a result is recorded, slide the visible cards' conviction meters to the
   engine's updated beliefs (the same cards stay in place). If the recorded result
   reshuffled the ranking, fall back to a clean re-render of the new plan. */
async function refreshBriefInPlace() {
  try {
    const data = await api(`/api/brief?week=${state.week}&k=3`);
    const host = $("cards");
    const shown = [...host.querySelectorAll(".card")];
    const shownIds = shown.map((e) => Number(e.dataset.id)).sort((a, b) => a - b);
    const newIds = data.map((c) => c.id).sort((a, b) => a - b);
    const same = shownIds.length === newIds.length &&
                 shownIds.every((v, i) => v === newIds[i]);
    if (!same) {                       // ranking shifted -> show the new plan
      host.innerHTML = "";
      data.forEach((c) => host.appendChild(cardEl(c)));
      return;
    }
    data.forEach((c) => {
      const el = shown.find((e) => Number(e.dataset.id) === c.id);
      if (!el) return;
      setConviction(el, c.value, c.uncertainty, c.roi);
      el.classList.add("is-learning");
      setTimeout(() => el.classList.remove("is-learning"), 800);
    });
  } catch (e) { /* keep the current cards if the refresh fails */ }
}

/* ---- This Week's Plan (full cards) -------------------------------------- */
function loadBrief() {
  const host = $("cards");
  host.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div>';
  $("weekVal").textContent = pad2(state.week);
  return api(`/api/brief?week=${state.week}&k=3`).then((data) => {
    host.innerHTML = "";
    if (!data.length) {
      host.innerHTML = '<p class="lede">No opportunities cleared the bar this week. Step forward a week.</p>';
      return;
    }
    data.forEach((c) => host.appendChild(cardEl(c)));
  }).catch(() => {
    host.innerHTML = '<p class="lede">Could not load the brief. Is the server running?</p>';
  });
}

/* ---- Dashboard overview (KPIs + hero + plan preview) -------------------- */
async function loadDashboard() {
  const [status, rob, brief] = await Promise.all([
    api("/api/status").catch(() => ({})),
    api("/api/robustness").catch(() => null),
    api(`/api/brief?week=${state.week}&k=3`).catch(() => []),
  ]);
  const b = rob && rob.robustness;
  const top = brief[0];

  const kpis = [
    { label: "Top opportunity this week", big: top ? top.topic : "—",
      sub: top ? `value/effort ${top.roi.toFixed(2)} · ${top.action}` : "", accent: "teal" },
    { label: "Proven lift vs fixed scoring", big: b ? `+${Math.round(b.lift_mean)}%` : "—",
      sub: b ? `across ${b.n} simulated markets` : "", accent: "teal" },
    { label: "Head-to-head markets won", big: b ? `${b.wins}/${b.n}` : "—",
      sub: "vs the original fixed-score design", accent: "ink" },
    { label: "Results learned from", big: status.model_updates != null ? String(status.model_updates) : "—",
      sub: "and improving with every one", accent: "amber" },
  ];
  $("kpis").innerHTML = kpis.map((k) => `
    <div class="kpi kpi--${k.accent}">
      <div class="kpi__label">${k.label}</div>
      <div class="kpi__big">${k.big}</div>
      <div class="kpi__sub">${k.sub}</div>
    </div>`).join("");

  if (b) {
    $("heroStat").textContent = `+${Math.round(b.lift_mean)}%`;
    $("heroCap").innerHTML =
      `more real value than the original fixed-score recommender — averaged across
       <b>${b.n} independent markets</b>, winning <b>${b.wins}/${b.n}</b>. Junk pages built:
       <b>${Math.round(b.decoys_static_mean)} → ${Math.round(b.decoys_loop_mean)}</b>.`;
    $("heroSide").innerHTML =
      `<div class="herometric"><b>${b.wins}/${b.n}</b><span>markets won</span></div>
       <div class="herometric"><b>±${b.lift_ci.toFixed(1)}%</b><span>95% CI</span></div>`;
  }

  $("dashPlan").innerHTML = brief.length ? brief.map((c) => `
    <button class="dpitem" data-goto="plan">
      <div class="dpitem__rank">${pad2(c.rank)}</div>
      <div class="dpitem__main">
        <div class="dpitem__topic">${c.topic}</div>
        <div class="dpitem__meta">
          <span class="tag tag--action">${c.action}</span>
          <span class="tag tag--effort-${c.effort}">${c.effort} effort</span>
        </div>
      </div>
      <div class="dpitem__roi">${c.roi.toFixed(2)}<span>value / effort</span></div>
    </button>`).join("") : `<p class="lede">No opportunities cleared the bar this week.</p>`;
  wireGoto();
}

/* ---- weekly intelligence summary (Dashboard) --------------------------- */
function loadSummary() {
  return api("/api/summary").then((s) => {
    if (!s || !s.actions) return;
    const chips = (arr) => (arr || []).map((x) => `<span class="schip">${x}</span>`).join("");
    const acts = s.actions.map((a) =>
      `<li><b>${a.action}</b> — ${a.topic} <span class="schip__roi">ROI ${a.roi.toFixed(2)}</span></li>`).join("");
    $("summaryCard").innerHTML = `
      <div class="summary__head">
        <span class="eyebrow">✦ Weekly intelligence summary · generated from live data</span>
        <span class="summary__mode">${s.data_mode === "real" ? "LIVE DATA" : "demo data"}</span>
      </div>
      <p class="summary__learned">${s.learned}</p>
      <div class="summary__grid">
        <div><div class="summary__lbl">Rising demand</div>${chips(s.rising)}</div>
        <div><div class="summary__lbl">Biggest content gaps</div>${chips(s.gaps)}</div>
        <div><div class="summary__lbl">Already well covered</div>${chips(s.covered)}</div>
      </div>
      <div class="summary__lbl">Recommended actions</div>
      <ol class="summary__acts">${acts}</ol>`;
  }).catch(() => {});
}

/* ---- Signals view: per-category live signals + headlines ---------------- */
function loadSignals() {
  const host = $("signals");
  if (host.dataset.loaded) return Promise.resolve();   // load once per session
  host.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div>';
  return api("/api/signals").then((d) => {
    const items = d.items || [];
    if (!items.length) { host.innerHTML = '<p class="lede">No signals loaded.</p>'; return; }
    const bar = (v, label) => `<div class="sig">
      <span class="sig__lbl">${label}</span>
      <div class="sig__track"><div class="sig__fill" style="width:${Math.round(v * 100)}%"></div></div>
      <span class="sig__val">${v.toFixed(2)}</span></div>`;
    host.innerHTML = items.map((it) => {
      const s = it.signals;
      const heads = (it.headlines || []).slice(0, 2)
        .map((h) => `<div class="sig__news">📰 ${h}</div>`).join("");
      return `<div class="sigrow">
        <div class="sigrow__top">
          <div class="sigrow__name">${it.topic}</div>
          <div class="sigrow__roi">${it.roi.toFixed(2)}<span>value / effort</span></div>
        </div>
        <div class="sigrow__bars">
          ${bar(s.trend_surprise, "demand-trend")}
          ${bar(s.news_relevance, "news")}
          ${bar(s.semantic_gap, "content gap")}
        </div>
        ${heads}
      </div>`;
    }).join("");
    host.dataset.loaded = "1";
  }).catch(() => { host.innerHTML = '<p class="lede">Could not load signals.</p>'; });
}

/* ---- learned-weights diverging bars ------------------------------------- */
function loadWeights() {
  return api("/api/weights").then((data) => {
    const items = data.learned;
    const maxAbs = Math.max(...items.map((d) => Math.abs(d.weight)), 0.01);
    const host = $("weights");
    const rows = {};
    host.querySelectorAll(".wrow").forEach((r) => (rows[r.dataset.name] = r));
    const canUpdate = items.length === Object.keys(rows).length &&
                      items.every((d) => rows[d.name]);

    if (canUpdate) {
      items.forEach((d) => {
        const r = rows[d.name];
        const neg = d.weight < 0;
        const fill = r.querySelector(".wbar__fill");
        fill.className = "wbar__fill " + (neg ? "neg" : "pos");
        fill.style.width = (Math.abs(d.weight) / maxAbs * 48).toFixed(1) + "%";
        r.querySelector(".wrow__val").textContent = signed(d.weight);
        r.classList.toggle("is-distrust", neg && d.name === "tiktok_velocity");
      });
    } else {
      host.innerHTML = items
        .map((d) => {
          const w = Math.abs(d.weight) / maxAbs * 48;
          const neg = d.weight < 0;
          const distrust = neg && d.name === "tiktok_velocity";
          return `<div class="wrow${distrust ? " is-distrust" : ""}" data-name="${d.name}">
            <div class="wrow__label">${d.name}</div>
            <div class="wbar"><div class="wbar__zero"></div>
              <div class="wbar__fill ${neg ? "neg" : "pos"}" style="width:${w.toFixed(1)}%"></div></div>
            <div class="wrow__val">${signed(d.weight)}</div>
          </div>`;
        })
        .join("");
    }

    const tiktok = items.find((d) => d.name === "tiktok_velocity");
    if (data.model_updates >= 6 && tiktok && tiktok.weight < 0) {
      $("weightsNote").innerHTML =
        `After <b>${data.model_updates}</b> results, the engine drove <b>tiktok_velocity negative</b> — it taught itself that loud single-channel hype predicts wasted effort, even though the original design trusted it at +0.15.`;
    } else {
      $("weightsNote").innerHTML =
        `Weights start near zero and move as results arrive. Record a few outcomes and watch them separate — this is the engine learning what actually pays.`;
    }
  });
}

/* ---- status: gauges + rail + client chip + settings -------------------- */
function loadStatus() {
  return api("/api/status").then((s) => {
    $("gRecs").textContent = s.recommendations;
    $("gOuts").textContent = s.outcomes;
    $("gUpd").textContent = s.model_updates;
    $("gAvg").textContent = s.avg_reward == null ? "—" : s.avg_reward.toFixed(2);
    $("railUpd").textContent = s.model_updates == null ? "—" : s.model_updates;
    $("railAvg").textContent = s.avg_reward == null ? "—" : s.avg_reward.toFixed(2);

    const c = s.client || {};
    if (c.name) {
      $("clientChip").textContent = c.name + (c.industry ? " · " + titleCase(c.industry) : "");
      $("railClient").textContent = c.name;
    }
    $("cfg").innerHTML = c.name ? `
      <div class="cfgrow"><span>Client</span><b>${c.name}</b></div>
      <div class="cfgrow"><span>Industry</span><b>${titleCase(c.industry)}</b></div>
      <div class="cfgrow"><span>Category framework</span><b>${c.categories} categories</b></div>
      <div class="cfgrow"><span>Website (content-gap source)</span><b>${c.site_source}</b></div>
      <div class="cfgrow"><span>Data mode</span><b>${s.data_mode}</b></div>
      <div class="cfgrow"><span>Source</span><b>${c.is_demo ? "built-in demo client" : "configured via env"}</b></div>
      <p class="cfg__note">Onboard a new client by setting <code>CLIENT_NAME</code>, <code>CLIENT_INDUSTRY</code>,
        <code>CLIENT_CATEGORIES</code> and <code>SITE_URL</code> — no code change.</p>` : "";
  });
}

/* ---- head-to-head proof chart ------------------------------------------- */
function proofSVG(d) {
  const W = 380, H = 188, pad = { l: 30, r: 12, t: 12, b: 24 };
  const n = d.weeks.length;
  const maxY = Math.max(...d.loop, ...d.static) * 1.05;
  const X = (i) => pad.l + (i / (n - 1)) * (W - pad.l - pad.r);
  const Y = (v) => H - pad.b - (v / maxY) * (H - pad.t - pad.b);
  const path = (arr) => arr.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");

  const fwd = d.loop.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");
  const back = d.static.map((v, i) => `L${X(n - 1 - i).toFixed(1)},${Y(d.static[n - 1 - i]).toFixed(1)}`).join(" ");
  const area = `${fwd} ${back} Z`;

  const yTicks = [0, maxY].map(
    (v) => `<text x="${pad.l - 6}" y="${(Y(v) + 3).toFixed(1)}" text-anchor="end"
              font-family="IBM Plex Mono" font-size="9" fill="#9AA1AC">${Math.round(v)}</text>`).join("");
  const xLabels = [0, Math.floor((n - 1) / 2), n - 1].map(
    (i) => `<text x="${X(i).toFixed(1)}" y="${H - 8}" text-anchor="middle"
              font-family="IBM Plex Mono" font-size="9" fill="#9AA1AC">w${d.weeks[i]}</text>`).join("");

  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" role="img"
              aria-label="Cumulative value: closed-loop vs static">
    <line x1="${pad.l}" y1="${H - pad.b}" x2="${W - pad.r}" y2="${H - pad.b}" stroke="#E6E8EC"/>
    <line x1="${pad.l}" y1="${pad.t}" x2="${pad.l}" y2="${H - pad.b}" stroke="#E6E8EC"/>
    ${yTicks}${xLabels}
    <path d="${area}" fill="rgba(15,118,110,.10)"/>
    <path d="${path(d.static)}" fill="none" stroke="#9AA1AC" stroke-width="2"/>
    <path d="${path(d.loop)}" fill="none" stroke="#0F766E" stroke-width="2.4"/>
  </svg>`;
}

/* ---- ablation: what each upgrade adds (hand-built bars, no chart lib) ----- */
function renderAblation(rows) {
  if (!rows || !rows.length) return;
  const friendly = {
    P0: "The original scorer",
    P1: "+ Weigh effort (ROI)",
    P2: "+ Avoid overlap",
    P3: "+ Learn from results",
    P4: "+ Explore the unknown",
  };
  const maxMean = Math.max(...rows.map((r) => r.mean));
  $("ablation").innerHTML = rows
    .map((r) => {
      const code = r.name.trim().split(/\s+/)[0];
      const closed = code === "P3" || code === "P4";
      const w = (r.mean / maxMean * 100).toFixed(1);
      const delta = r.delta == null ? ""
        : `<span class="${r.delta > 0 ? "up" : ""}">${r.delta > 0 ? "+" : "−"}${Math.abs(r.delta).toFixed(1)}</span>`;
      return `<div class="ablrow ${closed ? "closed" : "open"}">
        <div class="ablrow__label">${friendly[code] || r.name}</div>
        <div class="ablbar"><div class="ablbar__fill" style="width:${w}%"></div></div>
        <div class="ablrow__val">${r.mean.toFixed(1)} ${delta}</div>
      </div>`;
    })
    .join("");
  $("ablationNote").innerHTML =
    `Each rung turns on one more idea, measured across the same 30 markets. The big jumps are <b>weighing effort</b> and <b>learning from results</b> (which also collapses junk pages from ~9 to ~1). Grey rungs are still open-loop; teal is the engine learning from outcomes.`;
}

function loadProof() {
  const sim = api("/api/simulate").then((d) => {
    $("proof").innerHTML = proofSVG(d);
    $("proofNote").innerHTML =
      `This curve is <b>one representative market</b>, same budget, 20 weeks: the closed-loop engine captured <b>+${d.lift_pct}%</b> more value while building <b>${d.decoys_static - d.decoys_loop} fewer</b> junk pages (${d.decoys_loop} vs ${d.decoys_static}).`;
  }).catch(() => {});

  const rob = api("/api/robustness")
    .then((r) => {
      if (!r || !r.robustness) return;
      const b = r.robustness;
      $("robustStat").innerHTML =
        `<div class="robust__big">+${Math.round(b.lift_mean)}%
           <span>± ${b.lift_ci.toFixed(1)}% · 95% CI</span></div>
         <div class="robust__cap">more real value than the original scorer, averaged across
           <b>${b.n} independent markets</b> — and the closed loop won <b>${b.wins}/${b.n}</b> of them.
           Junk pages built: <b>${Math.round(b.decoys_static_mean)} → ${Math.round(b.decoys_loop_mean)}</b>.</div>`;
      renderAblation(r.ablation);
    })
    .catch(() => {});

  return Promise.all([sim, rob]);
}

/* ---- view routing ------------------------------------------------------- */
const VIEW_META = {
  dashboard: ["Overview", "Dashboard"],
  plan: ["This week", "Recommended plan"],
  signals: ["Live signals", "Signals"],
  proof: ["Controlled backtest", "Does it actually work?"],
  learning: ["The closed loop", "What it's learned"],
  settings: ["Configuration", "Client & settings"],
};

function showView(name) {
  if (!VIEW_META[name]) name = "dashboard";
  state.view = name;
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("view--active", v.id === "view-" + name));
  document.querySelectorAll(".nav__item").forEach((n) => n.classList.toggle("is-active", n.dataset.view === name));
  const [eb, t] = VIEW_META[name];
  $("viewEyebrow").textContent = eb;
  $("viewTitle").textContent = t;
  if (name === "dashboard") loadDashboard();
  if (name === "signals") loadSignals();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function wireGoto() {
  document.querySelectorAll("[data-goto]").forEach((b) => {
    if (b._wired) return;
    b._wired = true;
    b.addEventListener("click", () => showView(b.dataset.goto));
  });
}

/* ---- wiring ------------------------------------------------------------- */
function setWeek(w) {
  state.week = Math.max(0, Math.min(19, w));
  loadBrief();
}
document.querySelectorAll(".nav__item").forEach((n) =>
  n.addEventListener("click", () => showView(n.dataset.view)));
$("weekUp").addEventListener("click", () => setWeek(state.week + 1));
$("weekDown").addEventListener("click", () => setWeek(state.week - 1));
$("resetBtn").addEventListener("click", async () => {
  await api("/api/reset", { method: "POST" });
  toast("Learning reset — the engine starts fresh");
  await Promise.all([loadBrief(), loadWeights(), loadStatus(), loadDashboard()]);
});

/* ---- virtual assistant -------------------------------------------------- */
const asst = { open: false, busy: false };
function asstAdd(role, text) {
  const log = $("asstLog");
  const el = document.createElement("div");
  el.className = "asstmsg asstmsg--" + role;
  el.textContent = text;
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
  return el;
}
function asstToggle(show) {
  asst.open = show === undefined ? !asst.open : show;
  $("asst").hidden = !asst.open;
  $("asstFab").style.display = asst.open ? "none" : "";
  if (asst.open && !$("asstLog").children.length) {
    asstAdd("bot", "Hi — I answer from this client's live data. Try: “what should we do first?”, " +
      "“what's trending?”, “where are the content gaps?”, or “does it actually work?”");
    if (window.innerWidth > 600) $("asstInput").focus();
  }
}
async function asstSend(q) {
  if (!q || asst.busy) return;
  asst.busy = true;
  asstAdd("user", q);
  const thinking = asstAdd("bot", "…");
  try {
    const r = await api("/api/assistant", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q }),
    });
    thinking.textContent = r.answer || "I don't have that in the data.";
  } catch (e) {
    thinking.textContent = "Sorry — something went wrong.";
  }
  asst.busy = false;
}
$("asstFab").addEventListener("click", () => asstToggle(true));
$("asstClose").addEventListener("click", () => asstToggle(false));
$("asstForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const i = $("asstInput");
  const q = i.value.trim();
  i.value = "";
  asstSend(q);
});

// initial load
loadBrief();
loadWeights();
loadStatus();
loadProof();
loadDashboard();
loadSummary();
wireGoto();
showView("dashboard");
