/* Market Intelligence Engine — dashboard logic (vanilla JS, no build step) */

const state = { week: 8, view: "dashboard" };

const $ = (id) => document.getElementById(id);
const pad2 = (n) => String(n).padStart(2, "0");
const titleCase = (s) => (s || "").replace(/_/g, " ");

// Live reward scale — must match config.REWARD_MIN / REWARD_MAX.
const REWARD = { lo: -0.15, hi: 1.0 };
// 5-point agree/disagree verdict, mapped evenly across the reward scale.
const _mix = (t) => Math.round((REWARD.lo + (REWARD.hi - REWARD.lo) * t) * 1000) / 1000;
const LIKERT = [
  ["Strongly disagree", "sd", _mix(0)],
  ["Disagree", "d", _mix(0.25)],
  ["Neutral", "n", _mix(0.5)],
  ["Agree", "a", _mix(0.75)],
  ["Strongly agree", "sa", _mix(1)],
];

/* ---- plain-language helpers: speak to marketers, not ML engineers ------- */
const FEATURE_LABEL = {
  trend_surprise: "Rising search demand",
  trend_changepoint: "Sudden demand spike",
  reddit_growth: "Reddit buzz",
  reddit_neg_sentiment: "Complaints / reputation",
  tiktok_velocity: "TikTok hype",
  news_relevance: "In the news",
  semantic_gap: "Gap on your site",
  cross_source_agreement: "Multiple sources agree",
};
const CHIP_LABEL = {
  "demand rising": "Rising demand",
  "search rise": "Rising demand",
  "change-point": "Sudden spike",
  "content gap": "Gap on your site",
  "reputation risk": "Reputation risk",
  "single-channel only": "Only one source — be cautious",
  "multi-source": "Multiple sources agree",
};
const EFFORT_LABEL = { low: "Low", med: "Medium", high: "High" };

const priorityOf = (roi) =>
  roi >= 0.62 ? ["High", "is-high"] : roi >= 0.4 ? ["Medium", "is-med"] : ["Low", "is-low"];
// Prefer the server's relative priority (robust as the model learns); fall back
// to an absolute ROI band if it's absent.
const PRIO_CLASS = { High: "is-high", Medium: "is-med", Low: "is-low" };
const prioOf = (item) =>
  item && item.priority ? [item.priority, PRIO_CLASS[item.priority] || "is-med"]
                        : priorityOf(item && item.roi);
const confidenceOf = (unc) =>
  unc < 0.18 ? ["High", "is-high"] : unc < 0.35 ? ["Medium", "is-med"] : ["Still learning", "is-low"];
const actionVerb = (a) =>
  (a || "").toLowerCase().startsWith("create") ? ["Create a page for", ""] : ["Strengthen your", " page"];
const whyLine = (c) => {
  const ev = (c.evidence || []).map((e) => CHIP_LABEL[e] || e);
  return ev.length ? ev.join(" · ") : "Flagged by this week's market signals.";
};

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

/* ---- the signature element: how-sure-we-are meter (dot + band) ---------- */
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

/* slide a card's meter + labels to the engine's revised belief after a result */
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
  if (roiEl) { const [p, cls] = priorityOf(roi); roiEl.textContent = p; roiEl.className = "conv__roi prio " + cls; }
  const readout = el.querySelector(".conv__readout");
  if (readout) { const [cf, cc] = confidenceOf(unc); readout.innerHTML = `Confidence: <b class="${cc}">${cf}</b>`; }
}

