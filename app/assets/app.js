/* Cached records only. No model, GPU or external network calls. */
"use strict";
const primaryRecords = JSON.parse(document.getElementById("kiln-data").textContent);
const workspace = JSON.parse(document.getElementById("kiln-state").textContent);
const dryrunRecords = workspace.dryrun_records || [];
const precursors = workspace.precursors || [];
const precursorMap = new Map(precursors.map(p => [p.formula, p]));
const frozen = workspace.frozen_settings || {};
let activeMode = primaryRecords.length ? "primary" : (dryrunRecords.length ? "dryrun" : "primary");
let records = activeMode === "dryrun" ? dryrunRecords : primaryRecords;

const $ = id => document.getElementById(id);
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const text = value => value == null || value === "" ? "Not recorded" : typeof value === "object" ? JSON.stringify(value) : String(value);
const num = value => typeof value === "number" && Number.isFinite(value) ? value.toLocaleString(undefined,{maximumFractionDigits:4}) : "—";
const pct = value => typeof value === "number" ? `${(100 * value).toFixed(1)}%` : "Pending";
const pairName = row => row.precursor_a && row.precursor_b ? `${row.precursor_a} + ${row.precursor_b}` : row.item_id;
const conditionNames = {C1:"Single agent",C2:"Isolated specialists",C3:"Central planner",C4:"Collective"};
const empty = (title,detail) => `<div class="empty"><h3>${esc(title)}</h3><p>${esc(detail)}</p></div>`;
const riskWords = {red:"High risk",amber:"Watch",green:"Go",inconclusive:"Inconclusive"};
const risk = value => `<span class="risk-pill risk-${riskWords[value] ? value : "inconclusive"}">${riskWords[value] || "Risk not recorded"}</span>`;
const flagText = row => row.needs_review ? "Needs review" : "No review flag";
const matches = (row,query) => [row.item_id,row.precursor_a,row.precursor_b,row.run_id,row.cause,row.category].join(" ").toLowerCase().includes((query || "").toLowerCase());
let selected = records[0]?.key;
let timers = [];
let currentStep = -1;
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const storage = {get(key, fallback){try{return JSON.parse(sessionStorage.getItem(key)) ?? fallback;}catch{return fallback;}},set(key,value){try{sessionStorage.setItem(key,JSON.stringify(value));}catch{}}};

function activateTab(name, focus=false){
  document.querySelectorAll("[data-tab]").forEach(button => {
    const active = button.dataset.tab === name;
    button.setAttribute("aria-selected", String(active));button.tabIndex = active ? 0 : -1;
    $(`view-${button.dataset.tab}`).hidden = !active;
    if(active && focus) button.focus();
  });
}
document.querySelectorAll("[data-tab]").forEach(button => {
  button.addEventListener("click",()=>activateTab(button.dataset.tab));
  button.addEventListener("keydown",event=>{
    const names=["overview","ranked","trail","quality"],index=names.indexOf(button.dataset.tab);
    let next;if(event.key==="ArrowRight")next=(index+1)%4;if(event.key==="ArrowLeft")next=(index+3)%4;
    if(event.key==="Home")next=0;if(event.key==="End")next=3;
    if(next!==undefined){event.preventDefault();activateTab(names[next],true);}
  });
});
try{$("theme").value=localStorage.getItem("kiln-theme") || "auto";}catch{}
function setTheme(){const theme=$("theme").value;document.documentElement.dataset.theme=theme;try{localStorage.setItem("kiln-theme",theme);}catch{}}
$("theme").addEventListener("change",setTheme);setTheme();

function updateStatusBanner(){
  $("record-count").textContent = records.length;
  const switcher = $("dataset-switcher");
  if(switcher && dryrunRecords.length){
    switcher.hidden = false;
    switcher.innerHTML = `<button type="button" class="dataset-btn ${activeMode==="primary"?"active":""}" data-mode="primary">H100 / Primary (${primaryRecords.length})</button><button type="button" class="dataset-btn ${activeMode==="dryrun"?"active":""}" data-mode="dryrun">Dev Dry Run (${dryrunRecords.length})</button>`;
    switcher.querySelectorAll("[data-mode]").forEach(btn => btn.addEventListener("click", () => {
      activeMode = btn.dataset.mode;
      records = activeMode === "dryrun" ? dryrunRecords : primaryRecords;
      selected = records[0]?.key;
      updateStatusBanner();renderRanked();renderQueue();renderQuality();
    }));
  }
  const msg = primaryRecords.length
    ? `${primaryRecords.length} recorded assessments loaded. H100 results are shown separately from any legacy exports.`
    : (activeMode === "dryrun" && dryrunRecords.length
      ? `No H100 run records are present in this checkout yet — previewing ${dryrunRecords.length} recorded real-compute development dry-run assessments (C1–C4).`
      : "No H100 run records are present in this checkout. The workspace is ready for the recorded run export.");
  $("data-status").innerHTML = msg + ' <a href="/amendments" target="_blank" rel="noopener">Run amendment</a>' + (workspace.warnings.length ? `<br>${workspace.warnings.map(esc).join("<br>")}` : "");
  const headerKpis = $("header-kpis");
  if(headerKpis){
    const flagged = records.filter(r => r.needs_review).length;
    headerKpis.innerHTML = `<span class="mini-kpi"><strong>${records.length}</strong>records</span><span class="mini-kpi"><strong>${flagged}</strong>flagged</span><span class="mini-kpi"><strong>${precursors.length || 46}</strong>precursors</span>`;
  }
}
updateStatusBanner();


