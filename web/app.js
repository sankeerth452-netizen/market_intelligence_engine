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
const confidenceOf = (conf) =>
  conf >= 0.62 ? ["High", "is-high"] : conf >= 0.42 ? ["Medium", "is-med"] : ["Low", "is-low"];
const actionVerb = (a, leads) =>
  leads ? ["Defend your", " lead"] :
  (a || "").toLowerCase().startsWith("create") ? ["Create a page for", ""] : ["Strengthen your", " page"];
const whyLine = (c) => {
  const ev = (c.evidence || []).map((e) => CHIP_LABEL[e] || e);
  return ev.length ? ev.join(" · ") : "Flagged by this week's market signals.";
};

/* ---- greeting + live date/time (client-friendly header) ---------------- */
const greetWord = (h) => (h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening");
function updateGreeting() {
  const now = new Date();
  const date = now.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  const time = now.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  const g = $("greeting");
  if (g) g.innerHTML = `<span class="greeting__hi">${greetWord(now.getHours())}</span>` +
    `<span class="greeting__dt">${date} · ${time}</span>`;
}
function weekRange() {
  const now = new Date();
  const day = (now.getDay() + 6) % 7;                 // Monday = 0
  const mon = new Date(now); mon.setDate(now.getDate() - day);
  const sun = new Date(mon); sun.setDate(mon.getDate() + 6);
  const f = (d) => d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
  return `${f(mon)} – ${f(sun)}`;
}
const shortToday = () => new Date().toLocaleDateString(undefined, { day: "numeric", month: "short" });

/* Real mode has no synthetic "week N"; show the actual current week + hide the
   demo stepper. Synthetic/demo keeps the stepper. */
function configureWeek() {
  const eb = document.querySelector(".week .eyebrow");
  const down = $("weekDown"), up = $("weekUp");
  if (state.real) {
    if (eb) eb.textContent = "This week";
    if (down) down.style.display = "none";
    if (up) up.style.display = "none";
  } else {
    if (eb) eb.textContent = "Planning week";
    if (down) down.style.display = "";
    if (up) up.style.display = "";
  }
  setWeekLabel();
}
function setWeekLabel() {
  const el = $("weekVal");
  if (!el) return;
  if (state.real) { el.textContent = weekRange(); el.classList.add("week__val--date"); }
  else { el.textContent = pad2(state.week); el.classList.remove("week__val--date"); }
}

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

/* ---- the signature element: how-sure-we-are meter (dot + band) ----------
   dot = opportunity strength; band = uncertainty, narrow when confidence is high. */
function convictionSVG(strength, confidence) {
  const half = (1 - (confidence == null ? 0.5 : confidence)) * 0.42;
  const lo = Math.max(0, strength - half), hi = Math.min(1, strength + half);
  const value = strength;
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
function setConviction(el, strength, confidence, roi) {
  const X = (v) => 10 + v * 280;
  const half = (1 - (confidence == null ? 0.5 : confidence)) * 0.42;
  const lo = Math.max(0, strength - half), hi = Math.min(1, strength + half);
  const band = el.querySelector(".cv__band");
  const pt = el.querySelector(".cv__pt");
  if (band) {
    band.setAttribute("x", X(lo).toFixed(1));
    band.setAttribute("width", (X(hi) - X(lo)).toFixed(1));
  }
  if (pt) pt.setAttribute("cx", X(strength).toFixed(1));
  const roiEl = el.querySelector(".conv__roi");
  if (roiEl) { const [p, cls] = priorityOf(roi); roiEl.textContent = p; roiEl.className = "conv__roi prio " + cls; }
  const readout = el.querySelector(".conv__readout");
  if (readout) { const [cf, cc] = confidenceOf(confidence); readout.innerHTML = `Confidence: <b class="${cc}">${cf}</b>`; }
}

/* ---- opportunity cards --------------------------------------------------- */
let _recs = {};
function cardEl(c) {
  _recs[c.id] = c;
  const el = document.createElement("article");
  el.className = "card";
  el.dataset.id = c.id;
  el.style.animationDelay = (c.rank - 1) * 0.06 + "s";

  const [prio, prioCls] = prioOf(c);
  const [conf, confCls] = confidenceOf(c.confidence);
  const [verb, suffix] = actionVerb(c.action, c.leads);
  const test = (c.confidence != null && c.confidence < 0.5)
    ? `<span class="tag tag--test" title="Signals are mixed here — worth a quick test to find out">Worth a test</span>` : "";
  const news = (c.headlines && c.headlines[0])
    ? `<div class="card__news">📰 In the news: “${c.headlines[0]}”</div>` : "";

  // A 'create page' rec names the SPECIFIC missing page (a real gap), not the
  // category page JB already has.
  const specific = c.target && !c.leads;
  const title = specific
    ? `Create a ${c.target.type.toLowerCase()}: “${c.target.keyword}”`
    : `${verb} ${c.topic}${suffix}`;
  const catTag = specific ? ` <span class="card__cat">in ${c.topic}</span>` : "";
  const targetWhy = specific
    ? `<b>${c.target.competitor} ranks #${c.target.position} for this (${Number(c.target.volume).toLocaleString("en-US")}/mo) — you don't.</b> `
    : "";

  el.innerHTML = `
    <div class="card__rank">${pad2(c.rank)}</div>
    <div class="card__main">
      <h3 class="card__topic">${title}${catTag}</h3>
      <p class="card__why">${targetWhy}${whyLine(c)}</p>
      ${news}
      <div class="card__meta">
        <span class="tag tag--effort-${c.effort}">${EFFORT_LABEL[c.effort] || c.effort} effort</span>
        ${test}
        <button class="planbtn" type="button">✦ Get the AI action plan</button>
        <button class="markdone" type="button" title="Mark this recommendation as shipped so we can track its real results">✓ We built this</button>
        <button class="evbtn" type="button">Full evidence &amp; SEO brief →</button>
      </div>
      <div class="plan" hidden></div>
    </div>
    <div class="card__conv">
      <div class="conv__row">
        <span class="conv__label">Priority</span>
        <span class="conv__roi prio ${prioCls}">${prio}</span>
      </div>
      ${convictionSVG(c.strength != null ? c.strength : c.value, c.confidence)}
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
  el.querySelector(".evbtn").addEventListener("click", () => showRecDetail(c.id));
  const doneBtn = el.querySelector(".markdone");
  if (doneBtn) doneBtn.addEventListener("click", () => markDone(c, doneBtn));
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
                             headlines: c.headlines || [], signals: c.signals || {},
                             target: c.target || {} }),
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
    const data = await api(`/api/brief?week=${state.week}&k=20`);
    const host = $("cards");
    const shown = [...host.querySelectorAll(".card")];
    const shownIds = shown.map((e) => Number(e.dataset.id)).sort((a, b) => a - b);
    const newIds = data.map((c) => c.id).sort((a, b) => a - b);
    const same = shownIds.length === newIds.length && shownIds.every((v, i) => v === newIds[i]);
    if (!same) { host.innerHTML = ""; data.forEach((c) => host.appendChild(cardEl(c))); return; }
    data.forEach((c) => {
      const el = shown.find((e) => Number(e.dataset.id) === c.id);
      if (!el) return;
      setConviction(el, c.strength != null ? c.strength : c.value, c.confidence, c.roi);
      el.classList.add("is-learning");
      setTimeout(() => el.classList.remove("is-learning"), 800);
    });
  } catch (e) { /* keep current cards if refresh fails */ }
}

/* ---- What to do this week (full cards) ---------------------------------- */
function loadBrief() {
  const host = $("cards");
  host.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div>';
  setWeekLabel();
  return api(`/api/brief?week=${state.week}&k=20`).then((data) => {
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
function kpiIcon(name) {
  const p = {
    target: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/>',
    search: '<circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    trend: '<polyline points="3 17 9 11 13 15 21 7"/><polyline points="15 7 21 7 21 13"/>',
    spark: '<path d="M12 3l1.6 5.4L19 10l-5.4 1.6L12 17l-1.6-5.4L5 10l5.4-1.6z"/>',
    grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  }[name] || "";
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;
}

async function loadDashboard() {
  const [status, brief, sig, gaps, aiv] = await Promise.all([
    api("/api/status").catch(() => ({})),
    api(`/api/brief?week=${state.week}&k=20`).catch(() => []),
    api("/api/signals").catch(() => ({ items: [] })),
    api("/api/content-gaps").catch(() => ({})),
    api("/api/ai-visibility").catch(() => ({})),
  ]);
  const top = brief[0];
  const cats = (status.client && status.client.categories) || "—";
  const compact = (n) => n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? Math.round(n / 1e3) + "K" : String(n);
  const topVol = (sig.items || []).filter((i) => i.volume != null).sort((a, b) => b.volume - a.volume)[0];

  const topSpec = top && top.target && !top.leads;
  const k1 = { icon: "target", label: "Do this first", accent: "teal",
    big: top ? (topSpec ? top.target.keyword : top.topic) : "—",
    sub: top ? `${prioOf(top)[0]} priority · ${topSpec ? top.target.type.toLowerCase()
          : (top.leads ? "defend your lead" : (top.action || "").toLowerCase())}` : "" };

  const gapCount = gaps.kept || 0, gapCats = Object.keys(gaps.by_category || {}).length;
  const k2 = gapCount
    ? { icon: "search", label: "Content gaps found", accent: "amber",
        big: String(gapCount), sub: `rivals rank, you don't · ${gapCats} categories` }
    : { icon: "grid", label: "Categories tracked", accent: "ink", big: String(cats), sub: "monitored every week" };

  const k3 = topVol
    ? { icon: "trend", label: "Biggest search demand", accent: "teal",
        big: topVol.topic, sub: compact(topVol.volume) + " searches/mo" }
    : { icon: "trend", label: "This week", accent: "teal", big: weekRange(), sub: "your market snapshot" };

  let k4;
  const brands = (aiv && aiv.enabled) ? [...(aiv.brands || [])].sort((a, b) => b.sov - a.sov) : [];
  if (brands.length) {
    const me = brands.find((b) => b.brand === aiv.client) || brands[0];
    k4 = { icon: "spark", label: "AI share of voice", accent: "teal",
           big: Math.round(me.sov * 100) + "%", sub: `#${brands.indexOf(me) + 1} of ${brands.length} in AI answers` };
  } else {
    k4 = { icon: "grid", label: "Categories tracked", accent: "ink", big: String(cats), sub: "monitored every week" };
  }

  $("kpis").innerHTML = [k1, k2, k3, k4].map((k) => `
    <div class="kpi kpi--${k.accent}">
      <div class="kpi__top"><span class="kpi__ico">${kpiIcon(k.icon)}</span><span class="kpi__label">${k.label}</span></div>
      <div class="kpi__big">${k.big}</div>
      <div class="kpi__sub">${k.sub}</div>
    </div>`).join("");

  const totalVol = (sig.items || []).reduce((a, i) => a + (i.volume || 0), 0);
  if (totalVol > 0) {
    $("heroStat").textContent = compact(totalVol);
    $("heroCap").innerHTML =
      `monthly searches across your categories — the system ranks exactly where to focus, and refines as results come in.`;
  } else {
    $("heroStat").textContent = String(cats);
    $("heroCap").innerHTML =
      `categories analysed live — demand, gaps, competitors and AI visibility, refreshed weekly.`;
  }
  $("heroSide").innerHTML =
    `<div class="herometric"><b>${cats}</b><span>categories watched</span></div>
     <div class="herometric"><b>${shortToday()}</b><span>updated</span></div>`;

  $("dashPlan").innerHTML = brief.length ? brief.map((c) => {
    const [p, pc] = prioOf(c);
    const spec = c.target && !c.leads;
    const topic = spec ? c.target.keyword : c.topic;
    const actionLabel = spec ? c.target.type : (c.leads ? "Defend your lead" : c.action);
    return `<button class="dpitem" data-goto="plan">
      <div class="dpitem__rank">${pad2(c.rank)}</div>
      <div class="dpitem__main">
        <div class="dpitem__topic">${topic}</div>
        <div class="dpitem__meta">
          <span class="tag tag--action">${actionLabel}</span>
          <span class="tag tag--effort-${c.effort}">${EFFORT_LABEL[c.effort] || c.effort} effort</span>
        </div>
      </div>
      <div class="dpitem__roi prio ${pc}">${p}<span>priority</span></div>
    </button>`;
  }).join("") : `<p class="lede">No clear opportunities this week.</p>`;
  wireGoto();
}

/* ---- Market signals view ------------------------------------------------ */
function sparkline(series, w = 118, h = 26) {
  if (!series || series.length < 2) return "";
  const max = Math.max(...series), min = Math.min(...series), rng = max - min || 1;
  const pts = series.map((v, i) =>
    `${(i / (series.length - 1) * w).toFixed(1)},${(h - 2 - (v - min) / rng * (h - 4)).toFixed(1)}`).join(" ");
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">` +
    `<polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>`;
}

function sigBar(v, label) {
  return `<div class="sig"><span class="sig__lbl">${label}</span>` +
    `<div class="sig__track"><div class="sig__fill" style="width:${Math.round(v * 100)}%"></div></div>` +
    `<span class="sig__val">${Math.round(v * 100)}</span></div>`;
}
function sigrowHTML(it, demand) {
  const s = it.signals;
  const [p, pc] = prioOf(it);
  const heads = (it.headlines || []).slice(0, 2).map((h) => `<div class="sig__news">📰 ${h}</div>`).join("");
  const vol = it.volume != null
    ? `<div class="sigrow__vol">🔍 ${it.volume.toLocaleString("en-US")} searches/mo</div>` : "";
  const f = demand && demand[String(it.category || it.topic).toLowerCase()];
  let demandLine = "";
  if (f) {
    const cls = f.trend_pct > 4 ? "up" : f.trend_pct < -4 ? "down" : "";
    const arrow = cls === "up" ? "↑" : cls === "down" ? "↓" : "→";
    const peak = f.seasonal ? ` · peaks <b>${f.peak_month}</b> (+${f.peak_lift}%)` : "";
    demandLine = `<div class="sig__demand"><span class="spark--wrap ${cls}">${sparkline(f.series)}</span>` +
      `<span class="sig__trend ${cls}">${arrow} ${f.trend_pct > 0 ? "+" : ""}${f.trend_pct}% demand` +
      `<span class="sig__trend-sub"> · 18-mo${peak}</span></span></div>`;
  }
  return `<div class="sigrow sigrow--click" data-cat="${it.category || it.topic}">
    <div class="sigrow__top">
      <div><div class="sigrow__name">${it.topic}</div>${vol}</div>
      <div class="sigrow__roi prio ${pc}">${p}<span>priority</span></div>
    </div>
    <div class="sigrow__bars">
      ${sigBar(s.trend_surprise, "Search demand")}
      ${sigBar(s.news_relevance, "In the news")}
      ${sigBar(s.semantic_gap, "Gap on your site")}
    </div>
    ${demandLine}${heads}
    <div class="sigrow__more">View full detail and sources →</div>
  </div>`;
}
let _sig = { items: [], demand: {}, gaps: {} };
function loadSignals() {
  const host = $("signals");
  if (host.dataset.loaded) return Promise.resolve();
  host.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div>';
  return api("/api/signals").then((d) => {
    const items = d.items || [];
    if (!items.length) { host.innerHTML = '<p class="lede">No signals loaded yet.</p>'; return; }
    _sig.items = items;
    const render = (demand) => { host.innerHTML = items.map((it) => sigrowHTML(it, demand)).join(""); };
    render(null);                              // render signals immediately …
    host.dataset.loaded = "1";
    host.onclick = (e) => {                     // click a category -> full detail
      const row = e.target.closest(".sigrow");
      if (row && row.dataset.cat) showCategoryDetail(row.dataset.cat);
    };
    api("/api/demand").then((dem) => {         // … then enhance with demand history when it arrives
      const demand = {};
      (dem.categories || []).forEach((c) => { demand[String(c.category).toLowerCase()] = c; });
      _sig.demand = demand;
      if (Object.keys(demand).length) render(demand);
    }).catch(() => {});
    api("/api/content-gaps").then((g) => {     // … and the real content gaps per category
      const by = {};
      (g.opportunities || []).forEach((o) => { (by[o.category] = by[o.category] || []).push(o); });
      _sig.gaps = by;
    }).catch(() => {});
  }).catch(() => { host.innerHTML = '<p class="lede">Could not load market signals.</p>'; });
}

function showCategoryDetail(cat) {
  state.view = "category";
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("view--active", v.id === "view-category"));
  document.querySelectorAll(".nav__item").forEach((n) => n.classList.toggle("is-active", n.dataset.view === "signals"));
  $("viewEyebrow").textContent = "Market signal detail";
  $("viewTitle").textContent = cat;
  window.scrollTo(0, 0);
  renderCategoryDetail(cat);
}

function cdSignal(label, score, real, source) {
  const p = Math.round((score || 0) * 100);
  return `<div class="cdsig__row">
      <div class="cdsig__head"><span class="cdsig__label">${label}</span><span class="cdsig__score">${p}</span></div>
      <div class="cdbar"><div class="cdbar__fill" style="width:${p}%"></div></div>
      <div class="cdsig__real">${real} <span class="cdsig__src">· source: ${source}</span></div>
    </div>`;
}

function renderCategoryDetail(cat) {
  const host = $("category");
  const it = _sig.items.find((i) => String(i.category || i.topic) === cat) || {};
  const s = it.signals || {};
  const dem = _sig.demand[String(cat).toLowerCase()];
  const gaps = _sig.gaps[cat] || [];
  const heads = it.headlines || [];
  const back = `<button class="cdback" onclick="showView('signals')">← Back to all signals</button>`;

  const sig = `<div class="panel">
      <div class="panel__head"><div class="eyebrow">What we track for ${cat}</div>
        <h2 class="panel__title">The signals behind the score</h2></div>
      ${cdSignal("Search demand", s.trend_surprise, it.volume != null ? `≈ ${it.volume.toLocaleString("en-US")} searches/mo across all ${cat.toLowerCase()} keywords` : "search interest", "Ahrefs")}
      ${cdSignal("In the news", s.news_relevance, `${heads.length} recent headline${heads.length !== 1 ? "s" : ""} we crawled`, "Google News RSS")}
      ${cdSignal("Gap on your site", s.semantic_gap, `${gaps.length} keyword${gaps.length !== 1 ? "s" : ""} rivals rank for that you don't`, "Ahrefs content-gap")}
      <p class="panel__note">The bars are <b>0–100 scores</b>, relative to your other categories — a way to
        compare where to focus, not raw counts. The <b>real figures</b> are shown beside each.</p></div>`;

  let trend = "";
  if (dem) {
    const cls = dem.trend_pct > 4 ? "up" : dem.trend_pct < -4 ? "down" : "";
    const peak = dem.seasonal ? `typically peaks in <b>${dem.peak_month}</b> (+${dem.peak_lift}%)` : "no strong seasonal pattern";
    trend = `<div class="panel">
        <div class="panel__head"><div class="eyebrow">18-month demand · source: Ahrefs volume history</div>
          <h2 class="panel__title">How demand has trended</h2></div>
        <div class="cdtrend"><span class="spark--wrap ${cls}">${sparkline(dem.series, 280, 64)}</span>
          <div><div class="cdtrend__pct ${cls}">${dem.trend_pct > 0 ? "+" : ""}${dem.trend_pct}% over 18 months</div>
            <div class="cdtrend__sub">${peak}</div></div></div></div>`;
  }

  const gapType = (t) => /Comparison/.test(t) ? "cmp" : /Buying/.test(t) ? "guide" : /Guide|FAQ|Review/.test(t) ? "info" : "land";
  const gapList = gaps.length ? gaps.slice(0, 8).map((o) => {
    const comp = o.competitors[0];
    return `<div class="cdgap"><span class="gaptype gaptype--${gapType(o.type)}">${o.type}</span>
        <div class="cdgap__body"><div class="cdgap__kw">${o.keyword}</div>
          <div class="cdgap__meta">${o.volume.toLocaleString("en-US")}/mo · ${comp.name} ranks #${comp.position}, you don't</div></div></div>`;
  }).join("") : `<p class="panel__note">No open content gaps here — you already cover this category well.</p>`;
  const gapPanel = `<div class="panel">
      <div class="panel__head"><div class="eyebrow">From the Ahrefs content-gap export</div>
        <h2 class="panel__title">What rivals cover that you don't</h2></div>${gapList}</div>`;

  const newsPanel = heads.length ? `<div class="panel">
      <div class="panel__head"><div class="eyebrow">Google News · this week</div>
        <h2 class="panel__title">In the news</h2></div>
      ${heads.map((h) => `<div class="sig__news">📰 ${h}</div>`).join("")}</div>` : "";

  host.innerHTML = back + sig + trend + gapPanel + newsPanel;
}

