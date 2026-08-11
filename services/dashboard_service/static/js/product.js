const state = { workspace: "default", uploadLimit: 25 * 1024 * 1024, timer: null };
const app = document.querySelector("#app");
const titles = {
  home: ["Home", "Workspace locale"], documents: ["Documenti", "Libreria privata"],
  ask: ["Chiedi", "Ricerca con evidenze"], privacy: ["Privacy", "Controllo del modello"],
  audit: ["Audit", "Tracciabilità AI"], governance: ["Governance", "Retention e legal hold"],
  system: ["Sistema", "Stato dei servizi"]
};

const esc = value => String(value ?? "").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[c]);
const route = () => {
  const parts = location.pathname.split("/").filter(Boolean);
  if (parts[0] === "documents" && parts[1]) return { name: "document", id: decodeURIComponent(parts[1]) };
  const name = parts[0] || "home";
  return { name: titles[name] ? name : "home" };
};
const formatBytes = n => {
  if (n === null || n === undefined) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1048576) return `${(n/1024).toFixed(1)} KB`;
  return `${(n/1048576).toFixed(1)} MB`;
};
const formatDate = value => value ? new Intl.DateTimeFormat("it-IT", {dateStyle:"medium",timeStyle:"short"}).format(new Date(value)) : "—";
const shortId = value => String(value || "").length > 18 ? `${String(value).slice(0,8)}…${String(value).slice(-5)}` : String(value || "—");
const statusBadge = value => {
  const status = String(value || "UNKNOWN").toUpperCase();
  const cls = status === "SUCCEEDED" || status === "READY" ? "good" : status === "FAILED" || status === "ERROR" ? "bad" : "warn";
  return `<span class="badge ${cls}">${esc(status)}</span>`;
};
function toast(message, error=false) {
  const el = document.querySelector("#toast"); el.textContent = message; el.className = `toast show${error ? " error" : ""}`;
  clearTimeout(el._timer); el._timer = setTimeout(() => el.className = "toast", 3600);
}
async function json(url, options={}) {
  const response = await fetch(url, options);
  let body = {}; try { body = await response.json(); } catch (_) {}
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Richiesta non riuscita (${response.status})`);
  return body;
}
function setHead(name) {
  const info = name === "document" ? ["Dettaglio documento", "Libreria privata"] : titles[name];
  document.querySelector("#page-title").textContent = info[0];
  document.querySelector("#page-eyebrow").textContent = info[1];
  document.querySelectorAll("#nav a").forEach(a => a.classList.toggle("active", a.dataset.route === (name === "document" ? "documents" : name)));
}
function errorPanel(error) {
  app.innerHTML = `<section class="card error-panel"><h2>Non riesco a caricare questa vista</h2><p>${esc(error.message)}</p><button class="button" id="retry">Riprova</button></section>`;
  document.querySelector("#retry")?.addEventListener("click", render);
}
function empty(title, text, action="") { return `<div class="empty"><b>${esc(title)}</b>${esc(text)}${action}</div>`; }
function docRows(documents, limit=100) {
  return documents.slice(0,limit).map(d => `<tr data-doc="${esc(d.doc_id)}">
    <td><div class="doc-name"><span class="file-icon">${esc((d.mime_type || "DOC").split("/").pop().slice(0,3).toUpperCase())}</span><span>${esc(d.name)}<small class="subtle">${esc(shortId(d.doc_id))}</small></span></div></td>
    <td>${statusBadge(d.status)}</td><td>${d.chunks || 0}</td><td>${d.pii_detected || 0}</td>
    <td><span class="badge">${esc(d.privacy_policy || "off")}</span></td><td class="subtle">${formatDate(d.updated_at)}</td></tr>`).join("");
}
function bindDocRows() { document.querySelectorAll("[data-doc]").forEach(row => row.addEventListener("click", () => navigate(`/documents/${encodeURIComponent(row.dataset.doc)}`))); }
function navigate(path) { history.pushState({}, "", path); window.scrollTo(0,0); render(); document.querySelector(".sidebar").classList.remove("open"); }

async function home() {
  const [health, docs, privacy] = await Promise.all([
    json("/api/v1/health"), json(`/api/v1/documents?workspace=${encodeURIComponent(state.workspace)}&limit=8`),
    json(`/api/v1/privacy/settings?workspace=${encodeURIComponent(state.workspace)}`)
  ]);
  const services = Object.values(health.services || {}), healthy = services.filter(s => s.status === "healthy").length;
  const model = privacy.model || {}, pii = (docs.documents || []).reduce((sum,d) => sum + (d.pii_detected || 0), 0);
  app.innerHTML = `<section class="hero"><div class="hero-card"><span class="badge">Workspace ${esc(state.workspace)}</span>
    <h2>Conoscenza privata, pronta per essere interrogata.</h2><p>Carica documenti, applica la policy privacy locale e ottieni risposte verificabili con evidenze puntuali.</p>
    <div class="hero-actions"><a class="button secondary" href="/documents">Aggiungi documenti</a><a class="button ghost" href="/ask">Fai una domanda</a></div></div>
    <div class="card quick-card"><div><p class="eyebrow">Privacy attiva</p><h2>${esc(privacy.privacy_policy)}</h2><p>${privacy.privacy_detector === "rizzo_http" ? "Modello Rizzo completo" : "Rizzo leggero regex + checksum"}</p></div><a href="/privacy" class="button secondary">Gestisci privacy →</a></div></section>
    <section class="stats"><div class="card stat"><small>Documenti</small><strong>${docs.total || 0}</strong><em>persistenti nel workspace</em></div>
    <div class="card stat"><small>Evidenze PII</small><strong>${pii}</strong><em>senza valori grezzi</em></div>
    <div class="card stat"><small>Servizi</small><strong>${healthy}/${services.length}</strong><em>${health.overall === "healthy" ? "tutti operativi" : "verifica richiesta"}</em></div>
    <div class="card stat"><small>Modello completo</small><strong>${model.loaded ? "On" : "Off"}</strong><em>${esc((model.state || "non installato").toLowerCase())}</em></div></section>
    <section class="card"><div class="section-head"><div><h2>Documenti recenti</h2><p>Ultime attività del workspace</p></div><a class="button secondary" href="/documents">Vedi tutti</a></div>
    ${(docs.documents || []).length ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Documento</th><th>Stato</th><th>Chunk</th><th>PII</th><th>Policy</th><th>Aggiornato</th></tr></thead><tbody>${docRows(docs.documents,8)}</tbody></table></div>` : empty("Nessun documento", "Carica il primo file per iniziare.", '<br><a class="button" href="/documents">Carica documento</a>')}</section>`;
  bindDocRows(); setGlobal(health.overall === "healthy");
}

async function documents() {
  const docs = await json(`/api/v1/documents?workspace=${encodeURIComponent(state.workspace)}&limit=200`);
  app.innerHTML = `<div class="grid-2"><section class="card"><div class="section-head"><div><h2>Carica un documento</h2><p>PDF, testo o immagine · massimo ${formatBytes(state.uploadLimit)}</p></div></div>
    <label class="dropzone" id="dropzone"><input type="file" id="file"><strong>Trascina qui il file</strong><p>Il documento resta sul tuo stack locale.</p><span class="button secondary">Scegli file</span></label><div id="upload-state"></div></section>
    <section class="card"><h2>Libreria persistente</h2><p>I documenti rimangono disponibili dopo i riavvii. La policy mostrata è quella applicata al momento dell’elaborazione.</p><div class="note">Cambiare policy non riscrive la storia: vale per le nuove elaborazioni e per i reprocess espliciti.</div></section></div>
    <section class="card" style="margin-top:20px"><div class="section-head"><div><h2>Tutti i documenti</h2><p>${docs.total || 0} elementi nel workspace</p></div></div>
    ${(docs.documents || []).length ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Documento</th><th>Stato</th><th>Chunk</th><th>PII</th><th>Policy</th><th>Aggiornato</th></tr></thead><tbody>${docRows(docs.documents)}</tbody></table></div>` : empty("Libreria vuota", "Carica un file dal riquadro qui sopra.")}</section>`;
  bindDocRows();
  const input = document.querySelector("#file"), zone = document.querySelector("#dropzone");
  input.addEventListener("change", () => input.files[0] && upload(input.files[0]));
  ["dragenter","dragover"].forEach(e => zone.addEventListener(e, ev => {ev.preventDefault();zone.classList.add("drag")}));
  ["dragleave","drop"].forEach(e => zone.addEventListener(e, ev => {ev.preventDefault();zone.classList.remove("drag")}));
  zone.addEventListener("drop", ev => ev.dataTransfer.files[0] && upload(ev.dataTransfer.files[0]));
}
async function upload(file) {
  const out = document.querySelector("#upload-state");
  if (file.size > state.uploadLimit) return toast(`File oltre il limite di ${formatBytes(state.uploadLimit)}`, true);
  out.innerHTML = `<div class="note" style="margin-top:14px"><span class="spinner"></span> Invio di ${esc(file.name)}…</div>`;
  const data = new FormData(); data.append("file",file); data.append("tenant",state.workspace);
  try { const result = await json("/api/v1/ingest/file",{method:"POST",body:data}); toast("Documento ricevuto. Elaborazione avviata."); await pollDocument(result.doc_id); navigate(`/documents/${encodeURIComponent(result.doc_id)}`); }
  catch (error) { out.innerHTML = `<div class="note" style="margin-top:14px">${esc(error.message)}</div>`; toast(error.message,true); }
}
async function pollDocument(id) {
  for (let i=0;i<90;i++) { const d=await json(`/api/v1/doc/${encodeURIComponent(id)}?tenant=${encodeURIComponent(state.workspace)}`); if (["SUCCEEDED","FAILED"].includes(d.status)) return d; await new Promise(r=>setTimeout(r,1000)); }
  throw new Error("Elaborazione ancora in corso: il documento apparirà appena pronto.");
}

async function documentDetail(id) {
  const d = await json(`/api/v1/documents/${encodeURIComponent(id)}?workspace=${encodeURIComponent(state.workspace)}`);
  app.innerHTML = `<div class="section-head"><div><a href="/documents" class="subtle">← Documenti</a><h2 style="margin-top:10px">${esc(d.name)}</h2><p>${esc(shortId(d.doc_id))} · ${formatBytes(d.size_bytes)}</p></div>${statusBadge(d.status)}</div>
    <section class="stats"><div class="card stat"><small>Chunk</small><strong>${d.chunks}</strong><em>evidenze ricercabili</em></div><div class="card stat"><small>PII rilevate</small><strong>${d.pii_detected}</strong><em>${esc((d.pii_types||[]).join(", ") || "nessuna")}</em></div><div class="card stat"><small>Policy applicata</small><strong style="font-size:20px">${esc(d.privacy_policy)}</strong><em>${esc(d.privacy_detector || "nessun detector")}${d.privacy_engine_version?` · ${esc(d.privacy_engine_version)}`:""}${d.privacy_engine_source_revision?` · rev ${esc(d.privacy_engine_source_revision.slice(0,8))}`:""}</em></div><div class="card stat"><small>Decisioni</small><strong>${d.decisions_referencing}</strong><em>riferimenti audit</em></div></section>
    <section class="card"><div class="section-head"><div><h2>Evidenze indicizzate</h2><p>Anteprime del testo persistito e interrogabile</p></div><div class="hero-actions"><a class="button secondary" href="/privacy">Rivedi privacy</a><a class="button" href="/ask?doc=${encodeURIComponent(d.doc_id)}">Chiedi su questo documento</a></div></div>
    ${(d.evidence||[]).length ? `<div class="citations">${d.evidence.map(e=>`<button class="citation" data-evidence="${esc(e.chunk_id)}"><strong>Passaggio ${e.chunk_index+1}</strong><small>${e.token_count} token · ${esc(shortId(e.chunk_id))}</small><p>${esc(e.preview.slice(0,260))}</p></button>`).join("")}</div>` : empty("Nessuna evidenza", "L’elaborazione potrebbe essere ancora in corso.")}</section>`;
  document.querySelectorAll("[data-evidence]").forEach(b => b.addEventListener("click",()=>showEvidence(id,b.dataset.evidence)));
}

async function ask() {
  const docs = await json(`/api/v1/documents?workspace=${encodeURIComponent(state.workspace)}&limit=200`);
  const selectedFromQuery = new URLSearchParams(location.search).get("doc");
  app.innerHTML = `<div class="ask-layout"><div class="stack"><section class="card ask-box"><p class="eyebrow">Domanda</p><textarea id="question" placeholder="Che cosa dicono i documenti sulla policy di conservazione?"></textarea><div class="section-head" style="margin:12px 0 0"><span class="subtle">La risposta includerà sempre evidenze apribili.</span><button class="button" id="ask-submit">Cerca evidenze ✦</button></div></section><section class="card" id="answer-card" hidden></section></div>
    <aside class="card"><h3>Ambito documenti</h3><p>Se non selezioni nulla, cerco in tutta la libreria.</p><div class="doc-picker">${(docs.documents||[]).map(d=>`<label class="check-row"><input type="checkbox" value="${esc(d.doc_id)}" ${selectedFromQuery===d.doc_id?"checked":""}><span><strong>${esc(d.name)}</strong><small class="subtle">${d.chunks} passaggi</small></span></label>`).join("") || empty("Nessun documento", "Carica documenti prima di chiedere.")}</div><details style="margin-top:16px"><summary class="subtle">Opzioni avanzate</summary><div class="field" style="margin-top:10px"><label for="top-k">Numero evidenze</label><input id="top-k" type="number" min="1" max="20" value="5"></div></details></aside></div>`;
  document.querySelector("#ask-submit").addEventListener("click", runAsk);
}
async function runAsk() {
  const question = document.querySelector("#question").value.trim(); if (!question) return toast("Scrivi una domanda.",true);
  const button=document.querySelector("#ask-submit"), card=document.querySelector("#answer-card");button.disabled=true;button.innerHTML='<span class="spinner"></span> Ricerca…';card.hidden=false;card.innerHTML='<div class="loading-card"><span class="spinner"></span>Analisi delle evidenze…</div>';
  const docIds=[...document.querySelectorAll('.doc-picker input:checked')].map(i=>i.value);
  try { const result=await json("/api/v1/query",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({tenant:state.workspace,query:question,k:Number(document.querySelector("#top-k").value)||5,doc_ids:docIds.length?docIds:null})});
    card.innerHTML = result.answer ? `<div class="section-head"><div><p class="eyebrow">Risposta basata sulle evidenze</p><h2>Risultato</h2></div><span class="badge">score ${Number(result.score||0).toFixed(3)}</span></div><div class="answer">${esc(result.answer)}</div><h3 style="margin-top:25px">Fonti</h3><div class="citations">${(result.citations||[]).map((c,i)=>`<button class="citation" data-doc-id="${esc(c.doc_id)}" data-chunk-id="${esc(c.chunk_id)}"><strong>${i+1}. ${esc(c.document_name||shortId(c.doc_id))}</strong><small>Passaggio ${Number(c.chunk_index??0)+1}</small><p>${esc(c.preview||"")}</p></button>`).join("")}</div>` : empty("Nessuna evidenza", "Prova a riformulare la domanda o amplia l’ambito.");
    card.querySelectorAll("[data-chunk-id]").forEach(b=>b.addEventListener("click",()=>showEvidence(b.dataset.docId,b.dataset.chunkId)));
    if (result.answer && (result.citations||[]).length) {
      try { await json('/api/v1/decisions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tenant:state.workspace,trace_id:result.trace_id,decision_type:'rag_answer',citations:result.citations,context:{query:question,answer:result.answer,confidence:result.score,model:'alchimista-rag',model_version:'local'},metadata:{source:'product-ask'}})}); }
      catch (auditError) { toast(`Risposta pronta; registrazione audit non riuscita: ${auditError.message}`,true); }
    }
  } catch(error){card.innerHTML=`<h2>Ricerca non riuscita</h2><p>${esc(error.message)}</p>`;}
  finally{button.disabled=false;button.textContent="Cerca evidenze ✦";}
}
async function showEvidence(docId,chunkId){try{const e=await json(`/api/v1/documents/${encodeURIComponent(docId)}/evidence/${encodeURIComponent(chunkId)}?workspace=${encodeURIComponent(state.workspace)}`);document.querySelector("#evidence-content").innerHTML=`<p class="eyebrow">Evidenza verificabile</p><h2>${esc(e.document_name)}</h2><p class="subtle">Passaggio ${e.chunk_index+1} · ${e.token_count} token</p><div class="evidence-text">${esc(e.preview)}</div><p><a class="button secondary" href="/documents/${encodeURIComponent(docId)}">Apri documento</a></p>`;document.querySelector("#evidence-modal").showModal();}catch(error){toast(error.message,true)}}

async function privacy() {
  const [p,docs]=await Promise.all([json(`/api/v1/privacy/settings?workspace=${encodeURIComponent(state.workspace)}`),json(`/api/v1/documents?workspace=${encodeURIComponent(state.workspace)}&limit=100`)]), model=p.model||{};
  const policies=[['off','Off','Nessun rilevamento automatico.'],['detect','Detect','Rileva e registra solo metadati non reversibili.'],['protect_egress','Protect egress','Pseudonimizza prima di chiamate esterne.'],['strict','Strict','Persiste soltanto testo pseudonimizzato.']];
  app.innerHTML=`<section class="card"><div class="section-head"><div><h2>Policy per nuove elaborazioni</h2><p>La cronologia dei documenti già processati non viene modificata.</p></div><button class="button" id="save-privacy">Salva impostazioni</button></div><div class="policy-grid">${policies.map(x=>`<label class="card policy-card ${p.privacy_policy===x[0]?"selected":""}"><input type="radio" name="policy" value="${x[0]}" ${p.privacy_policy===x[0]?"checked":""}><h3>${x[1]}</h3><p>${x[2]}</p></label>`).join("")}</div><label class="check-row" style="margin-top:15px"><input id="mapping" type="checkbox" ${p.privacy_mapping_enabled?"checked":""}><span><strong>Mapping reversibile cifrato</strong><small class="subtle">Le chiavi restano esclusivamente nel privacy service.</small></span></label></section>
    <div class="grid-2" style="margin-top:20px"><section class="card"><div class="section-head"><div><h2>Detector attivo</h2><p>Scegli il motore per le prossime elaborazioni.</p></div></div><label class="check-row"><input type="radio" name="detector" value="rizzo_regex" ${p.privacy_detector==='rizzo_regex'?"checked":""}><span><strong>Rizzo leggero</strong><small class="subtle">Regex + checksum · sempre disponibile</small></span></label><label class="check-row"><input type="radio" name="detector" value="rizzo_http" ${p.privacy_detector==='rizzo_http'?"checked":""} ${!model.loaded?"disabled":""}><span><strong>Rizzo completo</strong><small class="subtle">Modello ML locale + regex · richiede stato READY</small></span></label></section>
    <section class="card" id="model-card">${modelCard(model)}</section></div><section class="card" style="margin-top:20px"><div class="section-head"><div><h2>Evidenza privacy per documento</h2><p>Metadati storici effettivamente applicati, senza mostrare valori originali.</p></div></div>${(docs.documents||[]).length?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Documento</th><th>Policy storica</th><th>Detector</th><th>PII</th><th>Tipi</th></tr></thead><tbody>${docs.documents.map(d=>`<tr data-doc="${esc(d.doc_id)}"><td><strong>${esc(d.name)}</strong></td><td><span class="badge">${esc(d.privacy_policy)}</span></td><td>${esc(d.privacy_detector||'—')}</td><td>${d.pii_detected}</td><td class="subtle">${esc((d.pii_types||[]).join(', ')||'nessuna')}</td></tr>`).join('')}</tbody></table></div>`:empty('Nessuna evidenza privacy','Elabora un documento per visualizzare policy, detector e classi PII.')}</section><section class="grid-3" style="margin-top:20px"><div class="card"><p class="eyebrow">Originale</p><h3>Storage locale trusted</h3><p>Il file sorgente resta nel volume locale.</p></div><div class="card"><p class="eyebrow">Mapping</p><h3>Vault locale cifrato</h3><p>Esportazione mapping: <strong>NO</strong>.</p></div><div class="card"><p class="eyebrow">Egress esterno</p><h3>${p.privacy_policy==='off'||p.privacy_policy==='detect'?'Non trasformato':'Protetto'}</h3><p>Stato derivato dalla policy attiva, non una certificazione legale.</p></div></section><div class="note" style="margin-top:20px">Il download usa solo repository e revisione fissati dal server. Nessun nome modello o percorso arbitrario arriva dal browser.</div>`;
  document.querySelectorAll('.policy-card input').forEach(i=>i.addEventListener('change',()=>{document.querySelectorAll('.policy-card').forEach(c=>c.classList.toggle('selected',c.querySelector('input').checked))}));
  document.querySelector("#save-privacy").addEventListener("click",savePrivacy);
  bindDocRows();
  bindModelActions(); if (["DOWNLOADING","LOADING"].includes(model.state)) schedulePrivacyPoll();
}
function modelCard(m){const busy=["DOWNLOADING","LOADING"].includes(m.state);return `<div class="model-state"><span class="model-orb">✦</span><span><strong>Rizzo PII 0.3B</strong><small>${esc(m.revision||"v1.5.0")} · ${statusBadge(m.state||"NOT_INSTALLED")}</small></span></div>${busy?`<div class="progress-track indeterminate"><span></span></div><p>${esc((m.phase||"operazione in corso").replaceAll("_"," "))}</p>`:""}${m.error?`<div class="note">${esc(m.error)}</div>`:""}<div class="hero-actions">${!m.installed?'<button class="button" data-model="install">Installa modello</button>':''}${m.installed&&!m.loaded?'<button class="button" data-model="load">Carica in memoria</button>':''}${m.loaded?'<button class="button secondary" data-model="unload">Scarica dalla memoria</button>':''}</div><p class="subtle">I pesi restano sul volume locale anche quando il modello è scaricato dalla RAM.</p>`}
function bindModelActions(){document.querySelectorAll('[data-model]').forEach(b=>b.addEventListener('click',async()=>{b.disabled=true;try{await json(`/api/v1/privacy/model/${b.dataset.model}`,{method:'POST'});toast('Operazione avviata.');schedulePrivacyPoll(true)}catch(e){toast(e.message,true);b.disabled=false}}))}
function schedulePrivacyPoll(immediate=false){clearTimeout(state.timer);state.timer=setTimeout(async()=>{if(route().name!=="privacy")return;try{const p=await json(`/api/v1/privacy/settings?workspace=${encodeURIComponent(state.workspace)}`),m=p.model||{};document.querySelector('#model-card').innerHTML=modelCard(m);bindModelActions();if(["DOWNLOADING","LOADING"].includes(m.state))schedulePrivacyPoll();else if(immediate)privacy();}catch(e){toast(e.message,true)}},immediate?400:2400)}
async function savePrivacy(){const button=document.querySelector('#save-privacy');button.disabled=true;try{const body={workspace:state.workspace,privacy_policy:document.querySelector('input[name=policy]:checked').value,privacy_detector:document.querySelector('input[name=detector]:checked').value,privacy_mapping_enabled:document.querySelector('#mapping').checked};await json('/api/v1/privacy/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});toast('Impostazioni privacy salvate.');await privacy()}catch(e){toast(e.message,true)}finally{button.disabled=false}}

async function audit(){const result=await json('/api/v1/decisions/query',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tenant:state.workspace,limit:100})});const items=result.decisions||[];app.innerHTML=`<section class="card"><div class="section-head"><div><h2>Registro delle decisioni AI</h2><p>${result.total||0} record con contesto, privacy e integrità verificabili</p></div></div>${items.length?`<div class="citations">${items.map(x=>{const p=x.metadata?.privacy||{};return `<button class="citation" data-decision="${esc(x.decision_id)}"><strong>${esc(x.model)} · ${esc(x.decision_id)}</strong><small>${formatDate(x.created_at)} · ${(x.context_docs||[]).length} documenti · confidence ${x.confidence??'—'}</small><p>${esc(String(x.output||'').slice(0,220))}</p><span class="badge">${esc(p.privacy_policy||'off')}</span> <span class="badge">${esc(p.privacy_engine||p.decision_privacy_engine||'—')}</span></button>`}).join('')}</div>`:empty('Nessuna decisione registrata','Le risposte prodotte da Ask compariranno qui con le evidenze applicate.')}</section>`;document.querySelectorAll('[data-decision]').forEach(b=>b.addEventListener('click',()=>showDecision(b.dataset.decision)))}
async function showDecision(id){try{const r=await json(`/api/v1/decisions/report?tenant=${encodeURIComponent(state.workspace)}&decision_id=${encodeURIComponent(id)}`),d=r.decision||{},p=d.metadata?.privacy||{};document.querySelector('#evidence-content').innerHTML=`<p class="eyebrow">Decision evidence</p><h2>${esc(d.decision_id||id)}</h2><div class="grid-2"><p><strong>Modello</strong><br><span class="subtle">${esc(d.model)} ${esc(d.model_version||'')}</span></p><p><strong>Timestamp</strong><br><span class="subtle">${formatDate(d.created_at)}</span></p><p><strong>Privacy</strong><br><span class="subtle">${esc(p.privacy_policy||'off')} · ${esc(p.privacy_engine||p.decision_privacy_engine||'—')}</span></p><p><strong>PII</strong><br><span class="subtle">${p.pii_detected||0} · ${esc((p.pii_types||[]).join(', ')||'nessuna')}</span></p><p><strong>Egress protetto</strong><br><span class="subtle">${p.external_payload_pseudonymized||p.decision_payload_pseudonymized?'SÌ':'NO'}</span></p><p><strong>Mapping esportato</strong><br><span class="subtle">${p.mapping_exported?'SÌ':'NO'}</span></p></div><div class="note">SHA-256: ${esc(r.report_hash_sha256||'—')}<br>Firma: ${esc(r.signature_alg||'none')} · ${r.signature?'presente':'non configurata'}</div><h3>Output</h3><div class="evidence-text">${esc(d.output||'')}</div>`;document.querySelector('#evidence-modal').showModal()}catch(e){toast(e.message,true)}}

async function governance(){const [policies,holds]=await Promise.all([json(`/api/v1/admin/retention-policies?tenant=${encodeURIComponent(state.workspace)}`),json(`/api/v1/admin/legal-holds?tenant=${encodeURIComponent(state.workspace)}&active_only=true`)]);app.innerHTML=`<div class="grid-2"><section class="card"><div class="section-head"><div><h2>Retention</h2><p>Conservazione degli artefatti audit</p></div></div><form id="retention" class="form-grid"><div class="field"><label>Tipo artefatto</label><input name="artifact" value="audit_artifacts"></div><div class="field"><label>Giorni</label><input name="days" type="number" min="1" max="3650" value="365"></div><div class="field full"><button class="button">Salva policy</button></div></form><div style="margin-top:18px">${(policies.policies||[]).map(p=>`<div class="check-row"><span>◷</span><span><strong>${esc(p.artifact_type)}</strong><small class="subtle">${p.retain_days} giorni · immutabile ${p.immutable_required?'sì':'no'}</small></span></div>`).join('')||'<p class="subtle">Nessuna policy configurata.</p>'}</div></section><section class="card"><div class="section-head"><div><h2>Legal hold attivi</h2><p>Blocchi di eliminazione espliciti</p></div></div>${(holds.holds||[]).map(h=>`<div class="check-row"><span>⚖</span><span><strong>${esc(h.scope_type)} · ${esc(h.scope_id)}</strong><small class="subtle">${esc(h.reason)} · ${formatDate(h.created_at)}</small></span></div>`).join('')||empty('Nessun legal hold','Non ci sono blocchi di conservazione attivi.')}</section></div><div class="note" style="margin-top:20px">L’enforcement distruttivo resta un’azione amministrativa esplicita e non viene avviato automaticamente da questa schermata.</div>`;document.querySelector('#retention').addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(e.target);try{await json('/api/v1/admin/retention-policies',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tenant:state.workspace,retention_days:Number(f.get('days')),artifact_type:f.get('artifact')})});toast('Policy salvata.');governance()}catch(err){toast(err.message,true)}})}

