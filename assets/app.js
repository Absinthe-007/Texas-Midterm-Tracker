/* TX '26 Tracker — front end. Plain JS + Leaflet, reads JSON the GitHub Action refreshes. */
(() => {
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const V = "?v=" + Math.floor(Date.now() / 600000); // bust cache every 10 min
const get = p => fetch(p + V).then(r => r.ok ? r.json() : null).catch(() => null);

const S = { races:{}, bios:{}, events:[], news:{}, meta:{}, cands:{}, static:{}, profiles:{}, forecast:null };
const STATE = { party:"all", kind:"all", level:"all", pollRace:"senate", hidePartisan:false, geo:"county", layer:null, raceFilter:"statewide" };
const SPEAK = new Set(["RALLY","TOWN_HALL","MEET_GREET","COMMUNITY","DEBATE_WATCH_PARTY","FUNDRAISER","OTHER","LEADERSHIP","WORKSHOP","MEETING","SOLIDARITY_EVENT","VISIBILITY_EVENT","FORUM","PRESS_CONFERENCE","PANEL"]);
const STATEWIDE_ORDER = ["senate","governor","ltgov","ag","comptroller","land","agriculture","railroad"];

/* ---------- helpers ---------- */
const slug = n => n.toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"");
const initials = n => { const w = n.replace(/,?\s+(Jr|Sr|II|III)\.?$/i,"").split(/\s+/).filter(Boolean); return ((w[0]||"")[0] + (w.length>1 ? w[w.length-1][0] : "")).toUpperCase(); };
const fmtMargin = m => m == null ? "—" : Math.abs(m) < 0.05 ? "Tied" : (m > 0 ? "D+" : "R+") + Math.abs(m).toFixed(1);
const mClass = m => m == null || Math.abs(m) < 0.05 ? "T" : m > 0 ? "D" : "R";
const money = v => v == null ? "—" : v >= 1e6 ? "$" + (v/1e6).toFixed(1) + "M" : v >= 1e3 ? "$" + Math.round(v/1e3) + "K" : "$" + v;
const dfmt = (iso, o = {month:"short", day:"numeric"}) => iso ? new Date(iso.length === 10 ? iso + "T12:00:00" : iso).toLocaleDateString("en-US", o) : "";
const tfmt = iso => iso ? new Date(iso).toLocaleTimeString("en-US",{hour:"numeric",minute:"2-digit",timeZone:"America/Chicago"}) : "";
const ago = iso => { const s=(Date.now()-new Date(iso))/1000; return s<3600?Math.round(s/60)+"m ago":s<86400?Math.round(s/3600)+"h ago":Math.round(s/86400)+"d ago"; };
const prettyType = t => (t||"").toLowerCase().replace(/_/g," ").replace(/\b\w/g,c=>c.toUpperCase());
const partyName = p => ({D:"Democrat",R:"Republican",L:"Libertarian",G:"Green",I:"Independent"})[p] || p;

function avatar(c, extra = "") {
  const bg = c.party==="D"?"linear-gradient(135deg,#2563eb,#22d3ee)":c.party==="R"?"linear-gradient(135deg,#dc2626,#fb923c)":"linear-gradient(135deg,#6b7280,#a855f7)";
  const img = c.photo ? `<img src="${esc(c.photo)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">` : "";
  return `<div class="avatar ${extra}" style="background:${bg}"><span>${esc(initials(c.name))}</span>${img}</div>`;
}

/* ---------- theme ---------- */
const savedTheme = (() => { try { return localStorage.getItem("tx26-theme"); } catch { return null; } })();
if (savedTheme) document.documentElement.dataset.theme = savedTheme;
$("#themeBtn").onclick = () => {
  const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem("tx26-theme", t); } catch {}
  setTiles();
};

/* ---------- tabs ---------- */
$$("#tabs button").forEach(b => b.onclick = () => {
  $$("#tabs button").forEach(x => x.classList.toggle("active", x === b));
  $$(".view").forEach(v => v.classList.toggle("active", v.id === "view-" + b.dataset.tab));
  if (b.dataset.tab === "trail") trailMap.invalidateSize();
  if (b.dataset.tab === "shift") { shiftMap.invalidateSize(); if (!shiftLayer) { shiftMap.fitBounds(TX); drawShift(); } }
  window.scrollTo({top:0, behavior:"smooth"});
});

/* ---------- countdown ---------- */
function headerInfo() {
  const now = new Date(), ed = new Date("2026-11-03T07:00:00-06:00");
  const days = Math.ceil((ed - now) / 864e5);
  $("#countdown").textContent = days > 1 ? `🗳️ ${days} days to Nov 3` : days === 1 ? "🗳️ Election Day is tomorrow" : days === 0 ? "🗳️ Election Day — go vote!" : "🗳️ Results season";
  const evs = new Date("2026-10-19T00:00:00-05:00"), eve = new Date("2026-10-31T00:00:00-05:00");
  const ep = $("#evpill");
  if (now < evs) ep.textContent = `Early voting opens Mon, Oct 19`;
  else if (now < eve) { ep.textContent = "✅ Early voting is open (thru Oct 30)"; ep.classList.add("live"); }
  else ep.textContent = "Early voting closed";
}

/* ---------- maps ---------- */
const TX = [[25.8,-106.7],[36.5,-93.5]];
const trailMap = L.map("trailMap", {zoomControl:true, minZoom:5, maxZoom:17, maxBounds:[[22,-112],[39,-88]]}).fitBounds(TX);
const shiftMap = L.map("shiftMap", {zoomControl:true, minZoom:5, maxZoom:17, maxBounds:[[22,-112],[39,-88]]}).fitBounds(TX);
let tiles = [];
function setTiles() {
  tiles.forEach(t => t.remove()); tiles = [];
  const dark = document.documentElement.dataset.theme === "dark";
  // Esri canvas basemaps: free with attribution, no API key
  const base = `https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/${dark ? "World_Dark_Gray_Base" : "World_Light_Gray_Base"}/MapServer/tile/{z}/{y}/{x}`;
  const ref = `https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/${dark ? "World_Dark_Gray_Reference" : "World_Light_Gray_Reference"}/MapServer/tile/{z}/{y}/{x}`;
  const attr = "Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors";
  tiles.push(L.tileLayer(base, {attribution:attr, maxZoom:16}).addTo(trailMap));
  tiles.push(L.tileLayer(ref, {maxZoom:16, pane:"overlayPane"}).addTo(trailMap));
  tiles.push(L.tileLayer(base, {attribution:attr, maxZoom:16}).addTo(shiftMap));
  if (!shiftMap.getPane("labels")) { shiftMap.createPane("labels"); shiftMap.getPane("labels").style.zIndex = 450; shiftMap.getPane("labels").style.pointerEvents = "none"; }
  tiles.push(L.tileLayer(ref, {maxZoom:16, pane:"labels"}).addTo(shiftMap));
}