function filteredRanked(){return records.filter(r=>{
  if(!matches(r,$("rank-search").value))return false;
  const condFilter = $("rank-condition-filter")?.value || "all";
  if(condFilter !== "all" && r.condition !== condFilter)return false;
  switch($("rank-filter").value){case "flagged":return !!r.needs_review;case "clear":return !r.needs_review;case "relaxation":return r.requests.some(q=>String(q.tier).includes("relax"));case "need-change":return r.has_need_change;default:return true;}
});}
function renderRanked(){
  const rows=filteredRanked();$("export-csv").disabled=!rows.length;
  const kpiEl = $("ranked-kpis");
  if(kpiEl){
    const flagged = rows.filter(r=>r.needs_review).length;
    const relax = rows.filter(r=>r.requests.some(q=>String(q.tier).includes("relax"))).length;
    const needs = rows.filter(r=>(r.telemetry?.fulfilled_needs || 0) > 0 || r.has_need_change).length;
    kpiEl.innerHTML = `<div class="kpi-card"><span>Matching assessments</span><strong>${rows.length}</strong></div><div class="kpi-card"><span>Needs human review</span><strong>${flagged}</strong></div><div class="kpi-card"><span>Bounded relaxations (30 u)</span><strong>${relax}</strong></div><div class="kpi-card"><span>Agent requests answered</span><strong>${needs}</strong></div>`;
  }
  $("ranked-table").innerHTML=rows.length ? `<table><thead><tr><th>Pair / item</th><th>Condition</th><th>Seed</th><th>Temp</th><th>Kiln proposes</th><th>ΔE (meV/atom)</th><th>Compute</th><th>Risk</th><th>Review</th><th>Source</th></tr></thead><tbody>${rows.map(r=>{const dE=r.telemetry?.dE_ev_per_atom;return `<tr><td><button class="link-button" data-open="${r.key}">${esc(pairName(r))}</button><br><small class="muted">${esc(r.item_id)}</small></td><td><strong>${esc(r.condition || "Not recorded")}</strong> <small class="muted">${esc(conditionNames[r.condition] || "")}</small></td><td>${esc(r.seed ?? "—")}</td><td>${r.temperature_c!=null?`${num(r.temperature_c)} °C`:"—"}</td><td><strong>${esc(text(r.category))}</strong><br><small class="muted">${esc(text(r.cause))}</small></td><td>${typeof dE==="number"?`${num(dE*1000)}`:"—"}</td><td>${num(r.telemetry?.compute_units ?? 0)} u</td><td>${risk(r.risk_after)}</td><td>${flagText(r)}</td><td>${esc(r.source_label)}</td></tr>`;}).join("")}</tbody></table>` : empty("No matching records","Try another filter, or load the recorded run export.");
  $("ranked-table").querySelectorAll("[data-open]").forEach(b=>b.addEventListener("click",()=>{selected=b.dataset.open;$("trail-search").value="";$("condition-filter").value="all";renderQueue();activateTab("trail",true);}));
}
$("rank-search").addEventListener("input",renderRanked);$("rank-filter").addEventListener("change",renderRanked);
$("rank-condition-filter")?.addEventListener("change",renderRanked);

