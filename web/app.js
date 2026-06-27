/* Market Intelligence Engine — dashboard logic (vanilla JS, no build step) */

const state = { week: 8 };

const $ = (id) => document.getElementById(id);
const pad2 = (n) => String(n).padStart(2, "0");
const signed = (x) => (x >= 0 ? "+" : "\u2212") + Math.abs(x).toFixed(3);

// Live reward scale \u2014 must match config.REWARD_MIN / REWARD_MAX. A recorded
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
      <div class="conv__readout">est <b>${c.value.toFixed(2)}</b> \u00b1 ${c.uncertainty.toFixed(2)}</div>
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
    btn.textContent = "Recorded \u2713";
    if (range) range.disabled = true;          // lock the pick once its result is in
    toast(`Result fed back \u2014 the engine has now learned from <b>${r.model_updates}</b> outcomes`);
    // Watch it learn: weights, gauges AND the live conviction meters all move.
    await Promise.all([loadWeights(), loadStatus(), refreshBriefInPlace()]);
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

async function loadBrief() {
  const host = $("cards");
  host.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div>';
  $("weekVal").textContent = pad2(state.week);
  $("briefEyebrow").textContent = `Morning brief \u00b7 Week ${pad2(state.week)}`;
  try {
    const data = await api(`/api/brief?week=${state.week}&k=3`);
    host.innerHTML = "";
    if (!data.length) {
      host.innerHTML = '<p class="lede">No opportunities cleared the bar this week. Step forward a week.</p>';
      return;
    }
    data.forEach((c) => host.appendChild(cardEl(c)));
  } catch (e) {
    host.innerHTML = '<p class="lede">Could not load the brief. Is the server running on port 8000?</p>';
  }
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
      // Update existing bars in place so they GLIDE to their new lengths.
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
          const w = Math.abs(d.weight) / maxAbs * 48; // % of half-track
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
        `After <b>${data.model_updates}</b> results, the engine drove <b>tiktok_velocity negative</b> \u2014 it taught itself that loud single-channel hype predicts wasted effort, even though the original design trusted it at +0.15.`;
    } else {
      $("weightsNote").innerHTML =
        `Weights start near zero and move as results arrive. Record a few outcomes and watch them separate \u2014 this is the engine learning what actually pays.`;
    }
  });
}

/* ---- feedback-loop gauges ----------------------------------------------- */
function loadStatus() {
  return api("/api/status").then((s) => {
    $("gRecs").textContent = s.recommendations;
    $("gOuts").textContent = s.outcomes;
    $("gUpd").textContent = s.model_updates;
    $("gAvg").textContent = s.avg_reward == null ? "\u2014" : s.avg_reward.toFixed(2);
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

  // area between the two curves (where loop leads)
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
      const code = r.name.trim().split(/\s+/)[0];        // "P0".."P4"
      const closed = code === "P3" || code === "P4";     // learning is on
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
  });

  // The credible headline: the same comparison repeated across many markets.
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

/* ---- wiring ------------------------------------------------------------- */
function setWeek(w) {
  state.week = Math.max(0, Math.min(19, w));
  loadBrief();
}
$("weekUp").addEventListener("click", () => setWeek(state.week + 1));
$("weekDown").addEventListener("click", () => setWeek(state.week - 1));
$("resetBtn").addEventListener("click", async () => {
  await api("/api/reset", { method: "POST" });
  toast("Learning reset \u2014 the engine starts fresh");
  await Promise.all([loadBrief(), loadWeights(), loadStatus()]);
});

// initial load
loadBrief();
loadWeights();
loadStatus();
loadProof();