/* ---- plan recommendation: full evidence + SEO brief (for an SEO manager) - */
async function showRecDetail(id) {
  const c = _recs[id];
  if (!c) return;
  state.view = "recdetail";
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("view--active", v.id === "view-recdetail"));
  document.querySelectorAll(".nav__item").forEach((n) => n.classList.toggle("is-active", n.dataset.view === "plan"));
  $("viewEyebrow").textContent = "Full evidence · SEO brief";
  $("viewTitle").textContent = c.target ? c.target.keyword : c.topic;
  window.scrollTo(0, 0);
  if (!Object.keys(_sig.demand || {}).length) {          // make sure the trend is available
    try {
      const dem = await api("/api/demand");
      _sig.demand = {};
      (dem.categories || []).forEach((x) => { _sig.demand[String(x.category).toLowerCase()] = x; });
    } catch (e) { /* trend just won't show */ }
  }
  renderRecDetail(c);
}

function _rdRow(k, v) { return `<tr><td class="rd__k">${k}</td><td class="rd__v">${v}</td></tr>`; }

function renderRecDetail(c) {
  const host = $("recdetail");
  const t = c.target, s = c.signals || {};
  const [prio] = prioOf(c);
  const dem = (_sig.demand || {})[String(c.category || "").toLowerCase()];
  const back = `<button class="cdback" onclick="showView('plan')">← Back to the plan</button>`;

  const rows = [];
  if (t) {
    rows.push(_rdRow("Target keyword", `“${t.keyword}”`));
    rows.push(_rdRow("Monthly search volume", `${Number(t.volume).toLocaleString("en-US")} / mo`));
    if (t.intent && t.intent.length) rows.push(_rdRow("Search intent", t.intent.join(", ")));
    if (t.kd != null) rows.push(_rdRow("Keyword difficulty (KD)", `${t.kd} / 100`));
    rows.push(_rdRow("Your organic position", "Not ranking — no page for this yet"));
    rows.push(_rdRow("Competitors ranking", (t.competitors || []).map((x) => `${x.name} #${x.position}`).join(" · ") || "—"));
    rows.push(_rdRow("Recommended page type", t.type));
  } else {
    rows.push(_rdRow("Category", c.topic));
    rows.push(_rdRow("Recommended action", c.action));
    if (c.leads) rows.push(_rdRow("Your position", "You already lead this category"));
  }
  const evTable = `<table class="rd__tbl">${rows.join("")}</table>`;

  const why = t
    ? `Ranked by <b>opportunity value</b> = search volume × buyer intent × the fact a competitor already ranks and you don't.
       This is <b>${prio} priority</b> because “${t.keyword}” draws <b>${Number(t.volume).toLocaleString("en-US")}/mo</b>${t.volume >= 5000 ? " (≥ 5,000/mo)" : ""},
       ${t.competitor} ${t.position ? "ranks #" + t.position : "ranks"} for it, and JB Hi-Fi has no page to compete.`
    : (c.leads
        ? "You already rank well across this category, so this is a <b>defend</b> — hold the lead, don't rebuild what you have."
        : "Surfaced by this week's live market signals.");

  const bar = (label, v, sub) => {
    const p = Math.round((v || 0) * 100);
    return `<div class="rdsig"><div class="rdsig__top"><span>${label}</span><b>${p}</b></div>
        <div class="cdbar"><div class="cdbar__fill" style="width:${p}%"></div></div>
        <div class="rdsig__sub">${sub}</div></div>`;
  };
  const sigPanel = `<div class="panel"><div class="panel__head"><div class="eyebrow">Signal profile</div>
      <h2 class="panel__title">The evidence behind the score</h2></div>
      ${bar("Search demand", s.trend_surprise, "unmet search interest vs your other categories")}
      ${bar("Content gap", s.semantic_gap, "how under-covered this is on your own site")}
      ${bar("News momentum", s.news_relevance, "current press / industry attention")}
      ${bar("Cross-source agreement", s.cross_source_agreement, "whether independent live signals corroborate")}
      <p class="panel__note">Scores are <b>0–100</b>, relative to your other categories — signal strength, not raw counts.
        Model confidence: <b>${confidenceOf(c.confidence)[0]}</b>.</p></div>`;

  let trend = "";
  if (dem) {
    const cls = dem.trend_pct > 4 ? "up" : dem.trend_pct < -4 ? "down" : "";
    const peak = dem.seasonal ? `typically peaks in <b>${dem.peak_month}</b> (+${dem.peak_lift}%)` : "no strong seasonal pattern";
    trend = `<div class="panel"><div class="panel__head"><div class="eyebrow">18-month demand · Ahrefs volume history</div>
        <h2 class="panel__title">Demand trend</h2></div>
        <div class="cdtrend"><span class="spark--wrap ${cls}">${sparkline(dem.series, 280, 64)}</span>
          <div><div class="cdtrend__pct ${cls}">${dem.trend_pct > 0 ? "+" : ""}${dem.trend_pct}% over 18 months</div>
            <div class="cdtrend__sub">${peak}</div></div></div></div>`;
  }

  const news = (c.headlines || []).length ? `<div class="panel"><div class="panel__head">
      <div class="eyebrow">Google News · this week</div><h2 class="panel__title">In the news</h2></div>
      ${c.headlines.map((h) => `<div class="sig__news">📰 ${h}</div>`).join("")}</div>` : "";

  const oppPanel = `<div class="panel"><div class="panel__head"><div class="eyebrow">The opportunity</div>
      <h2 class="panel__title">Why this is a ${prio.toLowerCase()} priority</h2></div>
      ${evTable}<p class="rd__why">${why}</p></div>`;

  host.innerHTML = back + oppPanel + sigPanel + trend + news +
    `<div class="panel" id="rdBrief"><div class="panel__head"><div class="eyebrow">SEO action brief</div>
        <h2 class="panel__title">What to build</h2></div><div class="plan__loading">Writing the SEO brief…</div></div>`;

  api("/api/playbook", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic: c.topic, action: c.action, effort: c.effort,
                             headlines: c.headlines || [], signals: c.signals || {}, target: c.target || {} }) })
    .then((p) => {
      const el = document.querySelector("#rdBrief");
      if (el) el.innerHTML = `<div class="panel__head"><div class="eyebrow">SEO action brief${p.source === "ai" ? " · AI-written" : ""}</div>
          <h2 class="panel__title">What to build</h2></div>` + planHTML(p);
    }).catch(() => {});
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
        `These start from proven marketing priors — rising demand and content gaps matter most — and adapt to what actually works for you as results are recorded.`;
    }
  });
}