/* ---- opportunity cards --------------------------------------------------- */
function cardEl(c) {
  const el = document.createElement("article");
  el.className = "card";
  el.dataset.id = c.id;
  el.style.animationDelay = (c.rank - 1) * 0.06 + "s";

  const [prio, prioCls] = prioOf(c);
  const [conf, confCls] = confidenceOf(c.uncertainty);
  const [verb, suffix] = actionVerb(c.action);
  const test = c.exploring
    ? `<span class="tag tag--test" title="We're less sure here — worth a quick test to find out">Worth a test</span>` : "";
  const news = (c.headlines && c.headlines[0])
    ? `<div class="card__news">📰 In the news: “${c.headlines[0]}”</div>` : "";

  el.innerHTML = `
    <div class="card__rank">${pad2(c.rank)}</div>
    <div class="card__main">
      <h3 class="card__topic">${verb} ${c.topic}${suffix}</h3>
      <p class="card__why">${whyLine(c)}</p>
      ${news}
      <div class="card__meta">
        <span class="tag tag--effort-${c.effort}">${EFFORT_LABEL[c.effort] || c.effort} effort</span>
        ${test}
        <button class="planbtn" type="button">✦ Get the AI action plan</button>
      </div>
      <div class="plan" hidden></div>
    </div>
    <div class="card__conv">
      <div class="conv__row">
        <span class="conv__label">Priority</span>
        <span class="conv__roi prio ${prioCls}">${prio}</span>
      </div>
      ${convictionSVG(c.strength != null ? c.strength : c.value, c.uncertainty)}
      <div class="conv__readout">Confidence: <b class="${confCls}">${conf}</b></div>
    </div>
    <div class="result">
      <span class="result__label">Was this a good call?</span>
      <div class="likert" role="group" aria-label="Your verdict on this recommendation">
        ${LIKERT.map(([label, cls, r]) => `<button type="button" class="lk lk--${cls}" data-r="${r}">${label}</button>`).join("")}
      </div>
      <div class="result__hint">Your verdict trains the system — it learns which signals lead to wins.</div>
    </div>`;

  el.querySelectorAll(".lk").forEach((b) =>
    b.addEventListener("click", () => recordLikert(c.id, Number(b.dataset.r), el, b)));
  const planBtn = el.querySelector(".planbtn");
  const planHost = el.querySelector(".plan");
  planBtn.addEventListener("click", () => loadPlan(c, planBtn, planHost));
  return el;
}

/* ---- AI Strategist: a grounded, client-ready action plan per pick ------- */
function planHTML(p) {
  const pts = (p.points || []).map((x) => `<li>${x}</li>`).join("");
  const badge = p.source === "ai"
    ? `<span class="plan__tag">✦ AI-written</span>`
    : `<span class="plan__tag plan__tag--tpl">grounded plan</span>`;
  return `<div class="plan__head">Suggested action plan ${badge}</div>
    <div class="plan__title">${p.title || ""}</div>
    <div class="plan__row"><span>Angle</span><p>${p.angle || ""}</p></div>
    <div class="plan__row"><span>Why now</span><p>${p.why_now || ""}</p></div>
    <div class="plan__row"><span>Cover</span><ul>${pts}</ul></div>`;
}

async function loadPlan(c, btn, host) {
  if (host.dataset.loaded) {                       // toggle once generated
    host.hidden = !host.hidden;
    btn.textContent = host.hidden ? "✦ Get the AI action plan" : "✦ Hide action plan";
    return;
  }
  btn.disabled = true;
  const orig = btn.textContent;
  btn.textContent = "✦ Writing your plan…";
  host.hidden = false;
  host.innerHTML = '<div class="plan__loading">Thinking through the play…</div>';
  try {
    const p = await api("/api/playbook", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic: c.topic, action: c.action, effort: c.effort,
                             headlines: c.headlines || [], signals: c.signals || {} }),
    });
    host.innerHTML = planHTML(p);
    host.dataset.loaded = "1";
    btn.textContent = "✦ Hide action plan";
  } catch (e) {
    host.innerHTML = '<div class="plan__loading">Could not generate a plan right now.</div>';
    btn.textContent = orig;
  } finally {
    btn.disabled = false;
  }
}

