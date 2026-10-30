"use strict";
const $ = id => document.getElementById(id);
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = n => Number(n).toFixed(2).replace(/\.00$/, '');
async function readJson(path) { const r = await fetch(path); if (!r.ok) throw new Error(`Unable to load ${path} (${r.status})`); return r.json(); }
async function initScores() {
 const data=await readJson('paper-results.json');
 const leaders = Object.fromEntries(['q','time_minutes','cost_usd'].map(field=>[field,[...data.models].sort((a,b)=>field==='q'?b[field]-a[field]:a[field]-b[field]).slice(0,3).map(m=>m.rank)]));
 function metric(m,field,digits){
  const place=leaders[field].indexOf(m.rank), value=m[field].toFixed(digits);
  return place===0?`<strong>${value}</strong>`:place>0?`<u>${value}</u>`:value;
 }
 function render(){
  const field=$('score-sort').value;
  const rows=[...data.models].sort((a,b)=>field==='q'?b[field]-a[field]:a[field]-b[field]);
  $('score-rows').innerHTML=rows.map(m=>`<tr class="${m.rank===1?'winner':''}"><td><span class="rank ${m.rank<=3?'top':''}">${m.rank}</span></td><td class="model-name">${escapeHtml(m.model)}</td><td>${escapeHtml(m.harness)}</td><td class="paper-quality">${metric(m,'q',2)}</td><td class="ci">${m.ci[0].toFixed(2)}–${m.ci[1].toFixed(2)}</td><td class="deduction">${m.delta.toFixed(2).replace('-','−')}</td><td>${m.baseline_rank} → ${m.rank}</td><td>${metric(m,'time_minutes',2)}</td><td>${metric(m,'cost_usd',4)}</td></tr>`).join('');
 }
 $('score-sort').addEventListener('change',render);render();
}
async function initQuestions() {
  const questions = await readJson('data/questions.json');
  let filtered = questions, page = 0, selected = questions[0].id, request = 0;
  const perPage = 5, cache = new Map();
  function list() {
    const pages = Math.ceil(filtered.length/perPage);
    $('match-count').textContent = `${filtered.length} ${filtered.length === 1 ? "question" : "questions"}`;
    $('page-label').textContent = pages ? `${page+1} / ${pages}` : '0 / 0';
    $('prev-page').disabled = page === 0;
    $('next-page').disabled = page+1 >= pages;
    $('question-list').innerHTML = filtered.slice(page*perPage, (page+1)*perPage).map(q => `<button class="question-item" data-id="${escapeHtml(q.id)}" aria-pressed="${selected===q.id}"><span>${escapeHtml(q.id)} · ${escapeHtml(q.topic)}</span><strong>${escapeHtml(q.question)}</strong></button>`).join('') || '<p class="error">No matching questions. Try another keyword.</p>';
  }
  function rubricItems(r, type) {
    return r[type].map(item => `<div class="rubric-item ${type}"><div class="rubric-title"><b>${escapeHtml(item.id)} · ${escapeHtml(item.dimension || item.severity || 'Penalty')}</b><span>${type==='positive'?'Weight '+fmt(item.weight):'Penalty '+fmt(item.penalty_points)}</span></div><p>${escapeHtml(item.criterion)}</p><details><summary>View ${type==='positive'?'pass conditions and boundaries':'trigger and deduplication rules'}</summary>${(type==='positive' ? [['Pass condition',item.pass_condition],['Fail example',item.fail_anchor],['Contradiction rule',item.contradiction_rule],['Support requirement',item.support_requirement]] : [['Trigger rule',item.trigger_rule],['Deduplication group',item.dedup_group],['Overlapping positive items',(item.overlap_positive_ids||[]).join(', ')],['Invalidated positive items',(item.invalidates_positive_ids||[]).join(', ')],['Score cap',item.score_cap]]).filter(([,v])=>v!==null&&v!==undefined&&v!=='').map(([k,v])=>`<p><b>${k}：</b>${escapeHtml(v)}</p>`).join('')}</details></div>`).join('');
  }
  async function select(id) {
    selected=id; list(); const ticket=++request;
    const panel=$('question-detail'); panel.innerHTML='<p>Loading rubric…</p>';
    try {
      if(!cache.has(id)) cache.set(id, await readJson(`data/rubrics/${encodeURIComponent(id)}.json`));
      if(ticket!==request) return;
      const r=cache.get(id), q=questions.find(q=>q.id===id);
      panel.innerHTML=`<div class="question-id">${escapeHtml(id)}</div><h3>${escapeHtml(q.question)}</h3><span class="topic">${escapeHtml(q.topic)}</span><div class="rubric-tabs" role="group" aria-label="Rubric type"><button data-rubric="positive" aria-pressed="true">+ Positive ${r.positive.length}</button><button data-rubric="negative" aria-pressed="false">− Negative ${r.negative.length}</button></div><div id="rubric-items">${rubricItems(r,'positive')}</div><a class="text-link" href="data/rubrics/${encodeURIComponent(id)}.json" download>Download question rubric ↓</a>`;
      panel.scrollTop=0;
      panel.querySelectorAll('[data-rubric]').forEach(button=>button.addEventListener('click',()=>{
        panel.querySelectorAll('[data-rubric]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));
        $('rubric-items').innerHTML=rubricItems(r,button.dataset.rubric);
      }));
    } catch(error) { if(ticket===request) panel.innerHTML=`<p class="error">${escapeHtml(error.message)}. Please refresh and try again.</p>`; }
  }
  function filter() {
    const term=$('question-search').value.trim().toLowerCase(),group=$('question-group').value;
    filtered=questions.filter(q=>(group==='all'||(group==='english')===q.id.startsWith('en120-'))&&`${q.id} ${q.topic} ${q.question}`.toLowerCase().includes(term));
    page=0;
    if(filtered.length) {select(filtered[0].id);} else {request++;list();$('question-detail').innerHTML='<p>Try another search term or source batch.</p>';}
  }
  $('question-list').addEventListener('click',event=>{const b=event.target.closest('[data-id]');if(b)select(b.dataset.id);});
  $('question-search').addEventListener('input',filter);
  $('question-group').addEventListener('change',filter);
  $('prev-page').addEventListener('click',()=>{page--;list();});
  $('next-page').addEventListener('click',()=>{page++;list();});
  list(); await select(selected);
}

$('copy-command').addEventListener('click',async()=>{try{await navigator.clipboard.writeText($('command').textContent);$('copy-command').textContent='Copied ✓';}catch{$('copy-command').textContent='Select and copy';const r=document.createRange();r.selectNodeContents($('command'));const s=window.getSelection();s.removeAllRanges();s.addRange(r);}});
const menu=document.querySelector('.menu-toggle');menu.addEventListener('click',()=>{const open=menu.getAttribute('aria-expanded')!=='true';menu.setAttribute('aria-expanded',String(open));$('navigation').classList.toggle('open',open);});
$('navigation').querySelectorAll('a').forEach(a=>a.addEventListener('click',()=>{menu.setAttribute('aria-expanded','false');$('navigation').classList.remove('open');}));
let figureTrigger;const dialog=$('figure-dialog');
document.querySelectorAll('[data-figure]').forEach(b=>b.addEventListener('click',()=>{figureTrigger=b;$('expanded-figure').src=b.dataset.figure;$('expanded-figure').alt=b.querySelector('img').alt;$('figure-caption').textContent=b.dataset.caption;dialog.showModal();document.body.style.overflow='hidden';}));
$('close-figure').addEventListener('click',()=>dialog.close());
dialog.addEventListener('click',e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close();}});
dialog.addEventListener('close',()=>{document.body.style.overflow='';figureTrigger?.focus();});
initScores().catch(e=>{$('score-rows').innerHTML=`<tr><td colspan="9" class="error">${escapeHtml(e.message)}. Download the results JSON above.</td></tr>`;});
initQuestions().catch(e=>{$('match-count').textContent='Unable to load questions';$('question-detail').innerHTML=`<p class="error">${escapeHtml(e.message)}</p>`;});