/* ---- status: gauges + rail + client chip + settings -------------------- */
function loadStatus() {
  return api("/api/status").then((s) => {
    state.real = s.data_mode === "real";
    configureWeek();
    $("gRecs").textContent = s.recommendations;
    $("gOuts").textContent = s.outcomes;
    $("gUpd").textContent = s.model_updates;
    $("gAvg").textContent = s.avg_reward == null ? "—" : s.avg_reward.toFixed(2);

    const c = s.client || {};
    $("cfg").innerHTML = c.name ? `
      <div class="cfgrow"><span>Client</span><b>${c.name}</b></div>
      <div class="cfgrow"><span>Industry</span><b>${titleCase(c.industry)}</b></div>
      <div class="cfgrow"><span>Categories tracked</span><b>${c.categories}</b></div>
      <div class="cfgrow"><span>Website analysed</span><b>${c.site_source}</b></div>
      <p class="cfg__note">These categories are monitored automatically every week across live search
        demand, news, on-site content gaps, competitor activity and AI visibility.</p>` : "";
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
    `Each part of the engine adds value on top of the base, tested across 30 market scenarios. The biggest gains come from <b>factoring in effort</b> and <b>learning from results</b> — which also keep wasted work low, at about one dead-end per run.`;
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
       <div class="robust__cap">Stress-tested across <b>${b.n} market scenarios</b>: the system
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
    <div class="comp__meta">${(c.total || 0).toLocaleString("en-US")} pages tracked · crawled ${timeAgo(c.last_crawled)}${
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
function sovGauge(p) {
  const r = 54, c = 2 * Math.PI * r, on = Math.max(0, Math.min(1, p)) * c;
  return `<svg viewBox="0 0 140 140" class="sovg" role="img" aria-label="${Math.round(p * 100)} percent share of voice">
      <circle cx="70" cy="70" r="${r}" class="sovg__bg"/>
      <circle cx="70" cy="70" r="${r}" class="sovg__arc" stroke-dasharray="${on.toFixed(1)} ${(c - on).toFixed(1)}" transform="rotate(-90 70 70)"/>
      <text x="70" y="65" class="sovg__pct">${Math.round(p * 100)}%</text>
      <text x="70" y="87" class="sovg__lbl">share of voice</text>
    </svg>`;
}

function loadAiVisibility() {
  const host = $("aivBars");
  if (!host.children.length) host.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div>';
  return api("/api/ai-visibility").then((d) => {
    if (!d.enabled) {
      host.innerHTML = `<p class="lede">AI visibility turns on with the Ahrefs key —
        set <b>AHREFS_API_KEY</b> to see your share of voice in ChatGPT and other AI answers.</p>`;
      return;
    }
    const brands = (d.brands || []).slice().sort((a, b) => b.sov - a.sov);
    if (!brands.length) { host.innerHTML = `<p class="lede">No AI visibility data available yet.</p>`; return; }
    const client = d.client, pct = (x) => Math.round(x * 100);
    const max = Math.max(...brands.map((b) => b.sov), 0.0001);
    const me = brands.find((b) => b.brand === client) || brands[0];
    const myRank = brands.indexOf(me) + 1;
    const rivals = brands.filter((b) => b.brand !== client);
    const top = rivals[0];
    const src = (d.sources || ["chatgpt"]).map((s) => s.toUpperCase()).join(", ");
    const leadPts = top ? pct(me.sov) - pct(top.sov) : null;
    const leadX = (top && top.sov > 0) ? (me.sov / top.sov).toFixed(1) : null;
    const headroom = pct(1 - me.sov);

    const heroLine = (myRank === 1 && top)
      ? `<b>${client}</b> leads AI visibility — cited in <b>${pct(me.sov)}%</b> of AI shopping answers, about <b>${leadX}&times;</b> the nearest competitor.`
      : `<b>${client}</b> ranks #${myRank} of ${brands.length} — cited in <b>${pct(me.sov)}%</b> of AI shopping answers.`;
    const hero = `<div class="aivhero">${sovGauge(me.sov)}<div>
        <span class="aivhero__rankbadge">${myRank === 1 ? "Category leader" : "Rank #" + myRank + " of " + brands.length}</span>
        <div class="aivhero__title">${heroLine}</div>
        <p class="aivhero__sub">Share of voice is how often a brand gets named when AI assistants answer shopping
          questions in your categories — the new shelf space, sitting above the ten blue links.</p>
        <div class="aivhero__chips"><span class="aivchip">Source: ${src}</span><span class="aivchip">Australia</span><span class="aivchip">Refreshed weekly</span></div>
      </div></div>`;

    const rows = brands.map((b, i) => {
      const mine = b.brand === client, threat = !mine && b === top;
      const gap = mine ? "" : `<span class="lb__gap">−${pct(me.sov) - pct(b.sov)} pts vs you</span>`;
      return `<div class="lb ${mine ? "lb--me" : ""} ${threat ? "lb--threat" : ""}">
          <div class="lb__rank">${pad2(i + 1)}</div>
          <div class="lb__main">
            <div class="lb__top"><span class="lb__name">${b.brand}</span>${mine ? '<span class="aiv__you">you</span>' : ""}${gap}</div>
            <div class="lb__bar"><div class="lb__fill" style="width:${Math.round(b.sov / max * 100)}%"></div></div>
          </div>
          <div class="lb__val">${pct(b.sov)}%</div>
        </div>`;
    }).join("");
    const board = `<div class="lbpanel"><div class="eyebrow" style="margin-bottom:14px">Competitive leaderboard</div>${rows}</div>`;

    const card = (cls, lbl, big, sub) =>
      `<div class="aivcard ${cls}"><div class="aivcard__lbl">${lbl}</div><div class="aivcard__big">${big}</div><div class="aivcard__sub">${sub}</div></div>`;
    const cards = `<div class="aivcards">
        ${card("", "Your rank", "#" + myRank + " of " + brands.length, myRank === 1 ? "you own the top spot" : "room to climb")}
        ${top ? card("", "Lead over #2", "+" + leadPts + " pts", leadX + "&times; " + top.brand) : ""}
        ${card("aivcard--amber", "Answer headroom", headroom + "%", "of AI answers still don't name you")}
        ${top ? card("aivcard--amber", "Closest challenger", top.brand, pct(top.sov) + "% share of voice") : ""}
      </div>`;

    const method = `<div class="aivmethod"><b>How this is measured.</b> Real Ahrefs Brand Radar data — how often each brand
      is actually cited when ${src} answers shopping questions across your categories in Australia, refreshed weekly.
      Share of voice is an appearance rate (one brand can appear in many answers), so figures do not sum to 100%.</div>`;

    host.innerHTML = hero + cards + board + method;
  }).catch(() => { host.innerHTML = `<p class="lede">Could not load AI visibility.</p>`; });
}

/* ---- Content Gaps: competitor content JB is missing (Ahrefs export) ----- */
let _gapFilter = "all";
function loadContentGaps() {
  const host = $("gaps");
  if (!host.children.length) host.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div>';
  return api("/api/content-gaps").then((d) => {
    if (!d.available) {
      host.innerHTML = `<p class="lede">No content-gap data imported yet. Add the Ahrefs content-gap and
        top-pages exports and run <code>import_ahrefs.py</code> to populate this view.</p>`;
      return;
    }
    const opps = d.opportunities || [];
    if (!opps.length) { host.innerHTML = `<p class="lede">No relevant gaps found.</p>`; return; }
    const cats = d.by_category || {}, catList = Object.keys(cats);
    const compact = (n) => n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? Math.round(n / 1e3) + "K" : String(n);
    const topCat = catList[0];

    const card = (lbl, big, sub) => `<div class="aivcard"><div class="aivcard__lbl">${lbl}</div><div class="aivcard__big">${big}</div><div class="aivcard__sub">${sub}</div></div>`;
    const summary = `<div class="aivcards">
        ${card("Opportunities", opps.length, "competitor ranks, you don't")}
        ${card("Categories", catList.length, "with missing content")}
        ${card("Addressable demand", compact(d.addressable_volume || 0) + "/mo", "searches across the gaps")}
        ${card("Biggest gap", topCat, cats[topCat] + " opportunities")}
      </div>`;

    const chip = (id, label, n) => `<button class="gapchip ${_gapFilter === id ? "is-on" : ""}" data-f="${id}">${label} <b>${n}</b></button>`;
    const chips = `<div class="gapchips">${chip("all", "All", opps.length)}${catList.map((c) => chip(c, c, cats[c])).join("")}</div>`;

    const typeCls = (t) => /Comparison/.test(t) ? "cmp" : /Buying/.test(t) ? "guide" : /Guide|FAQ|Review/.test(t) ? "info" : "land";
    const rows = opps.map((o) => {
      const comp = o.competitors[0], others = o.competitors.length > 1 ? " +" + (o.competitors.length - 1) : "";
      const intents = (o.intent || []).slice(0, 2).join(" · ");
      return `<div class="gap" data-cat="${o.category}">
          <span class="gaptype gaptype--${typeCls(o.type)}">${o.type}</span>
          <div class="gap__main">
            <div class="gap__kw">${o.keyword}</div>
            <div class="gap__meta"><span class="gap__vol">${o.volume.toLocaleString("en-US")}/mo</span>
              <span class="gap__sep">·</span>${intents}<span class="gap__sep">·</span>
              <span class="gap__comp">${comp.name} ranks #${comp.position}${others} — you don't</span></div>
          </div>
          <span class="gap__cat">${o.category}</span>
        </div>`;
    }).join("");

    const method = `<div class="aivmethod"><b>How this works.</b> Straight from your Ahrefs content-gap export
      (JB Hi-Fi vs ${(d.competitors || []).join(", ")}). A gap = a competitor ranks in Google and JB doesn't.
      Filtered to your categories and buyer intent (branded and navigational queries removed), then ranked by
      search volume × intent × how well the rival already ranks. Refresh weekly by re-running the import.</div>`;

    host.innerHTML = summary + chips + `<div class="gaplist">${rows}</div>` + method;
    host.querySelectorAll(".gapchip").forEach((b) => b.addEventListener("click", () => {
      _gapFilter = b.dataset.f;
      host.querySelectorAll(".gapchip").forEach((x) => x.classList.toggle("is-on", x === b));
      host.querySelectorAll(".gap").forEach((g) => { g.style.display = (_gapFilter === "all" || g.dataset.cat === _gapFilter) ? "" : "none"; });
    }));
  }).catch(() => { host.innerHTML = `<p class="lede">Could not load content gaps.</p>`; });
}

/* ---- Marketing Ideas: topics → many ranked ideas (v2 phase 2) ----------- */
function loadMarketingIdeas() {
  const host = $("ideas");
  if (!host.children.length) host.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div>';
  return api("/api/ideas").then((d) => {
    if (!d.available) {
      host.innerHTML = `<p class="lede">Marketing ideas appear once the content-gap data is imported
        — run <code>import_ahrefs.py</code> to populate the topics.</p>`;
      return;
    }
    const topics = d.topics || [];
    if (!topics.length) { host.innerHTML = `<p class="lede">No topics generated yet.</p>`; return; }
    const compact = (n) => n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? Math.round(n / 1e3) + "K" : String(n);
    const laneCls = (l) => ({ "SEO": "seo", "Commercial": "com", "Content": "con", "Social": "soc", "AI Visibility": "ai" })[l] || "con";

    const card = (lbl, big, sub) => `<div class="aivcard"><div class="aivcard__lbl">${lbl}</div><div class="aivcard__big">${big}</div><div class="aivcard__sub">${sub}</div></div>`;
    const summary = `<div class="aivcards">
        ${card("Topics", d.topic_count, "discovered from your gaps")}
        ${card("Marketing ideas", d.idea_count, "generated and ranked")}
        ${card("Addressable demand", compact(d.addressable_volume || 0) + "/mo", "across all topics")}
        ${card("Most-used lane", d.top_lane || "—", "where the wins cluster")}
      </div>`;

    const topicHTML = (t) => {
      const rival = t.competitors[0];
      const ev = `${t.total_volume.toLocaleString("en-US")}/mo unmet demand · ${t.gap_count} gap${t.gap_count > 1 ? "s" : ""}` +
        (rival ? ` · ${rival.name} ranks #${rival.position} for “${t.top_keyword}”` : "");
      const ideas = t.ideas.map((i) => `
          <div class="idea">
            <span class="idea__lane idea__lane--${laneCls(i.lane)}">${i.lane}</span>
            <div class="idea__body">
              <div class="idea__what">${i.what}</div>
              <div class="idea__why">${i.why}</div>
              <div class="idea__meta"><span class="idea__type">${i.type}</span>
                <span class="ipill">${i.confidence} confidence</span>
                <span class="ipill">${i.impact} impact</span>
                <span class="ipill">${i.effort} effort</span>
                <span class="idea__whynow">Why now — ${i.why_now}</span></div>
            </div>
            <span class="idea__score" title="opportunity score">${i.score}</span>
          </div>`).join("");
      return `<div class="topic">
          <div class="topic__head">
            <div><div class="topic__title">${t.topic}<span class="topic__cat">${t.category}</span></div>
              <div class="topic__ev">${ev}</div></div>
            <span class="topic__count">${t.idea_count} ideas</span>
          </div>
          <div class="topic__ideas">${ideas}</div>
        </div>`;
    };

    const method = `<div class="aivmethod"><b>How this works.</b> Each topic is discovered from your content-gap
      keywords (the shared theme inside a category); the engine then generates ideas across five lanes and ranks
      them by search demand × buyer intent × how hard rivals already rank — grounded in real data, no guesswork.
      Connect Google and it will learn which idea <i>types</i> actually pay off, and let those rise.</div>`;

    host.innerHTML = summary + topics.map(topicHTML).join("") + method;
  }).catch(() => { host.innerHTML = `<p class="lede">Could not load marketing ideas.</p>`; });
}

/* ---- Principle-based learning: which idea TYPES pay off ------------------ */
function loadPrinciples() {
  const host = $("principles");
  if (!host) return;
  return api("/api/principles").then((d) => {
    const ps = d.principles || [];
    if (!ps.length) { host.innerHTML = ""; return; }
    const max = Math.max(...ps.map((p) => p.score), 0.01);
    host.innerHTML = ps.map((p) => `
        <div class="prin">
          <div class="prin__top">
            <span class="prin__type">${p.type}</span>
            <span class="prin__basis ${p.n > 0 ? "is-learned" : ""}">${p.basis}</span>
            <span class="prin__score">${p.score.toFixed(2)}</span>
          </div>
          <div class="prin__track"><div class="prin__fill" style="width:${Math.round(p.score / max * 100)}%"></div></div>
          <div class="prin__why">${p.rationale}</div>
        </div>`).join("");
  }).catch(() => {});
}

/* ---- Google integrations (connect GSC/GA4 → real outcome learning) ------ */
async function connectGoogle() {
  try {
    const d = await api("/api/google/auth");
    if (d.auth_url) { window.location.href = d.auth_url; return; }
  } catch (e) {}
  toast("Google sign-in isn't available right now.");
}
async function disconnectGoogle() {
  try { await api("/api/google/disconnect", { method: "POST" }); } catch (e) {}
  loadIntegrations();
}
async function selectProperty(service, el) {
  if (!el.value) return;
  try {
    await api("/api/google/select", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ service, property_id: el.value }) });
    toast("Property selected — collecting your performance data…");
    loadIntegrations(); loadPerformance();
  } catch (e) {}
}
function intgRow(name, service, st) {
  const status = st.connected ? `<span class="intg__ok">Connected ✅</span>`
    : st.granted ? `<span class="intg__warn">Choose a property ↓</span>`
      : `<span class="intg__off">Not connected</span>`;
  const picker = st.granted
    ? `<select class="intg__sel" data-service="${service}" onchange="selectProperty('${service}', this)">
         <option value="">Loading properties…</option></select>` : "";
  return `<div class="intg"><div class="intg__top"><span class="intg__name">${name}</span>${status}</div>${picker}</div>`;
}
function loadIntegrations() {
  const host = $("integrations");
  if (!host) return Promise.resolve();
  return api("/api/google/status").then((s) => {
    if (!s.oauth_configured) {
      host.innerHTML = `<p class="intg__note">Google connection isn't enabled on this deployment yet. Once an
        admin adds Google credentials, clients can connect <b>Search Console</b> and <b>Analytics 4</b> here so
        the engine learns from real SEO outcomes. Everything else works without it.</p>`;
      return;
    }
    if (!s.account_connected) {
      host.innerHTML = `<p class="intg__note">Connect your Google account (read-only) so the engine can measure
        the real-world impact of the pages you build — clicks, rankings and traffic — and learn from what
        actually works.</p><button class="btn" onclick="connectGoogle()">Connect Google</button>`;
      return;
    }
    host.innerHTML = intgRow("Google Search Console", "gsc", s.gsc)
      + intgRow("Google Analytics 4", "ga4", s.ga4)
      + `<button class="linkbtn" onclick="disconnectGoogle()">Disconnect Google</button>`;
    ["gsc", "ga4"].forEach((svc) => {
      if (!s[svc].granted) return;
      api("/api/google/properties?service=" + svc).then((d) => {
        const sel = host.querySelector(`.intg__sel[data-service="${svc}"]`);
        if (!sel) return;
        const cur = s[svc].property;
        sel.innerHTML = `<option value="">— select your property —</option>` +
          (d.properties || []).map((p) =>
            `<option value="${p.id}" ${p.id === cur ? "selected" : ""}>${p.name}</option>`).join("");
      }).catch(() => {});
    });
  }).catch(() => {});
}

/* ---- Recommendation performance (real measured outcomes) --------------- */
function loadPerformance() {
  const host = $("performance");
  if (!host) return Promise.resolve();
  return api("/api/performance").then((p) => {
    if (!p.connected) {
      host.innerHTML = `<p class="perf__empty">Connect <b>Google Search Console</b> and <b>GA4</b> in Settings
        to measure the real-world impact of implemented recommendations — click growth, ranking gains and
        traffic uplift — and let those results refine the engine over time.</p>`;
      return;
    }
    const pct = (v) => v == null ? "—" : (v > 0 ? "+" : "") + v + "%";
    const stat = (val, label) => `<div class="perf__stat"><b>${val}</b><span>${label}</span></div>`;
    host.innerHTML = `<div class="perf__grid">
        ${stat(p.total, "Implemented")}
        ${stat(p.evaluated, "Evaluated")}
        ${stat(p.positive, "Positive outcomes")}
        ${stat(p.pending, "Still evaluating")}
        ${stat(pct(p.avg_click_growth), "Avg click growth")}
        ${stat(p.avg_position_gain == null ? "—" : "+" + p.avg_position_gain, "Avg ranking gain (positions)")}
      </div>
      <p class="panel__note">${p.real_updates} real outcome(s) have refined the model so far. Recommendations
        are measured 30–90 days after you mark them implemented — real results, never fabricated.</p>`;
  }).catch(() => { host.innerHTML = `<p class="perf__empty">Could not load performance data.</p>`; });
}

async function markDone(c, btn) {
  const url = window.prompt("Which page did you create or update for this recommendation?\n(Enter the URL so we can track its results.)", "");
  if (url === null) return;
  try {
    const ideaType = c.action === "Optimise existing page" ? "Category optimisation" : "New landing page";
    await api("/api/recommendations/implemented", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rec_id: c.id, target_url: (url || "").trim(), idea_type: ideaType }) });
    btn.textContent = "✓ Tracking results";
    btn.disabled = true;
    toast("Marked as done — we'll measure its impact over the next 30–90 days.");
  } catch (e) { toast("Couldn't save that just now."); }
}