async function system(){const [health,settings,privacy]=await Promise.all([json('/api/v1/health'),json('/api/settings'),json(`/api/v1/privacy/settings?workspace=${encodeURIComponent(state.workspace)}`)]);const services=health.services||{};app.innerHTML=`<section class="stats"><div class="card stat"><small>Runtime</small><strong>${esc(settings.runtime)}</strong><em>cloud opzionale</em></div><div class="card stat"><small>Auth</small><strong>${esc(settings.auth_mode)}</strong><em>gestita server-side</em></div><div class="card stat"><small>Vault</small><strong>${esc(privacy.vault_key_version||'—')}</strong><em>versione chiave attiva</em></div><div class="card stat"><small>Modello</small><strong>${privacy.model?.loaded?'Ready':'Idle'}</strong><em>${esc(privacy.model?.state||'unavailable')}</em></div></section><section class="card"><div class="section-head"><div><h2>Servizi locali</h2><p>Nessun endpoint o segreto è esposto nell’interfaccia.</p></div><button class="button secondary" id="system-refresh">Aggiorna</button></div><div class="grid-2">${Object.entries(services).map(([name,s])=>`<div class="card"><div class="section-head"><strong>${esc(name)}</strong>${statusBadge(s.status==='healthy'?'READY':s.status)}</div><p>${s.latency_ms!==undefined?`${s.latency_ms} ms`:'Nessuna risposta'}${s.detector?` · ${esc(s.detector)}`:''}</p></div>`).join('')}</div></section><section class="card" style="margin-top:20px"><h2>Configurazione prodotto</h2><div class="grid-3"><p><strong>Workspace</strong><br><span class="subtle">${esc(settings.workspace)}</span></p><p><strong>Privacy</strong><br><span class="subtle">${esc(privacy.privacy_policy)} · ${esc(privacy.privacy_detector)}</span></p><p><strong>Storage</strong><br><span class="subtle">${esc(settings.storage)} · upload ${formatBytes(settings.upload_limit_bytes)}</span></p></div></section><section class="card" style="margin-top:20px"><h2>Strumenti avanzati</h2><p>Le viste tecniche precedenti restano disponibili per diagnosi e amministrazione, separate dal prodotto principale.</p><div class="hero-actions"><a class="button secondary" href="/advanced/monitoring">Monitoring avanzato</a><a class="button secondary" href="/advanced/guide">Guida operativa</a></div></section>`;document.querySelector('#system-refresh').addEventListener('click',system);setGlobal(health.overall==='healthy')}

