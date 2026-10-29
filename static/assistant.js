const el = (id) => document.getElementById(id);
const log = el("chat-log");
function esc(s){return String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function addMessage(role, text){const div=document.createElement("div");div.className="chat-message "+(role==="user"?"user-message":"assistant-message");div.innerHTML=`<strong>${role==="user"?"You":"MediGuard AI"}</strong><p class="mb-0">${esc(text)}</p>`;log.appendChild(div);log.scrollTop=log.scrollHeight;}
async function checkStatus(){const badge=el("ollama-status");try{const r=await fetch("/api/ollama-status");const d=await r.json();if(!r.ok)throw new Error();badge.className="badge "+(d.model_available?"text-bg-success":"text-bg-warning");badge.textContent=d.model_available?"Ollama connected · model ready":"Ollama connected · model missing";}catch{badge.className="badge text-bg-danger";badge.textContent="Ollama not reachable";}}
checkStatus();
el("ask-ai").addEventListener("click",async()=>{const q=el("question").value.trim();if(!q)return;addMessage("user",q);el("question").value="";el("assistant-error").classList.add("d-none");const btn=el("ask-ai");btn.disabled=true;btn.textContent="Generating…";const waiting=document.createElement("div");waiting.className="chat-message assistant-message";waiting.innerHTML="<strong>MediGuard AI</strong><p class=\"mb-0\">Thinking…</p>";log.appendChild(waiting);log.scrollTop=log.scrollHeight;try{const r=await fetch("/api/assistant",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({question:q, language:el("answer-language").value})});const d=await r.json();if(!r.ok)throw new Error(d.error||"Could not get a response");waiting.remove();addMessage("assistant",d.answer+"\n\n"+d.disclaimer);}catch(e){waiting.remove();const err=el("assistant-error");err.textContent=e.message;err.classList.remove("d-none");}finally{btn.disabled=false;btn.textContent="Ask AI";}});
el("question").addEventListener("keydown",e=>{if((e.metaKey||e.ctrlKey)&&e.key==="Enter")el("ask-ai").click();});
el("clear-chat").addEventListener("click",()=>{log.innerHTML="";addMessage("assistant","I can explain general terms and help interpret the checker’s displayed alerts. I cannot verify every medicine or recommend a dose.");});

// Browser speech recognition; review medicine names and transcripts before sending.
const voiceButton = el("voice-question");
if (voiceButton) voiceButton.addEventListener("click", () => {
 const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
 const status = el("voice-status");
 if (!SpeechRecognition) { status.textContent = "Voice input is not supported in this browser. Try Chrome, or type your question."; return; }
 const recognition = new SpeechRecognition();
 recognition.lang = el("answer-language").value === "te" ? "te-IN" : "en-IN";
 recognition.interimResults = false; recognition.maxAlternatives = 1;
 status.textContent = "Listening… speak now."; voiceButton.disabled = true;
 recognition.onresult = (event) => { const transcript = event.results[0][0].transcript; const q = el("question"); q.value = (q.value ? q.value + " " : "") + transcript; status.textContent = "Voice captured. Review the text before sending."; };
 recognition.onerror = (event) => { status.textContent = "Voice input error: " + event.error + ". You can type instead."; };
 recognition.onend = () => { voiceButton.disabled = false; };
 recognition.start();
});