/* ---- Data page: upload the weekly Ahrefs exports ------------------------ */
const _fmtBig = (n) => {
  n = +n || 0;
  return n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? Math.round(n / 1e3) + "K" : String(n);
};
const UPLOAD_FIELDS = [
  ["content_gap", "Content Gap — JB vs rivals", "the keywords rivals rank for that you don't"],
  ["jbhifi", "JB Hi-Fi — Top Pages", "your strongest pages — needed for “defend your lead”"],
  ["harveynorman", "Harvey Norman — Top Pages", ""],
  ["thegoodguys", "The Good Guys — Top Pages", ""],
  ["officeworks", "Officeworks — Top Pages", ""],
];
function renderUploadRows() {
  const host = $("uplRows");
  if (host.children.length) return;              // build once
  host.innerHTML = UPLOAD_FIELDS.map(([f, label, hint]) => `
    <label class="uplrow" data-field="${f}">
      <span class="uplrow__l"><b>${label}</b>${hint ? `<span>${hint}</span>` : ""}</span>
      <span class="uplrow__file"><span class="uplrow__name" data-name>Choose .csv…</span>
        <input type="file" accept=".csv" data-field="${f}" hidden></span>
    </label>`).join("");
  host.querySelectorAll('input[type="file"]').forEach((inp) => {
    inp.addEventListener("change", () => {
      const name = inp.closest(".uplrow").querySelector("[data-name]");
      name.textContent = inp.files[0] ? inp.files[0].name : "Choose .csv…";
      inp.closest(".uplrow").classList.toggle("is-set", !!inp.files[0]);
    });
  });
}
function loadDataPage() {
  renderUploadRows();
  return api("/api/ahrefs/status").then((s) => {
    const srcLabel = { uploaded: "Your uploaded exports", committed: "Built-in snapshot", none: "None yet" };
    const srcClass = s.source === "uploaded" ? "is-live" : s.source === "none" ? "is-none" : "";
    const when = s.generated
      ? new Date(s.generated * 1000).toLocaleDateString("en-US", { day: "numeric", month: "short", year: "numeric" })
      : "—";
    const cats = Object.entries(s.by_category || {})
      .map(([c, n]) => `<span class="dchip">${c} <b>${n}</b></span>`).join("") || "<span class='dmuted'>none yet</span>";
    const sites = Object.entries(s.sites || {})
      .map(([n, t]) => `<div class="dsite"><span>${n}</span><b>${_fmtBig(t)} traffic</b></div>`).join("");
    $("dataStatus").innerHTML = `
      <div class="dgrid">
        <div class="dstat ${srcClass}"><span>Source</span><b>${srcLabel[s.source] || "—"}</b></div>
        <div class="dstat"><span>Last updated</span><b>${when}</b></div>
        <div class="dstat"><span>Gaps kept</span><b>${(s.kept || 0).toLocaleString("en-US")}</b></div>
        <div class="dstat"><span>Total demand</span><b>${_fmtBig(s.total_demand)}/mo</b></div>
      </div>
      <div class="dsub">Content gaps by category</div>
      <div class="dchips">${cats}</div>
      ${sites ? `<div class="dsub">Competitor traffic tracked</div><div class="dsites">${sites}</div>` : ""}`;
  }).catch(() => { $("dataStatus").innerHTML = "<p class='lede'>Could not load the data status.</p>"; });
}
function renderUploadResult(res) {
  const parts = [];
  const cg = res.content_gaps, tp = res.top_pages;
  if (cg) parts.push(`<div class="uplres__ok">✓ Content gaps rebuilt — kept <b>${(cg.kept || 0).toLocaleString("en-US")}</b>
    of ${(cg.total_gaps_scanned || 0).toLocaleString("en-US")} scanned · demand <b>${_fmtBig(cg.total_demand)}/mo</b></div>`);
  if (tp) parts.push(`<div class="uplres__ok">✓ Top pages rebuilt — ${Object.entries(tp.sites || {})
    .map(([n, t]) => `${n} ${_fmtBig(t)}`).join(" · ")}</div>`);
  if (cg && !cg.kept) parts.push(`<div class="uplres__warn">⚠ 0 gaps kept — was that the raw Ahrefs
    <b>Content Gap</b> export (UTF-16 .csv)? Nothing else was changed.</div>`);
  $("uplResult").innerHTML = parts.length ? `<div class="uplres">${parts.join("")}</div>` : "";
}
async function submitAhrefs(e) {
  e.preventDefault();
  const inputs = [...$("uplRows").querySelectorAll('input[type="file"]')];
  const fd = new FormData();
  let n = 0;
  inputs.forEach((inp) => { if (inp.files[0]) { fd.append(inp.dataset.field, inp.files[0]); n++; } });
  if (!n) { toast("Choose at least one CSV to upload."); return; }
  const btn = $("uplBtn"), label = btn.textContent;
  btn.disabled = true; btn.textContent = "Uploading…";
  $("uplMsg").textContent = ""; $("uplMsg").className = "upl__msg";
  try {
    const r = await fetch("/api/ahrefs/upload", { method: "POST", body: fd });
    const res = await r.json().catch(() => ({}));
    if (!r.ok || !res.ok) throw new Error(res.error || "Upload failed.");
    renderUploadResult(res);
    toast("Applied — the plan and gaps just updated from your new data.");
    inputs.forEach((inp) => { inp.value = ""; inp.dispatchEvent(new Event("change")); });
    loadDataPage();
    loadDashboard(); loadBrief();                 // refresh the AI-facing views live
  } catch (err) {
    $("uplMsg").textContent = String(err.message || err).slice(0, 160);
    $("uplMsg").className = "upl__msg upl__msg--err";
  } finally {
    btn.disabled = false; btn.textContent = label;
  }
}

