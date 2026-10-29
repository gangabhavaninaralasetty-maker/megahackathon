const $ = (id) => document.getElementById(id);
function getMedicationNames(){ return $("medications").value.split(/\n|,/).map(x=>x.trim()).filter(Boolean); }
function updateMedicationCount(){
 const count=getMedicationNames().length;
 const uniqueCount=new Set(getMedicationNames().map(x=>x.toLowerCase())).size;
 const pairs=uniqueCount*(uniqueCount-1)/2;
 if($("medicine-count")) $("medicine-count").textContent=`${count} / 20 medicine entries`;
 if($("pair-count")) $("pair-count").textContent=`${pairs} unique pairs to check`;
 if($("medicine-count")) $("medicine-count").classList.toggle("text-danger", count>20);
}
$("medications").addEventListener("input", updateMedicationCount);
updateMedicationCount();
$("sample").addEventListener("click", () => { $("medications").value = "Apixaban\nBivalirudin"; $("age").value=70; $("egfr").value=""; $("allergies").value=""; $("diagnoses").value=""; $("pregnancy").value="not_specified"; updateMedicationCount(); });
$("clear").addEventListener("click", () => { $("medications").value=""; updateMedicationCount(); $("diagnoses").value=""; $("allergies").value=""; $("egfr").value=""; $("age").value=25; $("pregnancy").value="not_specified"; $("results").innerHTML='<div class="empty-state"><div class="big-icon">✚</div><h2>Your results will appear here</h2><p>Run the checker to see resolved names, rule matches and alert limitations.</p></div>'; });
$("analyze").addEventListener("click", async () => {
 const medications = getMedicationNames();
 if(medications.length>20){ $("results").innerHTML=`<div class="alert alert-warning">Please enter no more than 20 medicine entries per check.</div>`; return; }
 if(!medications.length){ $("results").innerHTML=`<div class="alert alert-warning">Enter at least one medicine name.</div>`; return; }
 const patient = {age:$("age").value,egfr:$("egfr").value,allergies:$("allergies").value,conditions:$("diagnoses").value,diagnoses:$("diagnoses").value.split(",").map(x=>x.trim()).filter(Boolean),pregnancy_breastfeeding:$("pregnancy").value};
 const btn=$("analyze"); btn.disabled=true; btn.textContent="Checking…";
 try {
  const res=await fetch("/api/analyze",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({medications,patient})});
  const data=await res.json(); if(!res.ok) throw new Error(data.error||"Unable to analyse");
  renderResults(data);
 } catch(e) {$("results").innerHTML=`<div class="alert alert-danger">${escapeHtml(e.message)}</div>`}
 finally {btn.disabled=false;btn.textContent="Check medication list"}
});
function escapeHtml(s){return String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function renderResults(d){
 window.lastMediGuardResult = d;
 const r=d.resolutions.map(x=>`<li><code>${escapeHtml(x.input)}</code> → <strong>${escapeHtml(x.generic_name||"Unresolved")}</strong> <span class="pill">${escapeHtml(x.status)}</span> <span class="meta">confidence ${Math.round((x.confidence||0)*100)}%</span></li>`).join("");
 const alerts=d.alerts.length?d.alerts.map(a=>`<div class="alert-card ${a.severity==="HIGH"||a.severity==="CRITICAL"?"high":"review"}"><div class="d-flex justify-content-between gap-2"><h4>${escapeHtml(a.issue_type.replaceAll("_"," "))}</h4><span class="pill">${escapeHtml(a.severity)}</span></div><p class="mb-1"><strong>Medicines:</strong> ${a.drugs.map(escapeHtml).join(", ")}</p><p class="mb-1">${escapeHtml(a.reason)}</p><p class="mb-1"><strong>Suggested review action:</strong> ${escapeHtml(a.suggested_action)}</p><p class="meta mb-1"><strong>Confidence:</strong> ${escapeHtml(a.confidence)} · <strong>Limitations:</strong> ${escapeHtml(a.limitations)}</p><p class="meta mb-0">Rule: ${escapeHtml(a.rule_id||"supplied matching logic")} · ${a.demo_only ? "Demo-only alert" : "Unvalidated dataset signal"}</p></div>`).join(""):'<div class="alert alert-secondary">No issue was found in the rules that ran on this input. This does not establish that the list is safe.</div>';
 $("results").innerHTML=`<h2>Analysis results</h2><p class="meta">Mode: ${escapeHtml(d.mode)} · Medicines entered: ${d.patient_summary.medication_count} · Resolved entries: ${d.patient_summary.resolved_count}</p><div class="alert alert-warning small">${escapeHtml(d.notice)}</div><h3 class="mt-4">Name resolution</h3><ul>${r||"<li>No medicine names entered.</li>"}</ul><h3 class="mt-4">Prioritised alerts (${d.summary.alert_count})</h3>${alerts}<div class="alert alert-secondary small mt-3">${escapeHtml(d.disclaimer)}</div><div class="mt-3 d-flex gap-2 flex-wrap align-items-center"><label class="small" for="result-language">Explanation language</label><select id="result-language" class="form-select" style="max-width:180px"><option value="en">English</option><option value="te">Telugu (తెలుగు)</option></select><button class="btn btn-outline-primary" id="explain-with-ai">Explain these results with AI</button><button class="btn btn-outline-secondary" id="export-pdf">Download PDF report</button></div><div id="ai-explanation" class="mt-3"></div>`;
 const explainButton = $("explain-with-ai");
 if (explainButton) explainButton.addEventListener("click", explainCurrentResults);
 const pdfButton = $("export-pdf"); if (pdfButton) pdfButton.addEventListener("click", exportCurrentReport);
}

async function explainCurrentResults(){
 const target = $("ai-explanation"); const btn = $("explain-with-ai");
 if (!window.lastMediGuardResult || !target || !btn) return;
 const question = "Explain these screening results in simple language. What do the alerts mean and what should I ask a pharmacist? Do not add new interaction claims.";
 btn.disabled = true; btn.textContent = "Asking local AI…"; target.innerHTML = '<div class="alert alert-secondary">Waiting for local Ollama. The first response may take a little time.</div>';
 try {
  const d = window.lastMediGuardResult;
  const summary = {mode:d.mode, resolutions:d.resolutions, alerts:d.alerts};
  const res = await fetch("/api/assistant", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({question, screening_summary:summary, language:$("result-language")?.value || "en"})});
  const data = await res.json(); if (!res.ok) throw new Error(data.error || "AI explanation failed");
  target.innerHTML = `<div class="alert alert-info"><h4>AI explanation (not verified medical advice)</h4><p style="white-space:pre-wrap">${escapeHtml(data.answer)}</p><hr><p class="small mb-0">${escapeHtml(data.disclaimer)}</p></div>`;
 } catch(e) { target.innerHTML = `<div class="alert alert-danger">${escapeHtml(e.message)}. You can open the AI explainer page to check the connection.</div>`; }
 finally {btn.disabled=false; btn.textContent="Explain these results with AI";}
}