async function recordLikert(recId, reward, el, btn) {
  const group = btn.parentElement;
  const unlock = () => group.querySelectorAll(".lk").forEach((b) => (b.disabled = false));
  group.querySelectorAll(".lk").forEach((b) => (b.disabled = true));
  btn.classList.add("is-picked");
  try {
    const r = await api("/api/outcome", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rec_id: recId, reward }),
    });
    if (!r.ok) { toast(r.error || "Could not record that."); btn.classList.remove("is-picked"); unlock(); return; }
    el.classList.add("is-logged");
    toast(`Saved — the system just learned from your verdict (<b>${r.model_updates}</b> total)`);
    await Promise.all([loadWeights(), loadStatus(), refreshBriefInPlace(), loadDashboard()]);
  } catch (e) {
    toast("Something went wrong saving that.");
    btn.classList.remove("is-picked");
    unlock();
  }
}

/* after a result, slide the visible cards to the system's updated view */
async function refreshBriefInPlace() {
  try {
    const data = await api(`/api/brief?week=${state.week}&k=3`);
    const host = $("cards");
    const shown = [...host.querySelectorAll(".card")];
    const shownIds = shown.map((e) => Number(e.dataset.id)).sort((a, b) => a - b);
    const newIds = data.map((c) => c.id).sort((a, b) => a - b);
    const same = shownIds.length === newIds.length && shownIds.every((v, i) => v === newIds[i]);
    if (!same) { host.innerHTML = ""; data.forEach((c) => host.appendChild(cardEl(c))); return; }
    data.forEach((c) => {
      const el = shown.find((e) => Number(e.dataset.id) === c.id);
      if (!el) return;
      setConviction(el, c.strength != null ? c.strength : c.value, c.uncertainty, c.roi);
      el.classList.add("is-learning");
      setTimeout(() => el.classList.remove("is-learning"), 800);
    });
  } catch (e) { /* keep current cards if refresh fails */ }
}

/* ---- What to do this week (full cards) ---------------------------------- */
function loadBrief() {
  const host = $("cards");
  host.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div>';
  $("weekVal").textContent = pad2(state.week);
  return api(`/api/brief?week=${state.week}&k=3`).then((data) => {
    host.innerHTML = "";
    if (!data.length) {
      host.innerHTML = '<p class="lede">No clear opportunities this week. Step forward a week.</p>';
      return;
    }
    data.forEach((c) => host.appendChild(cardEl(c)));
  }).catch(() => {
    host.innerHTML = '<p class="lede">Could not load this week’s plan. Is the server running?</p>';
  });
}

/* ---- Dashboard overview (KPIs + hero + plan preview) -------------------- */
async function loadDashboard() {
  const [status, brief] = await Promise.all([
    api("/api/status").catch(() => ({})),
    api(`/api/brief?week=${state.week}&k=3`).catch(() => []),
  ]);
  const top = brief[0];
  const cats = (status.client && status.client.categories) || "—";
  const live = status.data_mode === "real" ? "Real" : "Demo";
  const updates = status.model_updates != null ? String(status.model_updates) : "—";

  const kpis = [
    { label: "Do this first", big: top ? top.topic : "—",
      sub: top ? `${prioOf(top)[0]} priority · ${(top.action || "").toLowerCase()}` : "", accent: "teal" },
    { label: "Categories watched", big: String(cats),
      sub: "monitored live, every week", accent: "ink" },
    { label: "Live data", big: live,
      sub: "news · your site · TikTok", accent: "teal" },
    { label: "Results learned from", big: updates,
      sub: "sharper with every one", accent: "amber" },
  ];
  $("kpis").innerHTML = kpis.map((k) => `
    <div class="kpi kpi--${k.accent}">
      <div class="kpi__label">${k.label}</div>
      <div class="kpi__big">${k.big}</div>
      <div class="kpi__sub">${k.sub}</div>
    </div>`).join("");

  $("heroStat").textContent = updates;
  $("heroCap").innerHTML =
    `results learned from so far — every outcome you record sharpens next week's plan.`;
  $("heroSide").innerHTML =
    `<div class="herometric"><b>${cats}</b><span>categories watched</span></div>
     <div class="herometric"><b>${live}</b><span>live data</span></div>`;

  $("dashPlan").innerHTML = brief.length ? brief.map((c) => {
    const [p, pc] = prioOf(c);
    return `<button class="dpitem" data-goto="plan">
      <div class="dpitem__rank">${pad2(c.rank)}</div>
      <div class="dpitem__main">
        <div class="dpitem__topic">${c.topic}</div>
        <div class="dpitem__meta">
          <span class="tag tag--action">${c.action}</span>
          <span class="tag tag--effort-${c.effort}">${EFFORT_LABEL[c.effort] || c.effort} effort</span>
        </div>
      </div>
      <div class="dpitem__roi prio ${pc}">${p}<span>priority</span></div>
    </button>`;
  }).join("") : `<p class="lede">No clear opportunities this week.</p>`;
  wireGoto();
}