/* ---------- data load ---------- */
Promise.all([
  get("data/live/races.json"), get("data/live/bios.json"), get("data/live/events.json"), get("data/live/news.json"), get("data/live/meta.json"),
  get("data/static/tx_counties.geojson"), get("data/static/tx_cd2025.geojson"), get("data/static/county_results.json"), get("data/static/district_results.json"),
  get("data/live/profiles.json"), get("data/live/forecast.json"),
]).then(([races, bios, events, news, meta, cgeo, dgeo, cres, dres, profiles, forecast]) => {
  S.profiles = profiles?.profiles || {}; S.forecast = forecast;
  S.races = races?.races || {}; S.bios = bios?.bios || {}; S.events = events?.events || []; S.news = news?.news || {}; S.meta = meta || {};
  S.static = {cgeo, dgeo, cres, dres};
  buildCandidates();
  const up = meta?.updated || races?.updated;
  $("#updated").textContent = up ? `Live · updated ${ago(up)}` : "Live data";
  headerInfo(); setTiles();
  renderStories(); renderTrail(); setupPolls(); setupShift(); renderRaces(); renderForecast();
  const h = location.hash.match(/^#c\/(.+)/); if (h && S.cands[h[1]]) openLoadout(h[1]);
});

function buildCandidates() {
  for (const [rk, r] of Object.entries(S.races)) {
    for (const n of r.nominees || []) {
      const id = slug(n.name), bio = n.wiki ? S.bios[n.wiki] : null;
      S.cands[id] = {...n, id, race:rk, raceLabel:r.label, raceType:r.type, district:r.district, photo:bio?.photo, bio};
    }
  }
}
const candsOf = e => (e.candidates || []).map(id => S.cands[id]).filter(Boolean);
const eventParty = e => { const ps = [...new Set(candsOf(e).map(c => c.party))]; return ps.length === 1 ? ps[0] : ps.length ? "both" : "?"; };
const eventKind = e => e.kind === "reported" ? "reported" : SPEAK.has(e.type) ? "speak" : "volunteer";

/* ---------- stories row (statewide nominees, Dems first) ---------- */
function renderStories() {
  const list = [];
  for (const k of STATEWIDE_ORDER) {
    const r = S.races[k]; if (!r) continue;
    for (const p of ["D","R"]) { const n = r.nominees.find(n => n.party === p); if (n) list.push(S.cands[slug(n.name)]); }
  }
  const count = id => S.events.filter(e => e.candidates?.includes(id)).length;
  $("#stories").innerHTML = list.map(c => `
    <button class="story" data-id="${c.id}" title="${esc(c.name)}">
      <div class="ring ${c.party} ${count(c.id) ? "hot" : ""}">${avatar(c)}</div>
      <div class="nm">${esc(c.name.split(" ").slice(-1)[0])}</div>
      <div class="rc">${esc(shortRace(c))}</div>
    </button>`).join("");
  $$("#stories .story").forEach(b => b.onclick = () => openLoadout(b.dataset.id));
}
const shortRace = c => c.raceType === "house" ? "TX-" + c.district : ({senate:"Senate",governor:"Governor",ltgov:"Lt. Gov",ag:"Atty Gen",comptroller:"Comptroller",land:"Land",agriculture:"Ag",railroad:"Railroad"})[c.race] || c.raceLabel;

/* ---------- campaign trail ---------- */
const cluster = L.markerClusterGroup({showCoverageOnHover:false, maxClusterRadius:38, spiderfyOnMaxZoom:true,
  iconCreateFunction: cl => { const n = cl.getChildCount(), sz = n < 10 ? 36 : n < 30 ? 44 : 52;
    return L.divIcon({className:"", iconSize:[sz,sz], html:`<div class="clu" style="width:${sz}px;height:${sz}px">${n}</div>`}); }});
trailMap.addLayer(cluster);
const markerById = {};
function chipGroup(id, key, cb) {
  $$(`#${id} button`).forEach(b => b.onclick = () => {
    $$(`#${id} button`).forEach(x => x.classList.toggle("on", x === b));
    STATE[key] = b.dataset.v; cb();
  });
}
chipGroup("partyChips","party",renderTrail); chipGroup("kindChips","kind",renderTrail); chipGroup("levelChips","level",renderTrail);

function filteredEvents() {
  const now = Date.now();
  return S.events.filter(e => {
    const cs = candsOf(e); if (!cs.length) return false;
    if (STATE.party !== "all" && !cs.some(c => c.party === STATE.party)) return false;
    if (STATE.level !== "all" && !cs.some(c => c.raceType === STATE.level)) return false;
    if (STATE.kind !== "all" && eventKind(e) !== STATE.kind) return false;
    if (e.kind === "scheduled" && new Date(e.end || e.start) < now - 3600e3) return false;
    return true;
  }).sort((a,b) => {
    if (a.kind !== b.kind) return a.kind === "scheduled" ? -1 : 1;           // upcoming first
    return a.kind === "scheduled" ? new Date(a.start) - new Date(b.start) : new Date(b.start) - new Date(a.start);
  });
}

function eventMeta(e) {
  const k = eventKind(e);
  const when = e.kind === "scheduled" ? `${dfmt(e.start,{weekday:"short",month:"short",day:"numeric"})} · ${tfmt(e.start)}` : `Reported ${dfmt(e.start)}`;
  return `${when}${e.city ? " · " + esc(e.city) : ""}${e.virtual ? " · Virtual" : ""}` +
    ` <span class="tag ${k==="reported"?"news":""}">${k==="reported" ? esc(e.source) : k==="speak" ? prettyType(e.type) : prettyType(e.type) || "Volunteer"}</span>`;
}

function renderTrail() {
  const evs = filteredEvents();
  cluster.clearLayers();
  for (const k in markerById) delete markerById[k];
  for (const e of evs) {
    if (e.lat == null || e.virtual) continue;
    const c = candsOf(e)[0], party = eventParty(e);
    const icon = L.divIcon({className:"", iconSize:[38,38], iconAnchor:[19,19],
      html:`<div class="pin ${party} ${e.kind==="reported"?"reported":""}">${avatar(c)}</div>`});
    // nudge identical coordinates so pins don't stack perfectly
    const jitter = () => (Math.random() - .5) * 0.01;
    const m = L.marker([e.lat + jitter(), e.lng + jitter()], {icon});
    m.bindPopup(() => popupHtml(e), {maxWidth:280});
    cluster.addLayer(m); markerById[e.id] = m;
  }
  const list = $("#eventList");
  list.innerHTML = evs.length ? evs.slice(0, 250).map(e => {
    const c = candsOf(e)[0];
    return `<div class="ev-card" data-id="${esc(e.id)}">
      ${avatar(c)}
      <div><div class="t">${esc(e.title)}</div>
      <div class="m"><span class="tag ${c.party}">${esc(candsOf(e).map(x=>x.name.split(" ").slice(-1)[0]).join(" + "))} · ${esc(shortRace(c))}</span></div>
      <div class="m">${eventMeta(e)}</div></div></div>`;
  }).join("") : `<div class="empty">No stops match these filters yet. The tracker refreshes every 6 hours.</div>`;
  $$("#eventList .ev-card").forEach(el => el.onclick = () => {
    const m = markerById[el.dataset.id];
    if (m) { cluster.zoomToShowLayer(m, () => m.openPopup()); if (innerWidth < 900) $("#trailMap").scrollIntoView({behavior:"smooth"}); }
    else { const e = S.events.find(x => x.id === el.dataset.id); if (e?.url) window.open(e.url, "_blank", "noopener"); }
  });
}
function popupHtml(e) {
  const cs = candsOf(e);
  return `<div class="pop-t">${esc(e.title)}</div>
    <div class="pop-m">${eventMeta(e)}</div>
    ${e.venue && e.venue !== "Texas" ? `<div class="pop-m">📍 ${esc(e.venue)}${e.address ? ", " + esc(e.address) : ""}</div>` : ""}
    ${e.host ? `<div class="pop-m">Host: ${esc(e.host)}</div>` : ""}
    ${e.more_times ? `<div class="pop-m">+${e.more_times} more time slots</div>` : ""}
    <div style="display:flex;gap:6px;flex-wrap:wrap">
      ${cs.map(c => `<button class="pop-btn" onclick="window.__lo('${c.id}')">${esc(c.name)} loadout →</button>`).join("")}
      ${e.url ? `<a class="pop-btn" style="text-decoration:none;background:var(--card2);color:var(--text)" href="${esc(e.url)}" target="_blank" rel="noopener">${e.kind==="reported"?"Read story":"RSVP / details"} ↗</a>` : ""}
    </div>`;
}
window.__lo = id => openLoadout(id);

/* ---------- loadout drawer ---------- */
const LO_TABS = [["overview","Overview"],["promises","Promises"],["record","Votes"],["talk","Debates & talk"],["scrutiny","Scrutiny"],["trail","Trail & news"]];
let LO = {id:null, tab:"overview"};
function openLoadout(id, tab) {
  const c = S.cands[id]; if (!c) return;
  LO = {id, tab: tab || (LO.id === id ? LO.tab : "overview")};
  const r = S.races[c.race];
  const fc = S.forecast?.races?.[c.race];
  const pWin = fc ? (fc.p_dem_sim ?? fc.p_dem) : null;
  const myWin = pWin == null ? null : (c.party === "D" ? pWin : c.party === "R" ? 1 - pWin : null);
  const consensus = ratingConsensus(r.ratings);
  const office = c.raceType === "house" ? `U.S. House · Texas District ${c.district}` : r.label === "U.S. Senate" ? "U.S. Senate · Texas" : `Texas ${r.label}`;
  $("#drawerBody").innerHTML = `
    <div class="lo-hero ${c.party}">
      <div class="lo-top">${avatar(c, "xl")}
        <div class="lo-id">
          <div class="lo-run">Running for</div>
          <div class="lo-office">${esc(office)}</div>
          <div class="lo-sub">
            <span class="tag ${c.party}">${partyName(c.party)}</span>
            ${c.incumbent ? `<span class="tag">Incumbent</span>` : ""}
            ${consensus ? `<span class="tag" style="${ratingStyle(consensus)}">${esc(consensus)}</span>` : ""}
          </div>
        </div>
      </div>
      <div class="lo-name">${esc(c.name)}</div>
      ${c.bio?.description ? `<div class="lo-desc">${esc(c.bio.description)}</div>` : ""}
      ${myWin != null ? `<div class="lo-odds"><div class="lo-odds-bar"><i style="width:${(myWin*100).toFixed(0)}%"></i></div><span><b>${(myWin*100).toFixed(0)}%</b> chance to win (model)</span></div>` : ""}
    </div>
    <nav class="lo-tabs" role="tablist">${LO_TABS.map(([k,l]) => `<button role="tab" data-t="${k}" class="${LO.tab===k?"on":""}">${l}</button>`).join("")}</nav>
    <div class="lo-panel">${loPanel(c, r, LO.tab)}</div>`;
  $$("#drawerBody .lo-tabs button").forEach(b => b.onclick = () => { LO.tab = b.dataset.t; $("#drawerBody .lo-panel").innerHTML = loPanel(c, r, LO.tab); $$("#drawerBody .lo-tabs button").forEach(x => x.classList.toggle("on", x === b)); wirePanel(); });
  wirePanel();
  $("#drawer").classList.add("on"); $("#scrim").classList.add("on"); $("#drawer").setAttribute("aria-hidden","false");
  if (!tab) $("#drawer").scrollTop = 0;
  history.replaceState(null, "", "#c/" + id);
}
function wirePanel() {
  $$("#drawerBody .stop").forEach(el => el.onclick = () => {
    const m = markerById[el.dataset.ev]; closeLoadout(); $$("#tabs button")[0].click();
    if (m) setTimeout(() => cluster.zoomToShowLayer(m, () => m.openPopup()), 250);
  });
  $$("#drawerBody .vote-filter button").forEach(b => b.onclick = () => {
    $$("#drawerBody .vote-filter button").forEach(x => x.classList.toggle("on", x === b));
    $$("#drawerBody .vote").forEach(v => v.hidden = b.dataset.v !== "all" && v.dataset.v !== b.dataset.v);
  });
}
const headlines = (list, empty) => list?.length ? list.map(n => `<a class="news-item" href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.title)}<small>${esc(n.outlet)}${n.published ? " · " + ago(n.published) : ""}</small></a>`).join("") : `<p class="muted small">${empty}</p>`;
const newsOf = id => { const n = S.news[id]; return Array.isArray(n) ? {latest:n, said:[], scrutiny:[]} : (n || {latest:[], said:[], scrutiny:[]}); };
function loPanel(c, r, tab) {
  const prof = S.profiles[c.name] || {};
  const bpLink = prof.url ? `<a href="${esc(prof.url)}" target="_blank" rel="noopener">Ballotpedia ↗</a>` : "";
  if (tab === "overview") {
    const fin = r.finance?.candidates?.[c.name], finAll = r.finance?.candidates || {};
    const maxRaised = Math.max(1, ...Object.values(finAll).map(f => f.raised || 0));
    const avg = r.polls ? pollAverage(r.polls, STATE.hidePartisan) : null;
    const opp = (r.nominees || []).filter(n => n.name !== c.name && ["D","R"].includes(n.party));
    const fc = S.forecast?.races?.[c.race];
    const pitch = (prof.key_messages || []).slice(0, 3);
    return `
      ${pitch.length ? `<div class="lo-sec pitch"><h5>Their pitch, in their words</h5>${pitch.map(m => `<p class="quote">“${esc(m)}”</p>`).join("")}</div>` : ""}
      <div class="lo-sec"><h5>Stat line</h5><div class="stats3">
        <div><b>${avg ? avg[c.party]?.toFixed(1) + "%" : "—"}</b><span>Poll avg</span></div>
        <div><b>${fin ? money(fin.raised) : "—"}</b><span>Raised</span></div>
        <div><b>${fc?.mean != null ? fmtMargin(fc.mean) : "—"}</b><span>Model margin</span></div></div>
        ${avg ? `<div class="split" style="margin-top:14px"><div class="d" style="width:${avg.D}%"></div><div style="flex:1"></div><div class="r" style="width:${avg.R}%"></div></div>
        <div class="split-lbl"><span class="D">D ${avg.D.toFixed(1)}</span><span>${fmtMargin(avg.margin)} · ${avg.n} polls</span><span class="R">R ${avg.R.toFixed(1)}</span></div>` : `<p class="muted small" style="margin-top:10px">No public polling for this race yet.</p>`}
      </div>
      ${opp.length ? `<div class="lo-sec"><h5>Opponent</h5>${opp.map(o => { const oc = S.cands[slug(o.name)]; return `<div class="opp" onclick="window.__lo('${oc.id}')">${avatar(oc)}<div><b>${esc(o.name)}</b><div class="muted small">${partyName(o.party)}${o.incumbent?" · incumbent":""}</div></div><span>→</span></div>`; }).join("")}</div>` : ""}
      ${c.bio?.extract ? `<div class="lo-sec"><h5>Bio</h5><p>${esc(c.bio.extract)}</p></div>` : ""}
      ${Object.keys(finAll).length ? `<div class="lo-sec"><h5>Money race <span class="h5n">${esc((r.finance?.as_of||"").replace(/^Campaign finance reports? /i,""))}</span></h5>
        ${Object.entries(finAll).filter(([n,f])=>f.raised).sort((a,b)=>b[1].raised-a[1].raised).slice(0,4).map(([n,f]) => { const p = r.nominees.find(x=>x.name===n)?.party;
          return `<div class="small" style="margin-top:8px"><b>${esc(n)}</b> <span class="muted">· raised ${money(f.raised)} · cash ${money(f.cash)}</span><div class="money-bar"><div style="width:${(f.raised/maxRaised*100).toFixed(1)}%;background:${p==="D"?"var(--dem)":p==="R"?"var(--rep)":"var(--muted)"}"></div></div></div>`; }).join("")}</div>` : ""}
      <div class="lo-sec"><h5>Go deeper</h5><div class="links">
        ${prof.website ? `<a href="${esc(prof.website)}" target="_blank" rel="noopener">Campaign site ↗</a>` : ""}${bpLink}
        ${c.bio?.url ? `<a href="${esc(c.bio.url)}" target="_blank" rel="noopener">Wikipedia ↗</a>` : ""}
        ${c.raceType === "house" || c.race === "senate" ? `<a href="https://www.fec.gov/data/candidates/?q=${encodeURIComponent(c.name)}&state=TX" target="_blank" rel="noopener">FEC filings ↗</a>` : `<a href="https://www.ethics.state.tx.us/search/cf/" target="_blank" rel="noopener">TX Ethics Comm. ↗</a>`}
      </div></div>`;
  }
  if (tab === "promises") {
    const issues = prof.issues || [], msgs = prof.key_messages || [], against = prof.against || [];
    if (!issues.length && !msgs.length) return `<div class="lo-sec"><p>${esc(c.name)} hasn't published a platform that Ballotpedia has captured yet.</p>
      <div class="links" style="margin-top:12px">${prof.website ? `<a href="${esc(prof.website)}" target="_blank" rel="noopener">Read their campaign site ↗</a>` : ""}${bpLink}</div></div>`;
    return `
      ${msgs.length ? `<div class="lo-sec pitch"><h5>Top promises</h5>${msgs.map((m,i) => `<div class="promise"><span class="pn">${i+1}</span><p>${esc(m)}</p></div>`).join("")}</div>` : ""}
      ${issues.length ? `<div class="lo-sec"><h5>Where they stand, issue by issue</h5><div class="issues">${issues.map(x => `
        <details class="issue"><summary>${esc(x.issue)}<span>${x.points.length}</span></summary>${x.points.map(p => `<p>${AGAINST_RE.test(p) ? "🚫 " : "✅ "}${esc(p)}</p>`).join("")}</details>`).join("")}</div></div>` : ""}
      ${against.length ? `<div class="lo-sec"><h5>What they want to stop</h5>${against.map(a => `<p class="against">🚫 ${esc(a)}</p>`).join("")}</div>` : ""}
      <p class="fine">Excerpts in the candidate's own words, from their campaign website and Ballotpedia's candidate survey. ${bpLink}</p>`;
  }
  if (tab === "record") {
    const kv = prof.key_votes || [];
    if (!kv.length) return `<div class="lo-sec"><h5>Voting record</h5><p>${esc(c.name)} ${c.raceType === "house" && c.incumbent ? "has no key votes listed yet." : "hasn't served in Congress, so there's no congressional voting record to show."}
      ${/state (representative|senator)|texas (house|senate)/i.test((c.bio?.description||"") + (c.bio?.extract||"")) ? " They've served in the Texas Legislature; see their bills and votes on Texas Legislature Online." : ""}</p>
      <div class="links" style="margin-top:12px"><a href="https://capitol.texas.gov/Search/MemberSearch.aspx" target="_blank" rel="noopener">Texas Legislature Online ↗</a>${bpLink}</div></div>
      ${(prof.against||[]).length || (prof.issues||[]).length ? `<p class="fine">For where they say they stand, see the Promises tab.</p>` : ""}`;
    const yes = kv.filter(v => /^(yea|aye|yes)$/i.test(v.vote)).length, no = kv.filter(v => /^(nay|no)$/i.test(v.vote)).length;
    return `<div class="lo-sec"><h5>Key votes in Congress</h5>
      <div class="vote-filter chips"><button data-v="all" class="on">All ${kv.length}</button><button data-v="yea">Voted for · ${yes}</button><button data-v="nay">Voted against · ${no}</button></div>
      <div class="votes">${kv.map(v => { const k = /^(yea|aye|yes)$/i.test(v.vote) ? "yea" : /^(nay|no)$/i.test(v.vote) ? "nay" : "nv";
        return `<details class="vote" data-v="${k}"><summary><span class="vbadge ${k}">${k==="yea"?"✓ For":k==="nay"?"✕ Against":"– Didn't vote"}</span><span class="vb">${esc(v.bill)}${v.number ? ` <em>${esc(v.number)}</em>` : ""}</span></summary>
          <p>${esc(v.summary)}</p><p class="muted small">${esc(v.status || "")} · ${esc(v.congress || "")}</p></details>`; }).join("")}</div></div>
      <p class="fine">Key votes chosen by Ballotpedia (nonpartisan) from Congress's most-viewed bills. ${bpLink}</p>`;
  }
  if (tab === "talk") {
    const last = c.name.split(" ").slice(-1)[0];
    const debates = (r.debates || []).filter(d => (d.participants || []).some(p => p.includes(last)));
    const said = newsOf(c.id).said;
    return `<div class="lo-sec"><h5>Debates & forums</h5>${debates.length ? debates.map(d => `
        <div class="debate"><div class="dt"><b>${esc((d.date||"").replace(/,? 20\d\d/,""))}</b></div><div><div class="t">${esc(d.host || "Debate")}</div>
        <div class="muted small">${d.participants?.length ? "With " + esc(d.participants.filter(p=>!p.includes(last)).join(", ")) : ""}${d.moderator ? " · Moderator: " + esc(d.moderator) : ""}</div>
        ${d.url ? `<a href="${esc(d.url)}" target="_blank" rel="noopener" class="watch">▶ Watch / read (${esc(d.link_text || "link")})</a>` : ""}</div></div>`).join("") : `<p class="muted small">No debates listed for this race yet.</p>`}</div>
      <div class="lo-sec"><h5>What they've been saying</h5>${headlines(said, "No recent debate, town hall or interview coverage from tracked outlets.")}</div>
      <p class="fine">Coverage of debates, town halls, forums and interviews from established outlets. Tap through to read or watch what was said.</p>`;
  }
  if (tab === "scrutiny") {
    const wiki = c.bio?.scrutiny || [], bp = prof.noteworthy || [], sc = newsOf(c.id).scrutiny;
    const items = [...bp.map(x => ({...x, src:"Ballotpedia"})), ...wiki.map(x => ({...x, src:"Wikipedia"}))];
    return `<div class="lo-sec"><h5>Controversies & investigations on record</h5>${items.length ? items.map(x => `
        <a class="scr" href="${esc(x.url)}" target="_blank" rel="noopener"><b>${esc(x.title)}</b>${x.summary ? `<span>${esc(x.summary)}</span>` : ""}<small>${x.src} ↗</small></a>`).join("") : `<p class="muted small">Nothing listed in the Wikipedia or Ballotpedia profiles.</p>`}</div>
      <div class="lo-sec"><h5>In the news</h5>${headlines(sc, "No recent coverage of scandals, investigations or lawsuits from tracked outlets.")}</div>
      <p class="fine">Same rules for every candidate in both parties: encyclopedia sections and headlines that mention investigations, indictments, lawsuits, ethics complaints or allegations. Allegations aren't convictions, so read the source before drawing conclusions.</p>`;
  }
  // trail
  const evs = S.events.filter(e => e.candidates?.includes(c.id));
  const upcoming = evs.filter(e => e.kind === "scheduled" && new Date(e.end || e.start) > Date.now()).sort((a,b)=>new Date(a.start)-new Date(b.start));
  const reported = evs.filter(e => e.kind === "reported").sort((a,b)=>new Date(b.start)-new Date(a.start));
  return `<div class="lo-sec"><h5>On the trail</h5>
      ${upcoming.length || reported.length ? [...upcoming.slice(0,8), ...reported.slice(0,6)].map(e => { const d = new Date(e.start);
        return `<div class="stop" data-ev="${esc(e.id)}"><div class="dt">${d.toLocaleDateString("en-US",{month:"short"}).toUpperCase()}<b>${d.getDate()}</b></div>
          <div><div style="font-weight:600">${esc(e.title)}</div><div class="muted small">${e.kind==="scheduled" ? tfmt(e.start) + " · " : "Reported · "}${esc(e.city||"")}${e.virtual?" · Virtual":""} · ${esc(e.kind==="reported"?e.source:prettyType(e.type))}</div></div></div>`; }).join("")
      : `<p class="muted small">No public stops found yet. Campaigns often announce events only a day or two ahead.</p>`}</div>
    <div class="lo-sec"><h5>Latest headlines</h5>${headlines(newsOf(c.id).latest, "No recent coverage from tracked outlets.")}</div>`;
}
const AGAINST_RE = /^(oppose|opposes|opposing|end|ending|stop|stopping|repeal|ban|eliminate|eliminating|block|fight against|reject|abolish|prevent|reverse|defund|no more)\b/i;
function closeLoadout() { $("#drawer").classList.remove("on"); $("#scrim").classList.remove("on"); $("#drawer").setAttribute("aria-hidden","true"); history.replaceState(null,"",location.pathname); }
$("#drawerClose").onclick = closeLoadout; $("#scrim").onclick = closeLoadout;
addEventListener("keydown", e => { if (e.key === "Escape") closeLoadout(); });

/* ---------- forecast ---------- */
function renderForecast() {
  const F = S.forecast; if (!F) { $("#fcGrid").innerHTML = `<div class="empty">Forecast will appear after the next update.</div>`; return; }
  const H = F.house, maxH = Math.max(...H.hist);
  const card = k => { const r = S.races[k], f = F.races[k]; if (!r || !f || f.uncontested) return "";
    const p = f.p_dem_sim ?? f.p_dem, fav = p >= .5 ? "D" : "R", pf = Math.max(p, 1-p);
    const d = r.nominees.find(n=>n.party==="D"), rp = r.nominees.find(n=>n.party==="R");
    const word = pf >= .95 ? "Safe" : pf >= .8 ? "Likely" : pf >= .6 ? "Lean" : "Toss-up";
    return `<div class="fc ${fav}">
      <div class="fc-h"><span class="rl">${esc(r.label)}</span><span class="rbadge" style="${ratingStyle(word==="Toss-up"?"Toss-up":word+" "+fav)}">${word}${word!=="Toss-up"?" "+fav:""}</span></div>
      <div class="fc-odds"><div class="fc-c" onclick="window.__lo('${slug(d.name)}')">${avatar(S.cands[slug(d.name)])}<b class="D">${Math.round(p*100)}%</b><span>${esc(d.name.split(" ").slice(-1)[0])}</span></div>
        <div class="fc-bar"><i class="d" style="width:${p*100}%"></i><i class="r" style="width:${(1-p)*100}%"></i></div>
        <div class="fc-c" onclick="window.__lo('${slug(rp.name)}')">${avatar(S.cands[slug(rp.name)])}<b class="R">${Math.round((1-p)*100)}%</b><span>${esc(rp.name.split(" ").slice(-1)[0])}</span></div></div>
      <div class="fc-m">Projected <b>${fmtMargin(f.mean)}</b> · 80% range ${fmtMargin(f.lo)} to ${fmtMargin(f.hi)}</div>
      <div class="fc-w">${[["Polls",f.inputs.weights.polls,f.inputs.polls],["Fundamentals",f.inputs.weights.fundamentals,f.inputs.fundamentals],["Experts",f.inputs.weights.experts,f.inputs.experts]].filter(x=>x[1]>0).map(([l,w,v]) => `<span>${l} ${Math.round(w*100)}% <em>${fmtMargin(v)}</em></span>`).join("")}</div></div>`; };
  const sw = STATEWIDE_ORDER.map(card).join("");
  const hk = Object.keys(S.races).filter(k => S.races[k].type==="house" && F.races[k] && !F.races[k].uncontested && Math.abs((F.races[k].p_dem_sim ?? F.races[k].p_dem) - .5) < .4)
    .sort((a,b) => Math.abs((F.races[a].p_dem_sim??F.races[a].p_dem)-.5) - Math.abs((F.races[b].p_dem_sim??F.races[b].p_dem)-.5));
  $("#fcHouse").innerHTML = `
    <div class="hero-k">U.S. House delegation · 38 seats</div>
    <div class="hero-big D">${H.dem_median} <span class="muted" style="font-size:20px">Dem seats</span></div>
    <div class="muted small">80% of simulations land between <b>${H.dem_lo80}</b> and <b>${H.dem_hi80}</b> Democratic seats. Harris carried ${H.harris_won_districts} of these districts in 2024.</div>
    <div class="hist">${H.hist.map((v,i) => v ? `<i title="${i} D seats: ${(v/200).toFixed(1)}% of sims" class="${i>=H.dem_lo80&&i<=H.dem_hi80?"in":""}" style="height:${(v/maxH*100).toFixed(1)}%"></i>` : "").join("")}</div>
    <div class="hist-l"><span>${H.hist.findIndex(v=>v)} D</span><span>${H.hist.length-1-[...H.hist].reverse().findIndex(v=>v)} D</span></div>`;
  $("#fcGrid").innerHTML = sw;
  $("#fcHouseGrid").innerHTML = hk.map(card).join("") || `<div class="empty">No competitive districts.</div>`;
  $("#fcNote").innerHTML = `Model inputs: each race's polling average, the 2024 result shifted by the current generic-ballot environment (${fmtMargin(F.environment.generic_ballot)}), an incumbency bump, and the forecasters' consensus rating. 20,000 simulations with a shared statewide error. ${F.days_to_election} days out. It's a probabilistic estimate, so a 30% chance happens about 1 time in 3.`;
}

/* ---------- polls ---------- */
function pollAverage(polls, hidePartisan, days = 30, today = new Date()) {
  let ps = polls.filter(p => !(hidePartisan && p.partisan));
  let recent = ps.filter(p => (today - new Date(p.end + "T12:00:00")) / 864e5 <= days && new Date(p.end) <= today);
  if (recent.length < 3) recent = [...ps].sort((a,b) => b.end.localeCompare(a.end)).slice(0, 8);
  const best = {};
  [...recent].sort((a,b) => b.end.localeCompare(a.end) || ((b.pop==="LV") - (a.pop==="LV"))).forEach(p => { if (!best[p.pollster]) best[p.pollster] = p; });
  const use = Object.values(best); if (!use.length) return null;
  const D = use.reduce((s,p)=>s+p.results.D,0)/use.length, R = use.reduce((s,p)=>s+p.results.R,0)/use.length;
  return {D, R, margin:D-R, n:use.length, from:use.map(p=>p.end).sort()[0], to:use.map(p=>p.end).sort().slice(-1)[0]};
}
function setupPolls() {
  const keys = [...STATEWIDE_ORDER.filter(k => S.races[k]?.polls?.length),
    ...Object.keys(S.races).filter(k => S.races[k].type === "house" && S.races[k].polls?.length).sort((a,b)=>+S.races[a].district - +S.races[b].district)];
  $("#pollRaceChips").innerHTML = keys.map(k => `<button data-v="${k}" class="${k===STATE.pollRace?"on":""}">${esc(S.races[k].label)}</button>`).join("");
  chipGroup("pollRaceChips","pollRace",renderPolls);
  $("#hidePartisan").onchange = e => { STATE.hidePartisan = e.target.checked; renderPolls(); };
  renderPolls();
}
function renderPolls() {
  const r = S.races[STATE.pollRace]; if (!r) return;
  const dN = r.nominees.find(n=>n.party==="D"), rN = r.nominees.find(n=>n.party==="R");
  const polls = r.polls.filter(p => !(STATE.hidePartisan && p.partisan));
  const a = pollAverage(r.polls, STATE.hidePartisan);
  const lead = a ? (a.margin > 0 ? dN?.name : rN?.name) : null;
  const cons = ratingConsensus(r.ratings);
  $("#pollHero").innerHTML = a ? `
    <div class="hero-k">${esc(r.label)} · polling average</div>
    <div class="hero-big ${mClass(a.margin)}">${fmtMargin(a.margin)}</div>
    <div class="muted" style="font-size:13.5px">${Math.abs(a.margin) < 0.05 ? "Dead even" : `${esc(lead)} leads`} across ${a.n} pollster${a.n>1?"s":""} · ${dfmt(a.from)}–${dfmt(a.to)}</div>
    <div class="split"><div class="d" style="width:${a.D}%"></div><div style="flex:1"></div><div class="r" style="width:${a.R}%"></div></div>
    <div class="split-lbl"><span class="D" style="cursor:pointer" onclick="window.__lo('${slug(dN.name)}')">${esc(dN.name)} ${a.D.toFixed(1)}%</span><span class="R" style="cursor:pointer" onclick="window.__lo('${slug(rN.name)}')">${esc(rN.name)} ${a.R.toFixed(1)}%</span></div>
    ${r.ratings?.length ? `<div class="ratings">${r.ratings.map(x => `<span class="rate" title="as of ${esc(x.as_of||"")}">${esc(x.source.replace(/^The /,""))}: <b style="${ratingStyle(x.rating,true)}">${esc(x.rating)}</b></span>`).join("")}</div>` : ""}
    ${cons ? `<div class="muted" style="font-size:12px;margin-top:8px">Forecaster consensus: <b>${esc(cons)}</b></div>` : ""}` : `<div class="empty">No polls yet.</div>`;
  $("#pollChart").innerHTML = `<div class="hero-k" style="margin-bottom:8px">30-day trend</div><div class="chart">${trendSvg(polls, dN, rN)}</div>`;
  $("#pollList").innerHTML = polls.map(p => `
    <div class="poll"><div class="p1"><div><div class="pn">${p.url ? `<a href="${esc(p.url)}" target="_blank" rel="noopener" style="color:inherit">${esc(p.pollster)} ↗</a>` : esc(p.pollster)}
      ${p.partisan ? `<span class="tag ${p.partisan}" style="white-space:nowrap" title="Sponsored by or affiliated with a ${partyName(p.partisan)} group">${p.partisan} sponsor</span>` : ""}</div>
      <div class="pm">${dfmt(p.start)}–${dfmt(p.end,{month:"short",day:"numeric",year:"numeric"})} · ${p.n ? p.n.toLocaleString() : "?"} ${esc(p.pop||"")}${p.moe ? " · ±" + p.moe : ""}</div></div>
      <span class="mpill ${mClass(p.margin)}">${fmtMargin(p.margin)}</span></div>
      <div class="minibar"><div class="d" style="width:${p.results.D}%"></div><div style="flex:1"></div><div class="r" style="width:${p.results.R}%"></div></div>
      <div class="split-lbl" style="font-size:12px;margin-top:5px"><span class="D">${p.results.D}%</span>${p.undecided!=null?`<span class="muted">${p.undecided}% undecided</span>`:""}<span class="R">${p.results.R}%</span></div>
    </div>`).join("");
}
function trendSvg(polls, dN, rN) {
  if (polls.length < 2) return `<div class="empty">Not enough polls for a trend.</div>`;
  const sorted = [...polls].filter(p => p.end >= "2026-01-01").sort((a,b)=>a.end.localeCompare(b.end));
  if (sorted.length < 2) return `<div class="empty">Not enough 2026 polls for a trend.</div>`;
  const t0 = new Date(sorted[0].end), t1 = new Date("2026-11-03");
  const days = [...new Set(sorted.map(p=>p.end))];
  const pts = days.map(d => { const win = sorted.filter(p => p.end <= d && (new Date(d) - new Date(p.end)) / 864e5 <= 30); if (win.length < 2) return null;
    const a = pollAverage(win, false, 30, new Date(d+"T23:00:00")); return a && {d, D:a.D, R:a.R}; }).filter(Boolean);
  if (!pts.length) return `<div class="empty">Not enough polls for a trend.</div>`;
  const all = sorted.flatMap(p => [p.results.D, p.results.R]);
  const lo = Math.floor(Math.min(...all) - 2), hi = Math.ceil(Math.max(...all) + 2);
  const W = 640, H = 260, P = {l:34, r:86, t:14, b:26};
  const x = d => P.l + (new Date(d) - t0) / (t1 - t0) * (W - P.l - P.r);
  const y = v => P.t + (hi - v) / (hi - lo) * (H - P.t - P.b);
  const line = k => pts.map((p,i) => `${i?"L":"M"}${x(p.d).toFixed(1)},${y(p[k]).toFixed(1)}`).join("");
  const grid = []; for (let v = Math.ceil(lo/5)*5; v <= hi; v += 5) grid.push(`<line x1="${P.l}" x2="${W-P.r}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line)"/><text x="${P.l-6}" y="${y(v)+4}" text-anchor="end" font-size="11" fill="var(--muted)">${v}</text>`);
  const months = []; for (let m = new Date(t0.getFullYear(), t0.getMonth()+1, 1); m <= t1; m.setMonth(m.getMonth()+ (t1-t0>200*864e5?2:1))) months.push(`<text x="${x(m)}" y="${H-6}" font-size="11" fill="var(--muted)" text-anchor="middle">${m.toLocaleDateString("en-US",{month:"short"})}</text>`);
  const dots = sorted.map(p => `<circle cx="${x(p.end)}" cy="${y(p.results.D)}" r="3" fill="var(--dem)" opacity=".35"/><circle cx="${x(p.end)}" cy="${y(p.results.R)}" r="3" fill="var(--rep)" opacity=".35"/>`).join("");
  const last = pts[pts.length-1];
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Polling trend">
    ${grid.join("")}${months.join("")}
    <line x1="${x("2026-11-03")}" x2="${x("2026-11-03")}" y1="${P.t}" y2="${H-P.b}" stroke="var(--acc)" stroke-dasharray="4 4"/>
    <text x="${x("2026-11-03")-4}" y="${P.t+10}" font-size="10.5" fill="var(--acc)" text-anchor="end">Nov 3</text>
    ${dots}
    <path d="${line("D")}" fill="none" stroke="var(--dem)" stroke-width="3" stroke-linecap="round"/>
    <path d="${line("R")}" fill="none" stroke="var(--rep)" stroke-width="3" stroke-linecap="round"/>
    <text x="${x(last.d)+6}" y="${y(last.D)+4}" font-size="12" font-weight="700" fill="var(--dem2)">${esc(dN.name.split(" ").slice(-1)[0])} ${last.D.toFixed(1)}</text>
    <text x="${x(last.d)+6}" y="${y(last.R)+4}" font-size="12" font-weight="700" fill="var(--rep2)">${esc(rN.name.split(" ").slice(-1)[0])} ${last.R.toFixed(1)}</text>
  </svg>`;
}

/* ---------- ratings ---------- */
const RATING_SCORE = r => { r = (r||"").toLowerCase(); const s = r.includes("toss") ? 0 : (r.includes("tilt") ? 1 : r.includes("lean") ? 2 : r.includes("likely") ? 3 : (r.includes("safe")||r.includes("solid")) ? 4 : null);
  if (s == null) return null; return s === 0 ? 0 : (/\bd\b|dem/.test(r) ? s : -s); };
function ratingConsensus(ratings) {
  const s = (ratings||[]).map(x => RATING_SCORE(x.rating)).filter(v => v != null); if (!s.length) return null;
  const avg = s.reduce((a,b)=>a+b,0)/s.length, m = Math.round(avg);
  return m === 0 ? "Toss-up" : `${["","Tilt","Lean","Likely","Safe"][Math.abs(m)]} ${m>0?"D":"R"}`;
}
function ratingStyle(r, textOnly) {
  const s = RATING_SCORE(r); if (s == null) return "";
  const col = s === 0 ? "#a855f7" : s > 0 ? "#3b82f6" : "#ef4444";
  return textOnly ? `color:${col}` : `background:${col}${["","33","44","55","66"][Math.abs(s)]||"33"};border-color:${col};color:${s===0?"#c084fc":s>0?"#93c5fd":"#fca5a5"}`;
}

/* ---------- red / blue map ---------- */
let shiftLayer = null;
const LAYERS = {
  county: [
    {k:"proj_sen", t:"2026 Senate projection (polls + 2024 baseline)", type:"proj"},
    {k:"proj_gov", t:"2026 Governor projection (polls + 2024 baseline)", type:"proj"},
    {k:"pres24", t:"2024 result (President)", type:"margin"},
    {k:"s20_24", t:"Shift 2020 → 2024 (President)", type:"shift", a:"pres20", b:"pres24"},
    {k:"s16_24", t:"Shift 2016 → 2024 (President)", type:"shift", a:"pres16", b:"pres24"},
  ],
  district: [
    {k:"rating", t:"2026 House race ratings", type:"rating"},
    {k:"proj_sen", t:"2026 Senate projection (polls + 2024 Senate baseline)", type:"proj"},
    {k:"proj_gov", t:"2026 Governor projection (polls + 2022 baseline)", type:"proj"},
    {k:"pres24", t:"2024 result (President, new lines)", type:"margin"},
    {k:"sen24", t:"2024 result (Senate: Allred vs Cruz)", type:"margin"},
    {k:"s20_24", t:"Shift 2020 → 2024 (President)", type:"shift", a:"pres20", b:"pres24"},
    {k:"s18_24", t:"Shift 2018 → 2024 (Senate: O'Rourke → Allred)", type:"shift", a:"sen18", b:"sen24"},
  ],
};
function setupShift() {
  $$("#geoSeg button").forEach(b => b.onclick = () => { $$("#geoSeg button").forEach(x=>x.classList.toggle("on",x===b)); STATE.geo = b.dataset.v; fillLayerSel(); drawShift(); });
  $("#layerSel").onchange = e => { STATE.layer = e.target.value; drawShift(); };
  fillLayerSel();
}
function fillLayerSel() {
  const ls = LAYERS[STATE.geo];
  $("#layerSel").innerHTML = ls.map(l => `<option value="${l.k}">${esc(l.t)}</option>`).join("");
  STATE.layer = ls[0].k;
}
// Diverging scale: red (R) ← white → blue (D)
function divColor(v, max) {
  if (v == null || isNaN(v)) return "#555";
  const t = Math.max(-1, Math.min(1, v / max));
  const dark = document.documentElement.dataset.theme === "dark";
  const mid = dark ? [58,52,80] : [240,236,248];
  const blue = [29,78,216], red = [220,38,38];
  const end = t > 0 ? blue : red, k = Math.pow(Math.abs(t), .75);
  const c = mid.map((m,i) => Math.round(m + (end[i]-m)*k));
  return `rgb(${c.join(",")})`;
}
function swingFor(raceKey, base) {
  const r = S.races[raceKey]; const a = r?.polls ? pollAverage(r.polls, false) : null; if (!a) return null;
  return {avg:a.margin, base, swing:a.margin - base};
}
function featValue(layer, rec, geo) {
  if (!rec) return null;
  if (layer.type === "margin") return rec[layer.k]?.margin;
  if (layer.type === "shift") return rec[layer.b] && rec[layer.a] ? rec[layer.b].margin - rec[layer.a].margin : null;
  if (layer.type === "proj") {
    const st = S.static.dres.STATE;
    if (layer.k === "proj_sen") { const baseKey = geo==="county" ? "pres24" : "sen24"; const sw = swingFor("senate", geo==="county" ? st.pres24.margin : st.sen24.margin); return sw && rec[baseKey] ? rec[baseKey].margin + sw.swing : null; }
    if (layer.k === "proj_gov") { const baseKey = geo==="county" ? "pres24" : "gov22"; const sw = swingFor("governor", geo==="county" ? st.pres24.margin : st.gov22.margin); return sw && rec[baseKey] ? rec[baseKey].margin + sw.swing : null; }
  }
  return null;
}
function drawShift() {
  if (shiftLayer) shiftLayer.remove();
  const geo = STATE.geo, layer = LAYERS[geo].find(l => l.k === STATE.layer);
  const gj = geo === "county" ? S.static.cgeo : S.static.dgeo, res = geo === "county" ? S.static.cres : S.static.dres;
  if (!gj || !res) return;
  const key = f => geo === "county" ? f.properties.fips : f.properties.district;
  const max = layer.type === "shift" ? 25 : 50;
  const vals = {};
  gj.features.forEach(f => {
    const k = key(f);
    vals[k] = layer.type === "rating" ? RATING_SCORE(ratingConsensus(S.races["tx"+k]?.ratings)) : featValue(layer, res[k], geo);
  });
  const color = k => layer.type === "rating" ? (vals[k] == null ? "#555" : divColor(vals[k], 4)) : divColor(vals[k], max);
  shiftLayer = L.geoJSON(gj, {
    style: f => ({fillColor:color(key(f)), fillOpacity:.88, color: document.documentElement.dataset.theme==="dark" ? "#0b0d17" : "#ffffff", weight: geo==="county" ? .6 : 1.4}),
    onEachFeature: (f, lyr) => {
      const k = key(f), name = geo === "county" ? `${f.properties.name || res[k]?.name} County` : `TX-${k}`;
      const v = vals[k];
      const label = layer.type === "rating" ? (ratingConsensus(S.races["tx"+k]?.ratings) || "No rating") : layer.type === "shift" ? (v==null?"—":`${v>0?"Bluer":"Redder"} by ${Math.abs(v).toFixed(1)} pts`) : fmtMargin(v);
      lyr.bindTooltip(`<b>${esc(name)}</b><br>${esc(label)}`, {sticky:true});
      lyr.on({ mouseover: () => lyr.setStyle({weight:3, color:"#a855f7"}), mouseout: () => shiftLayer.resetStyle(lyr), click: () => shiftDetail(k, name, geo) });
    },
  }).addTo(shiftMap);
  // scale + stats + note
  const scaleTxt = layer.type === "shift" ? ["Redder", "No change", "Bluer"] : layer.type === "rating" ? ["Safe R", "Toss-up", "Safe D"] : ["R+50", "Even", "D+50"];
  $("#scale").innerHTML = `<b>${esc(layer.t)}</b><div class="bar" style="background:linear-gradient(90deg,${divColor(-max,max)},${divColor(0,max)},${divColor(max,max)})"></div><div class="ends"><span>${scaleTxt[0]}</span><span>${scaleTxt[1]}</span><span>${scaleTxt[2]}</span></div>`;
  const vs = Object.values(vals).filter(v => v != null);
  let stats = "";
  if (layer.type === "shift") stats = `<div class="stat D"><div class="n">${vs.filter(v=>v>0).length}</div><div class="l">${geo==="county"?"counties":"districts"} got bluer</div></div><div class="stat R"><div class="n">${vs.filter(v=>v<0).length}</div><div class="l">got redder</div></div>`;
  else if (layer.type === "rating") stats = `<div class="stat D"><div class="n">${vs.filter(v=>v>0).length}</div><div class="l">lean/likely/safe D seats</div></div><div class="stat R"><div class="n">${vs.filter(v=>v<0).length}</div><div class="l">lean/likely/safe R seats</div></div><div class="stat"><div class="n">${vs.filter(v=>v===0).length}</div><div class="l">toss-ups</div></div><div class="stat"><div class="n">${vs.filter(v=>Math.abs(v)<=2).length}</div><div class="l">competitive (tilt/lean/toss-up)</div></div>`;
  else {
    const flips = layer.type === "proj" ? Object.entries(vals).filter(([k,v]) => v != null && res[k]?.pres24 && Math.sign(v) !== Math.sign(res[k].pres24.margin) && v > 0).length : null;
    stats = `<div class="stat D"><div class="n">${vs.filter(v=>v>0).length}</div><div class="l">${geo==="county"?"counties":"districts"} blue</div></div><div class="stat R"><div class="n">${vs.filter(v=>v<0).length}</div><div class="l">red</div></div>` +
      (flips != null ? `<div class="stat D"><div class="n">${flips}</div><div class="l">would flip blue vs. 2024 (President)</div></div><div class="stat"><div class="n">${vs.filter(v=>Math.abs(v)<5).length}</div><div class="l">within 5 pts</div></div>` : "");
  }
  $("#shiftStats").innerHTML = stats;
  let note = "";
  if (layer.type === "proj") {
    const isSen = layer.k === "proj_sen", sw = swingFor(isSen ? "senate" : "governor", 0);
    const r = S.races[isSen ? "senate" : "governor"];
    const baseTxt = geo === "county" ? "the 2024 presidential result" : isSen ? "the 2024 Senate result" : "the 2022 governor result";
    note = `How this works: takes ${baseTxt} in each ${geo==="county"?"county":"district"} and applies the statewide polling shift (current ${esc(r?.label)} average ${fmtMargin(sw?.avg)}). It's a uniform-swing estimate, not a forecast. Real shifts vary by place (e.g. South Texas moved far more than the suburbs in 2024).`;
  } else if (layer.type === "rating") note = "Consensus of Cook, Sabato, Inside Elections, Decision Desk HQ and others as listed on each race page. Uses the 2025 congressional map in effect for 2026.";
  else note = geo === "county" ? "Official county results. Shift = change in the Democratic-minus-Republican margin." : "Past statewide results re-tallied inside the 2025 district lines (Texas Legislative Council).";
  $("#shiftNote").textContent = note;
}
function shiftDetail(k, name, geo) {
  const rec = (geo === "county" ? S.static.cres : S.static.dres)[k] || {};
  const rows = Object.entries({pres16:"2016 President",pres20:"2020 President",pres24:"2024 President",sen18:"2018 Senate",sen20:"2020 Senate",sen24:"2024 Senate",gov18:"2018 Governor",gov22:"2022 Governor"})
    .filter(([key]) => rec[key]).map(([key,l]) => `<div class="kv"><span>${l}</span><b class="${mClass(rec[key].margin)==="D"?"":""}" style="color:${rec[key].margin>0?"var(--dem2)":"var(--rep2)"}">${fmtMargin(rec[key].margin)}</b></div>`).join("");
  const projS = featValue({type:"proj",k:"proj_sen"}, rec, geo), projG = featValue({type:"proj",k:"proj_gov"}, rec, geo);
  let race = "";
  if (geo === "district" && S.races["tx"+k]) {
    const r = S.races["tx"+k];
    race = `<div style="margin-top:12px" class="hero-k">2026 race</div>` + r.nominees.filter(n=>["D","R"].includes(n.party)).sort((a,b)=>a.party.localeCompare(b.party)).map(n =>
      `<div class="kv" style="cursor:pointer" onclick="window.__lo('${slug(n.name)}')"><span><span class="tag ${n.party}">${n.party}</span> ${esc(n.name)}${n.incumbent?" (inc.)":""}</span><span>loadout →</span></div>`).join("") +
      `<div class="kv"><span>Rating</span><b>${esc(ratingConsensus(r.ratings) || "—")}</b></div>`;
  }
  $("#shiftInfo").innerHTML = `<h4>${esc(name)}</h4>${rows}
    ${projS != null ? `<div class="kv"><span>2026 Senate (projection)</span><b style="color:${projS>0?"var(--dem2)":"var(--rep2)"}">${fmtMargin(projS)}</b></div>` : ""}
    ${projG != null ? `<div class="kv"><span>2026 Governor (projection)</span><b style="color:${projG>0?"var(--dem2)":"var(--rep2)"}">${fmtMargin(projG)}</b></div>` : ""}
    ${race}`;
  if (innerWidth < 900) $("#shiftInfo").scrollIntoView({behavior:"smooth", block:"center"});
}

