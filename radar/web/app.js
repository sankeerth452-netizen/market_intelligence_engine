/* The Radar — dashboard logic (vanilla JS, no build step) */
const $ = (id) => document.getElementById(id);
const SRC_LABEL = { google_trends: "Trends", tiktok: "TikTok", instagram: "Instagram" };

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
function fmtDate(iso) {
  try { return new Date(iso + "T00:00:00").toLocaleDateString(undefined,
    { weekday: "long", day: "numeric", month: "long", year: "numeric" }); }
  catch (e) { return iso; }
}

function srcChip(link) {
  const s = link.source;
  return `<a class="src src--${s}" href="${esc(link.url)}" target="_blank" rel="noopener">${SRC_LABEL[s] || s}</a>`;
}

function ideaCard(idea, i) {
  const now = /right.?now/i.test(idea.why_now || "");
  return `<article class="idea ${now ? "idea--now" : ""}">
    <div class="idea__rank">IDEA ${i + 1}</div>
    <div class="idea__title">${esc(idea.title)}</div>
    <div class="idea__row"><b>Signal</b><span>${esc(idea.signal)}</span></div>
    <div class="idea__row"><b>Why now</b><span>${esc(idea.why_now)}</span></div>
    <div class="idea__foot">
      <span class="play">${esc(idea.play)}</span>
      ${idea.link ? `<a class="idea__link" href="${esc(idea.link)}" target="_blank" rel="noopener">See the signal →</a>` : ""}
    </div>
  </article>`;
}

function trendRow(t, i) {
  const pct = Math.round((t.score || 0) * 100);
  const srcs = (t.links || []).map(srcChip).join("");
  return `<div class="trend">
    <div class="trend__rank">${String(i + 1).padStart(2, "0")}</div>
    <div>
      <div class="trend__name">${esc(t.term)}
        <span class="speed speed--${t.speed}">${t.speed === "right-now" ? "right now" : "building"} · ${esc(t.window)}</span>
      </div>
      <div class="trend__metric">${esc((t.metrics || [])[0] || "")}</div>
    </div>
    <div class="trend__bar" title="${pct}"><i style="width:${pct}%"></i></div>
    <div class="trend__srcs">
      ${t.agreement > 1 ? `<span class="agree">${t.agreement} sources agree</span>` : ""}
      ${srcs}
    </div>
  </div>`;
}

function render(d) {
  $("topic").textContent = d.topic || "crafts";
  $("sub").textContent = `Daily social trend discovery · ${(d.topic || "crafts")} · ${d.geo || "AU"}`;
  const badge = $("modeBadge");
  if (d.sample) { badge.textContent = "SAMPLE DATA"; badge.className = "badge badge--sample"; }
  else if (d.live) { badge.textContent = "LIVE · APIFY"; badge.className = "badge badge--live"; }
  else { badge.textContent = "OFFLINE"; badge.className = "badge"; }

  $("trendCount").textContent = (d.trends || []).length;
  $("heroMeta").innerHTML = `${esc(fmtDate(d.date))} · sources: Google Trends, TikTok, Instagram` +
    ` · ideas by ${d.ai ? "Claude" : "rules"}`;

  $("ideas").innerHTML = (d.ideas || []).map(ideaCard).join("") ||
    `<p class="foot">No ideas yet — hit Refresh.</p>`;
  $("trends").innerHTML = (d.trends || []).map(trendRow).join("");

  const note = d.sample
    ? `Showing <b>sample</b> crafts trends so you can see the shape of it. Add an <b>Apify API key</b> (and it will pull real Google Trends, TikTok and Instagram data). Nothing here is presented as real live data.`
    : `Live read via Apify. "Trending" = recent velocity on a source, boosted when independent sources agree.`;
  $("foot").innerHTML = `${note}<br>Generated ${esc(d.generated_at || "")} · topic <b>${esc(d.topic)}</b> (${esc(d.geo)}) · a daily read.`;
}

function load(url, opts) {
  return fetch(url, opts).then((r) => r.json()).then(render).catch(() => {
    $("ideas").innerHTML = `<p class="foot">Could not load the radar. Is the server running?</p>`;
  });
}

$("refresh").addEventListener("click", async () => {
  const b = $("refresh"); b.disabled = true; b.textContent = "Scanning…";
  try { await load("/api/refresh", { method: "POST" }); }
  finally { b.disabled = false; b.textContent = "Refresh"; }
});

load("/api/radar");