/* ---- view routing ------------------------------------------------------- */
const VIEW_META = {
  dashboard: ["Overview", "Dashboard"],
  plan: ["Your plan", "What to do this week"],
  signals: ["The signals behind every recommendation", "Market signals"],
  competitors: ["New pages rivals are publishing", "Competitors"],
  gaps: ["Content competitors have and you don't", "Content gaps"],
  ideas: ["Many ideas per topic, ranked", "Marketing ideas"],
  aivis: ["Your presence in AI answers", "AI Visibility"],
  proof: ["Validated across 30 markets", "How it works"],
  learning: ["What the system figured out", "What it's learned"],
  data: ["This week's Ahrefs exports, straight into the AI", "Market data"],
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
  if (name === "gaps") loadContentGaps();
  if (name === "ideas") loadMarketingIdeas();
  if (name === "aivis") loadAiVisibility();
  if (name === "settings") loadIntegrations();
  if (name === "data") loadDataPage();
  if (name === "learning") { loadPerformance(); loadPrinciples(); }
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
$("ahrefsForm").addEventListener("submit", submitAhrefs);

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
    asstAdd("bot", "Hi — ask me anything about your market. I can dig into your categories, " +
      "search volumes, competitors and AI visibility. Try: “what should we do first?”, " +
      "“what's our AI share of voice?”, “what are competitors publishing?”, or " +
      "“what's the search volume for headphones?”");
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
loadCompetitors();
loadAiVisibility();
loadPerformance();
loadIntegrations();
updateGreeting();
setInterval(updateGreeting, 30000);   // keep the clock current
wireGoto();
// returning from the Google OAuth consent flow?
if (location.search.indexOf("google=connected") >= 0) {
  toast("Google connected — pick your properties in Settings.");
  showView("settings");
  history.replaceState({}, "", "/");
} else if (location.search.indexOf("google=error") >= 0) {
  toast("Google connection didn't complete. Please try again.");
  history.replaceState({}, "", "/");
  showView("dashboard");
} else {
  showView("dashboard");
}
