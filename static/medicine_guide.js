const q = document.getElementById("medicine-query");
const btn = document.getElementById("medicine-search-btn");
const result = document.getElementById("medicine-result");
function esc(v){return String(v ?? "").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
async function searchMedicine(){
  const name=q.value.trim();
  if(!name){result.innerHTML='<div class="alert alert-warning">Enter a medicine name.</div>';return;}
  btn.disabled=true; btn.textContent="Searching…";
  try{
    const response=await fetch(`/api/medicine-info?q=${encodeURIComponent(name)}`);
    const data=await response.json();
    if(!response.ok) throw new Error(data.error || "Search failed");
    if(data.status==="exact"){
      result.innerHTML=`<div class="alert alert-success"><strong>Exact name match:</strong> ${esc(data.name)}</div>
      <dl class="row small"><dt class="col-4">Database ID</dt><dd class="col-8">${esc(data.database_id || "Not supplied")}</dd>
      <dt class="col-4">Target metadata</dt><dd class="col-8">${esc(data.target || "Not supplied")}</dd>
      <dt class="col-4">Enzyme metadata</dt><dd class="col-8">${esc(data.enzyme || "Not supplied")}</dd></dl>
      <p class="small text-secondary">${esc(data.message)}</p>`;
    } else {
      result.innerHTML=`<div class="alert alert-warning"><strong>${esc(data.status.replaceAll("_"," "))}</strong><p class="mb-1">${esc(data.message)}</p>${data.candidate?`<p class="mb-0">Possible spelling candidate: <strong>${esc(data.candidate)}</strong> (${Math.round((data.confidence||0)*100)}% text similarity; not confirmed)</p>`:""}</div>`;
    }
  }catch(e){result.innerHTML=`<div class="alert alert-danger">${esc(e.message)}</div>`;}
  finally{btn.disabled=false;btn.textContent="Search";}
}
btn.addEventListener("click",searchMedicine);
q.addEventListener("keydown",e=>{if(e.key==="Enter")searchMedicine();});