async function exportCurrentReport(){
 const btn=$("export-pdf"); if(!window.lastMediGuardResult || !btn) return;
 btn.disabled=true; const old=btn.textContent; btn.textContent="Preparing PDF…";
 try {
  const response=await fetch("/api/report.pdf",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({result:window.lastMediGuardResult})});
  if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(data.error||"Could not export PDF");}
  const blob=await response.blob(); const url=URL.createObjectURL(blob); const a=document.createElement("a"); a.href=url; a.download="mediguard-screening-summary.pdf"; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
 } catch(e){alert(e.message);} finally{btn.disabled=false;btn.textContent=old;}
}
const voiceMedsButton=$("voice-medicines");
if(voiceMedsButton) voiceMedsButton.addEventListener("click",()=>{
 const SpeechRecognition=window.SpeechRecognition||window.webkitSpeechRecognition; const status=$("checker-voice-status");
 if(!SpeechRecognition){status.textContent="Voice input is not supported in this browser. Try Chrome or type names.";return;}
 const recognition=new SpeechRecognition(); recognition.lang="en-IN"; recognition.interimResults=false; recognition.maxAlternatives=1;
 status.textContent="Listening… say medicine names slowly, with a pause between names.";voiceMedsButton.disabled=true;
 recognition.onresult=(event)=>{const spoken=event.results[0][0].transcript;$("medications").value += ($("medications").value.trim()?"\n":"") + spoken.replace(/,\s*/g,"\n");updateMedicationCount();status.textContent="Captured: "+spoken+". Please verify spelling; medicine names can be misheard.";};
 recognition.onerror=(event)=>{status.textContent="Voice input error: "+event.error+". You can type names instead.";};recognition.onend=()=>{voiceMedsButton.disabled=false;};recognition.start();
});