/* ---- weekly intelligence summary (Dashboard) --------------------------- */
function loadSummary() {
  return api("/api/summary").then((s) => {
    if (!s || !s.actions) return;
    const chips = (arr) => (arr || []).map((x) => `<span class="schip">${x}</span>`).join("");
    const acts = s.actions.map((a) => {
      const [p] = prioOf(a);
      return `<li><b>${a.action}</b> — ${a.topic} <span class="schip__roi">${p} priority</span></li>`;
    }).join("");
    $("summaryCard").innerHTML = `
      <div class="summary__head">
        <span class="eyebrow">✦ This week's read on the market · from live data</span>
        <span class="summary__mode">${s.data_mode === "real" ? "LIVE DATA" : "demo data"}</span>
      </div>
      <p class="summary__learned">${s.learned}</p>
      <div class="summary__grid">
        <div><div class="summary__lbl">Demand rising fastest</div>${chips(s.rising)}</div>
        <div><div class="summary__lbl">Biggest gaps on your site</div>${chips(s.gaps)}</div>
        <div><div class="summary__lbl">Already well covered</div>${chips(s.covered)}</div>
      </div>
      <div class="summary__lbl">What to do</div>
      <ol class="summary__acts">${acts}</ol>`;
  }).catch(() => {});
}

/* ---- Market signals view ------------------------------------------------ */
function loadSignals() {
  const host = $("signals");
  if (host.dataset.loaded) return Promise.resolve();
  host.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div>';
  return api("/api/signals").then((d) => {
    const items = d.items || [];
    if (!items.length) { host.innerHTML = '<p class="lede">No signals loaded yet.</p>'; return; }
    const bar = (v, label) => `<div class="sig">
      <span class="sig__lbl">${label}</span>
      <div class="sig__track"><div class="sig__fill" style="width:${Math.round(v * 100)}%"></div></div>
      <span class="sig__val">${Math.round(v * 100)}</span></div>`;
    host.innerHTML = items.map((it) => {
      const s = it.signals;
      const [p, pc] = prioOf(it);
      const heads = (it.headlines || []).slice(0, 2).map((h) => `<div class="sig__news">📰 ${h}</div>`).join("");
      const vol = it.volume != null
        ? `<div class="sigrow__vol">🔍 ${it.volume.toLocaleString()} searches/mo</div>` : "";
      return `<div class="sigrow">
        <div class="sigrow__top">
          <div>
            <div class="sigrow__name">${it.topic}</div>
            ${vol}
          </div>
          <div class="sigrow__roi prio ${pc}">${p}<span>priority</span></div>
        </div>
        <div class="sigrow__bars">
          ${bar(s.trend_surprise, "Search demand")}
          ${bar(s.news_relevance, "In the news")}
          ${bar(s.semantic_gap, "Gap on your site")}
        </div>
        ${heads}
      </div>`;
    }).join("");
    host.dataset.loaded = "1";
  }).catch(() => { host.innerHTML = '<p class="lede">Could not load market signals.</p>'; });
}