function csvCell(value){let v=typeof value==="object" && value!==null ? JSON.stringify(value) : String(value??"");if(/^[\s]*[=+@-]/.test(v))v="'"+v;return '"'+v.replace(/"/g,'""')+'"';}
$("export-csv").addEventListener("click",()=>{
  const keys=["item_id","precursor_a","precursor_b","condition","seed","category","risk_after","needs_review","cause","fix","run_id","source_label"];
  const csv=[keys.map(csvCell).join(","),...filteredRanked().map(r=>keys.map(k=>csvCell(r[k])).join(","))].join("\r\n");
  const url=URL.createObjectURL(new Blob([csv],{type:"text/csv;charset=utf-8"}));const a=document.createElement("a");a.href=url;a.download="kiln-recorded-results.csv";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});

function valueDisplay(key,value){
  if(value==null)return "Unknown";
  if(typeof value==="number"){
    if(key.includes("ev_per_atom"))return `${num(value*1000)} meV/atom`;
    if(key.endsWith("_c"))return `${num(value)} °C`;
    if(key.endsWith("_h"))return `${num(value)} h`;
    return num(value);
  }
  return text(value);
}
function citation(value){const label=text(value);try{const u=new URL(label);if(["https:","http:"].includes(u.protocol))return `<a href="${esc(u.href)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>`;}catch{}return esc(label);}
function card(a,index,row){
  const claims=Array.isArray(a.claims)?a.claims:[];const values=Object.entries(a.values || {});
  const references=Array.isArray(a.cites)?a.cites:[];const compute=Array.isArray(a.compute_requests)?a.compute_requests:[];
  return `<article class="box artifact-card" id="${row.key}-artifact-${index}" tabindex="-1"><div class="box-header"><h3>${index+1}. ${esc(a.agent || "Specialist")}</h3><span class="stamp stamp-${esc(a.verifier)}">${esc(a.verifier)}${a.verifier==="rejected"?" · dropped from verdict":""}</span></div><div class="box-body"><p class="artifact-summary">${esc(a.summary)}</p><div class="artifact-details"><div><h4>Values & units</h4>${values.length?`<dl class="value-list">${values.map(([k,v])=>`<div><dt>${esc(k.replace(/_ev_per_atom/g," (meV/atom)").replace(/_/g," "))}</dt><dd>${esc(valueDisplay(k,v))}</dd></div>`).join("")}</dl>`:'<p>No numeric evidence recorded.</p>'}</div><div><h4>Claims & falsification</h4>${claims.length?`<ul>${claims.map(c=>`<li>${esc(text(c.statement))}<br><span class="muted">Falsified if: ${esc(text(c.falsified_if))}</span></li>`).join("")}</ul>`:'<p>No falsification condition recorded.</p>'}</div><div><h4>Citations</h4>${references.length?`<ul>${references.map(c=>`<li>${citation(c)}</li>`).join("")}</ul>`:'<p>No citation IDs recorded.</p>'}</div><div><h4>Compute & coordination</h4><p>${compute.length?compute.map(c=>esc(text(c))).join(", "):"No compute request attached."}</p>${a.fulfills_need?`<p>Answers request: ${esc(text(a.fulfills_need))}</p>`:""}${a.verifier_notes?`<p>Verifier: ${esc(text(a.verifier_notes))}</p>`:""}</div></div><p class="artifact-id">${esc(a.artifact_id)}${a.created_at?` · ${esc(a.created_at)}`:""}</p></div></article>`;
}
function clearReplay(){timers.forEach(clearTimeout);timers=[];}
function highlightStep(index){
  const strip=$("trail-content")?.querySelector("[data-replay]");if(!strip)return;
  const segments=[...strip.querySelectorAll(".strip-segment")];
  const cards=[...$("trail-content").querySelectorAll(".artifact-card")];
  segments.forEach((s,i)=>{s.classList.toggle("on", i<=index);s.classList.toggle("active-step", i===index);});
  cards.forEach((c,i)=>c.classList.toggle("active-card", i===index));
  const done = index >= segments.length - 1;
  strip.classList.toggle("complete", done);
  const proposal=$("proposal-outcome");if(proposal)proposal.hidden=!done;
}
function finishReplay(){
  const strip=$("trail-content")?.querySelector("[data-replay]");if(!strip)return;
  const segments=[...strip.querySelectorAll(".strip-segment")];
  currentStep = segments.length - 1;
  segments.forEach(s=>{s.classList.add("on");s.classList.remove("active-step");});
  $("trail-content").querySelectorAll(".artifact-card").forEach(c=>c.classList.remove("active-card"));
  strip.classList.add("complete");strip.setAttribute("aria-busy","false");
  const proposal=$("proposal-outcome");if(proposal)proposal.hidden=false;
  const button=strip.querySelector(".play-trail");if(button)button.textContent="↻ Replay trail";
}
function stepReplay(delta){
  clearReplay();const strip=$("trail-content")?.querySelector("[data-replay]");if(!strip)return;
  const segments=[...strip.querySelectorAll(".strip-segment")];if(!segments.length)return;
  if(currentStep < 0) currentStep = 0;
  else currentStep = Math.max(0, Math.min(segments.length - 1, currentStep + delta));
  highlightStep(currentStep);
  const button=strip.querySelector(".play-trail");if(button)button.textContent=currentStep>=segments.length-1?"↻ Replay trail":"▶ Play trail";
}
function playReplay(){
  clearReplay();const strip=$("trail-content")?.querySelector("[data-replay]");if(!strip)return;
  strip.classList.remove("complete");
  const proposal=$("proposal-outcome");if(proposal)proposal.hidden=true;
  strip.setAttribute("aria-busy","true");
  const segments=[...strip.querySelectorAll(".strip-segment")];
  segments.forEach(s=>{s.classList.remove("on");s.classList.remove("active-step");});
  currentStep = -1;
  if(reducedMotion.matches || !segments.length){finishReplay();return;}
  const btn=strip.querySelector(".play-trail");if(btn)btn.textContent="↻ Restart replay";
  segments.forEach((s,i)=>timers.push(setTimeout(()=>{currentStep=i;highlightStep(i);},i*520+90)));
  timers.push(setTimeout(finishReplay,segments.length*520+160));
}
reducedMotion.addEventListener("change",()=>{if(reducedMotion.matches){clearReplay();finishReplay();}});

function renderTrail(){
  clearReplay();const row=records.find(r=>r.key===selected);
  if(!row){$("trail-content").innerHTML=empty("Ready for the evidence","Choose a recorded assessment to replay its verifier decisions. Missing run files are not replaced with example results.");return;}
  $("trail-content").innerHTML=`<div class="pair-heading"><h2>${esc(pairName(row))}</h2><p>${esc(row.item_id)} · ${esc(row.condition || "Condition not recorded")} / ${esc(conditionNames[row.condition] || "")} · Seed ${esc(row.seed ?? "—")}</p><div class="metadata"><span class="label">${esc(row.source_label)}</span><span class="label">${flagText(row)}</span><span class="label">${row.temperature_c==null?"Temperature not recorded":`${esc(num(row.temperature_c))} °C`}</span>${row.models_disagree?'<span class="risk-pill risk-amber">Models disagree</span>':""}</div></div>${(row.review_flags || []).map(f=>`<div class="warning"><strong>${esc(f.reason || "Review flag")}</strong> · ${esc(f.detail || text(f))}</div>`).join("")}${row.strip_html}<article class="box proposal-outcome" id="proposal-outcome" hidden><div class="box-header"><h3>Kiln proposes: ${esc(text(row.category))}</h3></div><div class="box-body"><h4>Proposed cause</h4><p>${esc(text(row.cause))}</p><h4>Suggested fix</h4><p>${esc(text(row.fix))}</p><p class="box-note">These are recorded recommendations, not validated causes or measured lab outcomes.</p></div></article><h3 class="timeline-heading">Evidence timeline · ${row.artifacts.length} artifacts</h3>${row.artifacts.map((a,i)=>card(a,i,row)).join("") || empty("No artifacts exported","The assessment exists, but its evidence cards were not included in this export.")}<article class="box"><div class="box-header"><h3>Compute used</h3><span class="label">${row.requests.length} requests</span></div><div class="table-wrap"><table><thead><tr><th>Request / tier</th><th>Status</th><th>Units</th><th>GPU seconds</th><th>Recorded category change</th></tr></thead><tbody>${row.requests.map(q=>`<tr><td>${esc(text(q.request_id))}<br><span class="muted">${esc(text(q.tier))}</span></td><td>${esc(text(q.status))}</td><td>${num(q.compute_units)}</td><td>${num(q.gpu_seconds)}</td><td>${q.category_before!=null&&q.category_after!=null?`${esc(q.category_before)} → ${esc(q.category_after)}`:"Not recorded"}</td></tr>`).join("") || '<tr><td colspan="5">No compute requests exported.</td></tr>'}</tbody></table></div></article>`;
  $("trail-content").querySelector(".play-trail")?.addEventListener("click",playReplay);
  $("trail-content").querySelector(".step-prev")?.addEventListener("click",()=>stepReplay(-1));
  $("trail-content").querySelector(".step-next")?.addEventListener("click",()=>stepReplay(1));
  $("trail-content").querySelectorAll(".segment-link").forEach(a=>a.addEventListener("click",event=>{event.preventDefault();const target=$(a.getAttribute("href").slice(1));target?.focus();target?.scrollIntoView({behavior:reducedMotion.matches?"instant":"smooth",block:"start"});}));
  enhanceTrailView(row);
  finishReplay();
}

function enhanceTrailView(row){

  const root = $("trail-content");
  if(!root || !row) return;
  const siblings = records.filter(r => r.item_id === row.item_id);
  const heading = root.querySelector(".pair-heading");
  if(heading && siblings.length > 1){
    const bar = document.createElement("div");
    bar.className = "condition-switcher";
    bar.innerHTML = `<span class="muted" style="font-size:12px">Compare conditions on ${esc(row.item_id)}:</span>` + siblings.map(s => `<button type="button" class="cond-pill ${s.key===row.key?"active":""}" data-switch-key="${s.key}"><strong>${esc(s.condition || "—")}</strong><span>${esc(conditionNames[s.condition] || "")}</span><small class="muted">s${esc(s.seed ?? 0)} · ${esc(text(s.category))}</small></button>`).join("");
    heading.appendChild(bar);
    bar.querySelectorAll("[data-switch-key]").forEach(b => b.addEventListener("click", () => {
      selected = b.dataset.switchKey;
      renderQueue();
    }));
  }
  const tel = row.telemetry || {};
  const maxUnits = Number(frozen.max_compute_units_per_item) || 32;
  const usedUnits = Number(tel.compute_units) || 0;
  const unitPct = Math.min(100, Math.max(2, (usedUnits / maxUnits) * 100));
  const dE = typeof tel.dE_ev_per_atom === "number" ? tel.dE_ev_per_atom * 1000 : null;
  const dEPct = dE != null ? Math.min(100, Math.max(5, ((-dE + 50) / 200) * 100)) : 0;
  const tFurnace = row.temperature_c;
  const tamA = tel.tammann_a_c ?? precursorMap.get(row.precursor_a)?.tammann_c;
  const tamB = tel.tammann_b_c ?? precursorMap.get(row.precursor_b)?.tammann_c;
  const gaugeWrap = document.createElement("div");
  gaugeWrap.className = "telemetry-grid";
  gaugeWrap.innerHTML = `
    <div class="gauge-card">
      <div class="gauge-head"><h4>Thermodynamic driving force (ΔE)</h4><span class="gauge-value">${dE!=null?`${num(dE)} meV/atom`:"Not recorded"}</span></div>
      <div class="gauge-track"><div class="gauge-fill ${dE!=null && dE < -50 ? "fill-green" : ""}" style="width:${dEPct}%"></div></div>
      <div class="gauge-markers"><span>Decisive threshold: −50 meV/atom</span><span>${tel.products?`Products: ${esc(tel.products)}`:(tel.decomp_summary?esc(tel.decomp_summary):"Standard hull check")}</span></div>
    </div>
    <div class="gauge-card">
      <div class="gauge-head"><h4>Furnace vs. Tammann onset (⅔Tₘ)</h4><span class="gauge-value">${tFurnace!=null?`${num(tFurnace)} °C`:"—"}</span></div>
      <div class="gauge-track"><div class="gauge-fill" style="width:${tFurnace!=null?Math.min(100,Math.max(8,(tFurnace/1400)*100)):10}%"></div></div>
      <div class="gauge-markers"><span>${esc(row.precursor_a || "A")} ⅔Tₘ: ${tamA!=null?`${num(tamA)} °C`:"?"}</span><span>${esc(row.precursor_b || "B")} ⅔Tₘ: ${tamB!=null?`${num(tamB)} °C`:"?"}</span></div>
    </div>
    <div class="gauge-card">
      <div class="gauge-head"><h4>Compute budget allocation</h4><span class="gauge-value">${num(usedUnits)} / ${num(maxUnits)} u</span></div>
      <div class="gauge-track"><div class="gauge-fill ${usedUnits > maxUnits ? "fill-red" : ""}" style="width:${unitPct}%"></div></div>
      <div class="gauge-markers"><span>${row.requests.length} requests · ${num(tel.gpu_seconds || 0)} GPU-s</span><span>${tel.fulfilled_needs || 0} need(s) fulfilled</span></div>
    </div>`;
  const stripEl = root.querySelector(".evidence-strip");
  if(stripEl) stripEl.insertAdjacentElement("afterend", gaugeWrap);
  const props = [row.precursor_a, row.precursor_b].map(formula => precursorMap.get(formula)).filter(Boolean);
  if(props.length){
    const sources = props.map(p=>{
      const href = /^https?:\/\//i.test(p.melting_point_source_url || "") ? p.melting_point_source_url : null;
      const source = href ? `<a href="${esc(href)}" target="_blank" rel="noopener">Source</a>` : esc(p.melting_point_source || "Source not recorded");
      const note = p.melting_point_semantics_note ? ` · ${esc(p.melting_point_semantics_note)}` : "";
      const semanticsSource = /^https?:\/\//i.test(p.melting_point_semantics_source || "") ? ` · <a href="${esc(p.melting_point_semantics_source)}" target="_blank" rel="noopener">Melting-point note source</a>` : "";
      return `<li><strong>${esc(p.formula)}</strong>: melting point ${p.melting_point_c!=null?`${num(p.melting_point_c)} °C`:"not recorded"}; ${source}${semanticsSource}${note}</li>`;
    }).join("");
    const notes=document.createElement("article");notes.className="box";notes.innerHTML=`<h3>Precursor sources and melting point notes</h3><ul>${sources}</ul>`;gaugeWrap.insertAdjacentElement("afterend",notes);
  }
  if(siblings.length > 1){
    const matrix = document.createElement("article");
    matrix.className = "box";
    matrix.innerHTML = `<div class="box-header"><h3>Cross-condition comparison on ${esc(pairName(row))}</h3><span class="label">${siblings.length} conditions recorded</span></div><div class="table-wrap"><table><thead><tr><th>Condition</th><th>Proposal</th><th>Cause</th><th>ΔE (meV/atom)</th><th>Tiers used</th><th>Units</th><th>Review</th></tr></thead><tbody>${siblings.map(s=>{const sdE=s.telemetry?.dE_ev_per_atom;return `<tr${s.key===row.key?' style="background:var(--active)"':""}><td><button type="button" class="link-button" data-switch-key="${s.key}">${esc(s.condition)} · ${esc(conditionNames[s.condition] || "")}</button></td><td><strong>${esc(text(s.category))}</strong></td><td>${esc(text(s.cause))}</td><td>${typeof sdE==="number"?num(sdE*1000):"—"}</td><td>${esc((s.telemetry?.tiers || []).join(" → ") || "—")}</td><td>${num(s.telemetry?.compute_units ?? 0)} u</td><td>${flagText(s)}</td></tr>`;}).join("")}</tbody></table></div>`;
    const timelineHeading = root.querySelector(".timeline-heading");
    if(timelineHeading) timelineHeading.insertAdjacentElement("beforebegin", matrix);
    matrix.querySelectorAll("[data-switch-key]").forEach(b => b.addEventListener("click", () => {
      selected = b.dataset.switchKey;
      renderQueue();
    }));
  }
}

}
function renderQueue(){
  const rows=records.filter(r=>matches(r,$("trail-search").value) && ($("condition-filter").value==="all" || r.condition===$("condition-filter").value));
  if(!rows.some(r=>r.key===selected))selected=rows[0]?.key;
  $("queue-count").textContent=rows.length;
  $("record-list").innerHTML=rows.map(r=>`<button class="record-choice ${r.key===selected?"selected":""}" data-key="${r.key}" aria-pressed="${r.key===selected}"><strong>${esc(pairName(r))}</strong><small>${esc(r.condition || "Unknown condition")} · Seed ${esc(r.seed ?? "—")} · ${flagText(r)}</small></button>`).join("") || '<p class="muted">No matching records.</p>';
  $("record-list").querySelectorAll("[data-key]").forEach(b=>b.addEventListener("click",()=>{selected=b.dataset.key;renderQueue();$("record-list").querySelector(`[data-key="${selected}"]`)?.focus();}));renderTrail();
}
$("trail-search").addEventListener("input",renderQueue);$("condition-filter").addEventListener("change",renderQueue);

function renderQuality(){
  const main=records.filter(r=>r.source_kind==="h100"),runs=[...new Set(main.map(r=>r.run_id))];
  $("comparison-table").innerHTML=runs.length?`<table><thead><tr><th>Condition / seed</th><th>Records</th><th>Unflagged coverage</th><th>Accuracy</th><th>AUROC</th><th>Brier</th></tr></thead><tbody>${runs.map(id=>{const rows=main.filter(r=>r.run_id===id),r=rows[0],e=workspace.evaluations.find(e=>e.run_id===id)?.metrics;return `<tr><td>${esc(r.condition)} · Seed ${esc(r.seed)}<br><small class="muted">${esc(id)}</small></td><td>${rows.length}</td><td>${pct(rows.filter(r=>!r.needs_review).length/rows.length)}</td><td>${pct(e?.four_class_accuracy)}</td><td>${e?num(e.auroc):"Pending"}</td><td>${e?num(e.brier):"Pending"}</td></tr>`;}).join("")}</tbody></table>`:empty("Evaluation pending","Matching H100 prediction and evaluator exports will populate this comparison. No results are inferred.");
  const groups=new Map();main.forEach(r=>r.requests.forEach(q=>{const k=`${r.condition} / seed ${r.seed} / ${q.tier}`;if(!groups.has(k))groups.set(k,{n:0,units:0,known:0,failed:0});const g=groups.get(k);g.n++;if(typeof q.compute_units==="number"){g.units+=q.compute_units;g.known++;}if(["error","failed"].includes(q.status))g.failed++;}));
  $("allocation-table").innerHTML=groups.size?`<table><thead><tr><th>Condition / tier</th><th>Requests</th><th>Charged units</th><th>Failed</th></tr></thead><tbody>${[...groups].map(([k,g])=>`<tr><td>${esc(k)}</td><td>${g.n}</td><td>${g.known===g.n?num(g.units):"Incomplete"}</td><td>${g.failed}</td></tr>`).join("")}</tbody></table>`:empty("No compute log loaded","Charged units and failures will appear here from recorded requests.");
  const p=workspace.provenance;$("provenance-content").innerHTML=[['Protocol digest',p.protocol_sha256],['H100 prediction manifest digest',p.prediction_sha256],['Local hash-post receipt',p.prediction_posted_at]].map(([label,value])=>`<div class="provenance-row"><strong>${label}</strong><p class="hash">${esc(value || "Not available in this checkout")}</p></div>`).join("")+'<p>A local receipt is not independent confirmation of a public hash post. See the amendment for the adopted run and invalidated GB10 run.</p>';
}
let callIndex=0;
const calls=workspace.call_pairs || [],answers=storage.get("kiln-calls-v1",{});
const callKey=p=>JSON.stringify([p.split,p.id,p.precursors,p.temp_c,p.hours,p.real_reacts]);
function renderCall(){
  const p=calls[callIndex];if(!p){$("call-content").innerHTML=empty("Awaiting published pairs",workspace.scoring_released?"The release files are present. A scorer-approved pair export is still needed for this exercise.":"Development pairs can be used before scoring. Held-out outcomes stay unavailable until the prediction-hash and comparison files are present.");return;}
  $("call-scope").textContent=p.label;const saved=answers[callKey(p)];const entries=calls.map(c=>answers[callKey(c)]).filter(a=>a&&typeof a.correct==="boolean");
  const precChips = (p.precursors || []).map(f => {
    const info = precursorMap.get(f);
    if(!info) return `<div class="precursor-mini-card"><strong>${esc(f)}</strong></div>`;
    return `<div class="precursor-mini-card"><strong>${esc(f)}</strong> · Tₘ ${info.melting_point_c!=null?`${num(info.melting_point_c)} °C`:"?"} · ⅔Tₘ ${info.tammann_c!=null?`${num(info.tammann_c)} °C`:"?"}${info.decomposes_at_c!=null?` · decomp ${num(info.decomposes_at_c)} °C (${esc(info.decomposition_product || "")})`:""}</div>`;
  }).join("");
  const stripBlock = saved && p.strip_html ? `<div class="call-strip-wrap">${p.strip_html}</div>` : "";
  $("call-content").innerHTML=`<div class="call-header-bar"><div><h3>${esc(p.precursors.join(" + "))}</h3><p>${p.temp_c==null?"Temperature not recorded":`${esc(num(p.temp_c))} °C`} · ${p.hours==null?"Dwell not recorded":`${esc(num(p.hours))} h`}</p></div><span class="label">Pair ${callIndex + 1} of ${calls.length}</span></div><div class="call-precursor-chips">${precChips}</div>${saved?`<div class="call-results"><div>Your call<strong>${saved.guess?"Reacts":"Does not react"}</strong></div><div>Kiln proposes<strong>${p.kiln_reacts?"Reacts":"Does not react"}</strong></div><div>Recorded lab result<strong>${p.real_reacts?"Reacts":"Does not react"}</strong></div></div>${stripBlock}<p><strong>Kiln’s reason:</strong> ${esc(text(p.kiln_cause))}</p><p class="call-score">Session score: ${entries.filter(a=>a.correct).length} / ${entries.length} correct. Each pair counts once.</p><div class="call-actions"><button class="button" id="prev-call">‹ Previous pair</button><button class="button button-primary" id="next-call">Next pair ›</button></div>`:'<p class="call-score">Make a call, then compare it with the recorded proposal and lab result.</p><div class="call-actions"><button class="button button-primary" data-guess="yes">Reacts</button><button class="button" data-guess="no">Does not react</button></div>'}`;
  const callStrip = $("call-content").querySelector("[data-replay]");
  if(callStrip){
    callStrip.querySelectorAll(".strip-segment").forEach(s=>s.classList.add("on"));
    callStrip.classList.add("complete");
    callStrip.querySelector(".play-trail")?.addEventListener("click", () => {
      const segs=[...callStrip.querySelectorAll(".strip-segment")];
      callStrip.classList.remove("complete");
      segs.forEach(s=>s.classList.remove("on"));
      if(reducedMotion.matches){segs.forEach(s=>s.classList.add("on"));callStrip.classList.add("complete");return;}
      segs.forEach((s,i)=>setTimeout(()=>s.classList.add("on"), i*450+80));
      setTimeout(()=>callStrip.classList.add("complete"), segs.length*450+140);
    });
  }
  $("call-content").querySelectorAll("[data-guess]").forEach(b=>b.addEventListener("click",()=>{const guess=b.dataset.guess==="yes";answers[callKey(p)]={guess,correct:guess===p.real_reacts};storage.set("kiln-calls-v1",answers);renderCall();}));
  $("prev-call")?.addEventListener("click",()=>{callIndex=(callIndex+calls.length-1)%calls.length;renderCall();});
  $("next-call")?.addEventListener("click",()=>{callIndex=(callIndex+1)%calls.length;renderCall();});
}
function renderOverview(){
  const budgetEl = $("frozen-budget-summary");
  if(budgetEl){
    const prices = frozen.tier_prices || {cached_lookup:0.1, decomposition_reeval:0.2, single_point:1.0, bounded_relaxation:30.0};
    budgetEl.innerHTML = Object.entries(prices).map(([k,v]) => `<span class="budget-chip"><span>${esc(k.replace(/_/g," "))}</span><code>${num(v)} u</code></span>`).join("") + `<span class="budget-chip"><span>Per-item cap</span><code>${num(frozen.max_compute_units_per_item ?? 32)} u</code></span>`;
  }
  const tableEl = $("precursor-table");
  if(!tableEl) return;
  const q = ($("precursor-search")?.value || "").toLowerCase().trim();
  const rows = precursors.filter(p => !q || [p.formula, p.decomposition_product, p.melting_point_source, p.melting_point_semantics, p.melting_point_semantics_note].join(" ").toLowerCase().includes(q));
  tableEl.innerHTML = rows.length ? `<table><thead><tr><th>Precursor</th><th>Reported Tₘ (°C)</th><th>Tammann ⅔Tₘ (°C)</th><th>Decomposes at (°C)</th><th>Decomp product</th><th>Melting semantics &amp; caution</th><th>Source</th></tr></thead><tbody>${rows.map(p=>`<tr><td><strong>${esc(p.formula)}</strong></td><td>${p.melting_point_c!=null?`${num(p.melting_point_c)} °C`:"Unknown"}</td><td><strong>${p.tammann_c!=null?`${num(p.tammann_c)} °C`:"—"}</strong></td><td>${p.decomposes_at_c!=null?`${num(p.decomposes_at_c)} °C`:"—"}</td><td>${esc(p.decomposition_product || "—")}</td><td>${p.melting_point_semantics==="possible_decomposition_or_dehydration"?`<span class="risk-pill risk-amber" title="${esc(p.melting_point_semantics_note || "")}">Apparent melt / decomp caution</span>`:`<span class="label">As reported</span>`}</td><td><small class="muted">${esc(p.melting_point_source || "—")}</small></td></tr>`).join("")}</tbody></table>` : empty("No matching precursors","Try searching for another chemical formula or decomposition product.");
}
$("precursor-search")?.addEventListener("input", renderOverview);

document.addEventListener("keydown", event => {
  if(["INPUT","SELECT","TEXTAREA"].includes(document.activeElement?.tagName) || event.metaKey || event.ctrlKey || event.altKey) return;
  if(!$("view-trail").hidden){
    if(event.key === " " && document.activeElement?.tagName !== "BUTTON"){event.preventDefault();playReplay();}
    else if(event.key === "["){event.preventDefault();stepReplay(-1);}
    else if(event.key === "]"){event.preventDefault();stepReplay(1);}
    else if(event.key === "j" || event.key === "k"){
      const items = [...$("record-list").querySelectorAll("[data-select]")];
      const idx = items.findIndex(b => b.dataset.select === selected);
      if(items.length){
        const nextIdx = event.key === "j" ? (idx + 1) % items.length : (idx - 1 + items.length) % items.length;
        selected = items[nextIdx].dataset.select;
        renderQueue();
      }
    }
  }
});

renderOverview();renderRanked();renderQueue();renderQuality();renderCall();