/* ---------- races grid ---------- */
chipGroup("raceFilter","raceFilter",renderRaces);
function renderRaces() {
  let keys;
  if (STATE.raceFilter === "statewide") keys = STATEWIDE_ORDER.filter(k => S.races[k]);
  else {
    keys = Object.keys(S.races).filter(k => S.races[k].type === "house");
    if (STATE.raceFilter === "competitive") keys = keys.filter(k => { const s = RATING_SCORE(ratingConsensus(S.races[k].ratings)); return s != null && Math.abs(s) <= 3; });
    keys.sort((a,b) => {
      const sa = Math.abs(RATING_SCORE(ratingConsensus(S.races[a].ratings)) ?? 9), sb = Math.abs(RATING_SCORE(ratingConsensus(S.races[b].ratings)) ?? 9);
      return STATE.raceFilter === "competitive" ? sa - sb || +S.races[a].district - +S.races[b].district : +S.races[a].district - +S.races[b].district;
    });
  }
  $("#raceGrid").innerHTML = keys.map(k => {
    const r = S.races[k];
    const d = r.nominees.find(n=>n.party==="D"), rp = r.nominees.find(n=>n.party==="R");
    const a = r.polls ? pollAverage(r.polls, false) : null, cons = ratingConsensus(r.ratings);
    const card = n => { if (!n) return `<div class="cand"><div class="cn muted">No nominee</div></div>`; const c = S.cands[slug(n.name)], f = r.finance?.candidates?.[n.name];
      return `<div class="cand" onclick="window.__lo('${c.id}')">${avatar(c)}<div class="cn">${esc(n.name)}</div><div class="cs">${n.incumbent?"Incumbent · ":""}${f?.raised ? money(f.raised) + " raised" : partyName(n.party)}</div></div>`; };
    const dres = r.type === "house" ? S.static.dres?.[r.district] : null;
    return `<div class="race"><div class="rh"><div><div class="rl">${esc(r.label)}</div>
        <div class="muted" style="font-size:12px">${r.type==="house" && dres ? `2024 Pres: ${fmtMargin(dres.pres24?.margin)} · ` : ""}${a ? `Polls: <b style="color:${a.margin>0?"var(--dem2)":"var(--rep2)"}">${fmtMargin(a.margin)}</b>` : "No polls"}</div></div>
        ${cons ? `<span class="rbadge" style="${ratingStyle(cons)}">${esc(cons)}</span>` : ""}</div>
      <div class="vs">${card(d)}<div class="vs-mid">VS</div>${card(rp)}</div></div>`;
  }).join("") || `<div class="empty">Nothing here.</div>`;
}
})();