/* ---- what the system has learned matters (plain language) -------------- */
function loadWeights() {
  return api("/api/weights").then((data) => {
    const items = data.learned;
    const maxAbs = Math.max(...items.map((d) => Math.abs(d.weight)), 0.01);
    const host = $("weights");
    const verdict = (w) => (w < -0.02 ? "doesn’t pay off" : w > 0.15 ? "matters a lot" : w > 0.05 ? "helps" : "minor");
    const rows = {};
    host.querySelectorAll(".wrow").forEach((r) => (rows[r.dataset.name] = r));
    const canUpdate = items.length === Object.keys(rows).length && items.every((d) => rows[d.name]);

    if (canUpdate) {
      items.forEach((d) => {
        const r = rows[d.name];
        const neg = d.weight < 0;
        const fill = r.querySelector(".wbar__fill");
        fill.className = "wbar__fill " + (neg ? "neg" : "pos");
        fill.style.width = (Math.abs(d.weight) / maxAbs * 48).toFixed(1) + "%";
        r.querySelector(".wrow__val").textContent = verdict(d.weight);
        r.classList.toggle("is-distrust", neg && d.name === "tiktok_velocity");
      });
    } else {
      host.innerHTML = items.map((d) => {
        const w = Math.abs(d.weight) / maxAbs * 48;
        const neg = d.weight < 0;
        const distrust = neg && d.name === "tiktok_velocity";
        return `<div class="wrow${distrust ? " is-distrust" : ""}" data-name="${d.name}">
          <div class="wrow__label">${FEATURE_LABEL[d.name] || titleCase(d.name)}</div>
          <div class="wbar"><div class="wbar__zero"></div>
            <div class="wbar__fill ${neg ? "neg" : "pos"}" style="width:${w.toFixed(1)}%"></div></div>
          <div class="wrow__val">${verdict(d.weight)}</div>
        </div>`;
      }).join("");
    }

    const positives = items.filter((d) => d.weight > 0.05).map((d) => FEATURE_LABEL[d.name] || titleCase(d.name));
    const drivers = positives.slice(0, 2).join(" and ") || "your strongest signals";
    const worst = items[items.length - 1];
    if (data.model_updates >= 6 && worst && worst.weight < 0) {
      const worstLbl = FEATURE_LABEL[worst.name] || titleCase(worst.name);
      const punch = worst.name === "tiktok_velocity"
        ? " That’s the opposite of the old rule-of-thumb that trusted social hype." : "";
      $("weightsNote").innerHTML =
        `After ${data.model_updates} results, the system has figured out that <b>${drivers}</b> are what actually pay off — and that <b>${worstLbl}</b> usually doesn’t.${punch}`;
    } else {
      $("weightsNote").innerHTML =
        `These start even and shift as results come in. Record a few outcomes on the plan and watch what the system decides actually matters.`;
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
      <div class="cfgrow"><span>Categories tracked</span><b>${c.categories}</b></div>
      <div class="cfgrow"><span>Website analysed</span><b>${c.site_source}</b></div>
      <div class="cfgrow"><span>Data</span><b>${s.data_mode === "real" ? "live" : "demo"}</b></div>
      <p class="cfg__note">This is a reusable platform — point it at a new client by setting
        <code>CLIENT_NAME</code>, <code>CLIENT_INDUSTRY</code>, <code>CLIENT_CATEGORIES</code> and
        <code>SITE_URL</code>. No code changes.</p>` : "";
  });
}

/* ---- value-over-time chart (the system's captured value, week by week) -- */
function proofSVG(d) {
  const W = 380, H = 188, pad = { l: 30, r: 12, t: 12, b: 24 };
  const n = d.weeks.length;
  const maxY = Math.max(...d.loop) * 1.05;
  const X = (i) => pad.l + (i / (n - 1)) * (W - pad.l - pad.r);
  const Y = (v) => H - pad.b - (v / maxY) * (H - pad.t - pad.b);
  const path = (arr) => arr.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");
  const area = `${path(d.loop)} L${X(n - 1).toFixed(1)},${Y(0).toFixed(1)} L${X(0).toFixed(1)},${Y(0).toFixed(1)} Z`;
  const yTicks = [0, maxY].map(
    (v) => `<text x="${pad.l - 6}" y="${(Y(v) + 3).toFixed(1)}" text-anchor="end"
              font-family="IBM Plex Mono" font-size="9" fill="#9AA1AC">${Math.round(v)}</text>`).join("");
  const xLabels = [0, Math.floor((n - 1) / 2), n - 1].map(
    (i) => `<text x="${X(i).toFixed(1)}" y="${H - 8}" text-anchor="middle"
              font-family="IBM Plex Mono" font-size="9" fill="#9AA1AC">wk ${d.weeks[i]}</text>`).join("");
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" role="img"
              aria-label="Value the system captures, growing week over week">
    <line x1="${pad.l}" y1="${H - pad.b}" x2="${W - pad.r}" y2="${H - pad.b}" stroke="#E6E8EC"/>
    <line x1="${pad.l}" y1="${pad.t}" x2="${pad.l}" y2="${H - pad.b}" stroke="#E6E8EC"/>
    ${yTicks}${xLabels}
    <path d="${area}" fill="rgba(15,118,110,.10)"/>
    <path d="${path(d.loop)}" fill="none" stroke="#0F766E" stroke-width="2.4"/>
  </svg>`;
}

/* ---- "what each upgrade adds" (hand-built bars, no chart lib) ----------- */
function renderAblation(rows) {
  if (!rows || !rows.length) return;
  const friendly = {
    P0: "Base scoring",
    P1: "+ Factor in effort",
    P2: "+ Avoid overlap",
    P3: "+ Learn from results",
    P4: "+ Explore new ideas",
  };
  const maxMean = Math.max(...rows.map((r) => r.mean));
  $("ablation").innerHTML = rows.map((r) => {
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
  }).join("");
  $("ablationNote").innerHTML =
    `Each part of the engine adds value on top of the base, tested across 30 simulated markets. The biggest gains come from <b>factoring in effort</b> and <b>learning from results</b> — which also keep wasted work low, at about one dead-end per run.`;
}

function loadProof() {
  const sim = api("/api/simulate").then((d) => {
    $("proof").innerHTML = proofSVG(d);
    $("proofNote").innerHTML =
      `A 20-week validation run: the system's recommendations captured steadily rising value as it
       learned, while keeping its picks focused — only <b>${d.decoys_loop} low-value ideas</b> across
       the whole run.`;
  }).catch(() => {});

  const rob = api("/api/robustness").then((r) => {
    if (!r || !r.robustness) return;
    const b = r.robustness;
    $("robustStat").innerHTML =
      `<div class="robust__big">${b.n} <span>markets validated</span></div>
       <div class="robust__cap">Stress-tested across <b>${b.n} simulated markets</b>: the system
        consistently prioritised the genuinely high-value topics and kept dead-end picks low, at about
        <b>${Math.round(b.decoys_loop_mean)} per run</b>.</div>`;
    renderAblation(r.ablation);
  }).catch(() => {});

  return Promise.all([sim, rob]);
}

/* ---- Competitors: new pages rivals are publishing ---------------------- */
function timeAgo(ts) {
  if (!ts) return "not yet";
  const s = Date.now() / 1000 - ts;
  if (s < 3600) return Math.max(1, Math.round(s / 60)) + "m ago";
  if (s < 86400) return Math.round(s / 3600) + "h ago";
  return Math.round(s / 86400) + "d ago";
}

function compCard(c) {
  if (c.ok === false) {
    return `<div class="comp comp--blocked">
      <div class="comp__top">
        <div class="comp__name">${c.name}</div>
        <span class="comp__badge comp__badge--blk">bot-protected</span>
      </div>
      <p class="comp__note">This retailer blocks automated crawlers (enterprise bot-protection).
        Their new pages will come through the <b>Ahrefs</b> integration.</p>
    </div>`;
  }
  const pages = c.new_pages && c.new_pages.length
    ? `<ul class="comp__pages">${c.new_pages.map((p) =>
        `<li><a href="${p.url}" target="_blank" rel="noopener">${p.title || p.url}</a></li>`).join("")}</ul>`
    : `<p class="comp__note">Baseline captured — new pages this competitor publishes will appear
        here after the next weekly crawl.</p>`;
  return `<div class="comp">
    <div class="comp__top">
      <div class="comp__name">${c.name}</div>
      <span class="comp__badge ${c.new_count ? "comp__badge--new" : ""}">${
        c.new_count ? c.new_count + " new" : "tracked"}</span>
    </div>
    <div class="comp__meta">${(c.total || 0).toLocaleString()} pages tracked · crawled ${timeAgo(c.last_crawled)}${
      c.note ? ` · <span class="comp__src">${c.note}</span>` : ""}</div>
    ${pages}
  </div>`;
}

function loadCompetitors() {
  const host = $("competitors");
  if (!host.children.length) host.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div>';
  return api("/api/competitors").then((d) => {
    const rows = (d && d.competitors) || [];
    host.innerHTML = rows.length ? rows.map(compCard).join("")
      : `<p class="lede">No competitors configured.</p>`;
  }).catch(() => { host.innerHTML = `<p class="lede">Could not load competitor data.</p>`; });
}

/* ---- AI Visibility: share of voice in AI answers ----------------------- */
function loadAiVisibility() {
  const host = $("aivBars");
  if (!host.children.length) host.innerHTML = '<div class="skeleton"></div>';
  return api("/api/ai-visibility").then((d) => {
    if (!d.enabled) {
      host.innerHTML = `<p class="lede">AI visibility turns on with the Ahrefs key —
        set <b>AHREFS_API_KEY</b> to see your share of voice in ChatGPT & co.</p>`;
      return;
    }
    const brands = d.brands || [];
    if (!brands.length) { host.innerHTML = `<p class="lede">No AI visibility data available yet.</p>`; return; }
    const max = Math.max(...brands.map((b) => b.sov), 0.0001);
    const src = (d.sources || ["chatgpt"]).join(", ").toUpperCase();
    host.innerHTML =
      `<div class="aiv__src">Source: <b>${src}</b> · Australia · how often each brand appears in AI answers</div>` +
      brands.map((b) => {
        const mine = b.brand === d.client;
        return `<div class="aiv ${mine ? "aiv--me" : ""}">
          <div class="aiv__name">${b.brand}${mine ? ' <span class="aiv__you">you</span>' : ""}</div>
          <div class="aiv__track"><div class="aiv__fill" style="width:${Math.round(b.sov / max * 100)}%"></div></div>
          <div class="aiv__val">${Math.round(b.sov * 100)}%</div>
        </div>`;
      }).join("");
  }).catch(() => { host.innerHTML = `<p class="lede">Could not load AI visibility.</p>`; });
}

/* ---- view routing ------------------------------------------------------- */
const VIEW_META = {
  dashboard: ["Overview", "Dashboard"],
  plan: ["Your plan", "What to do this week"],
  signals: ["Live market signals", "Market signals"],
  competitors: ["New pages rivals are publishing", "Competitors"],
  aivis: ["Your presence in AI answers", "AI Visibility"],
  proof: ["Validated across 30 markets", "How it works"],
  learning: ["What the system figured out", "What it's learned"],
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
  if (name === "competitors") loadCompetitors();
  if (name === "aivis") loadAiVisibility();
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
  toast("Reset — the system starts learning from scratch");
  await Promise.all([loadBrief(), loadWeights(), loadStatus(), loadDashboard()]);
});
$("compRefresh").addEventListener("click", async () => {
  const b = $("compRefresh");
  b.disabled = true; b.textContent = "Crawling…";
  try { await api("/api/competitors/refresh", { method: "POST" }); } catch (e) {}
  toast("Crawling competitors in the background — this refreshes in a moment.");
  setTimeout(() => { loadCompetitors(); b.disabled = false; b.textContent = "Refresh now"; }, 6000);
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
    asstAdd("bot", "Hi — ask me anything about your market. Try: “what should we do first?”, " +
      "“what's trending?”, “where are the gaps on our site?”, or “does this actually work?”");
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
loadCompetitors();
loadAiVisibility();
wireGoto();
showView("dashboard");