function setGlobal(ok){document.querySelector('#global-status').classList.toggle('ok',ok)}
async function render(){clearTimeout(state.timer);window.scrollTo(0,0);const r=route();setHead(r.name);app.innerHTML='<div class="loading-card"><span class="spinner"></span>Caricamento…</div>';try{if(r.name==='home')await home();else if(r.name==='documents')await documents();else if(r.name==='document')await documentDetail(r.id);else if(r.name==='ask')await ask();else if(r.name==='privacy')await privacy();else if(r.name==='audit')await audit();else if(r.name==='governance')await governance();else if(r.name==='system')await system();app.focus({preventScroll:true});}catch(error){errorPanel(error)}}
async function init(){if('scrollRestoration' in history)history.scrollRestoration='manual';try{const settings=await json('/api/settings');state.workspace=settings.workspace||'default';state.uploadLimit=settings.upload_limit_bytes||state.uploadLimit;document.querySelector('#workspace-label').textContent=state.workspace}catch(_){}document.body.addEventListener('click',e=>{const a=e.target.closest('a[href^="/"]');if(a&&!a.target&&!a.href.includes('/advanced/')){e.preventDefault();navigate(a.getAttribute('href'))}});document.querySelector('#refresh').addEventListener('click',render);document.querySelector('#menu-button').addEventListener('click',()=>document.querySelector('.sidebar').classList.toggle('open'));document.querySelector('#evidence-modal .modal-close').addEventListener('click',()=>document.querySelector('#evidence-modal').close());window.addEventListener('popstate',render);render()}
init();
