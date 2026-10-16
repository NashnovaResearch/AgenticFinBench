'use strict';
const $ = id => document.getElementById(id);
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = n => Number(n).toFixed(2).replace(/\.00$/, '');
async function readJson(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`无法读取 ${path} (${response.status})`);
  return response.json();
}
async function initScores() {
  const data = await readJson('results.json');
  function render() {
    const common = $('score-scope').value === 'common';
    const field = common ? 'common499_new_Q' : 'new_Q';
    const rows = [...data.models].sort((a,b) => b[field]-a[field]);
    $('score-rows').innerHTML = rows.map((m,i) => `<tr><td><span class="rank ${i<3?'top':''}">${String(i+1).padStart(2,'0')}</span></td><td class="model-name">${escapeHtml(m.label)}</td><td><div class="score-cell"><span class="score-value">${m[field].toFixed(2)}</span><span class="score-bar" aria-hidden="true"><span style="width:${m[field]}%"></span></span></div></td><td>${common?499:m.count} / 500</td></tr>`).join('');
    $('score-note').textContent = common ? '全部配置在同一组 499 道题上计算均分；统一排除缺少共同回答的 en120-120。' : '10 组完成 500 题；Trae 与 Dumate 各完成 499 题。可切换共同 499 题进行同题集比较。';
  }
  $('score-scope').addEventListener('change', render); render();
}
async function initQuestions() {
  const questions = await readJson('data/questions.json');
  let filtered = questions, page = 0, selected = questions[0].id, request = 0;
  const perPage = 5, cache = new Map();
  function list() {
    const pages = Math.ceil(filtered.length/perPage);
    $('match-count').textContent = `${filtered.length} 道题目`;
    $('page-label').textContent = pages ? `${page+1} / ${pages}` : '0 / 0';
    $('prev-page').disabled = page === 0;
    $('next-page').disabled = page+1 >= pages;
    $('question-list').innerHTML = filtered.slice(page*perPage, (page+1)*perPage).map(q => `<button class="question-item" data-id="${escapeHtml(q.id)}" aria-pressed="${selected===q.id}"><span>${escapeHtml(q.id)} · ${escapeHtml(q.topic)}</span><strong>${escapeHtml(q.question)}</strong></button>`).join('') || '<p class="error">没有匹配题目，试试其他关键词。</p>';
  }
  function rubricItems(r, type) {
    return r[type].map(item => `<div class="rubric-item ${type}"><div class="rubric-title"><b>${escapeHtml(item.id)} · ${escapeHtml(item.dimension || item.severity || '扣分项')}</b><span>${type==='positive'?'权重 '+fmt(item.weight):'扣分 '+fmt(item.penalty_points)}</span></div><p>${escapeHtml(item.criterion)}</p><details><summary>查看${type==='positive'?'通过条件与边界':'触发与去重规则'}</summary>${(type==='positive' ? [['通过条件',item.pass_condition],['不通过示例',item.fail_anchor],['矛盾处理',item.contradiction_rule],['支持要求',item.support_requirement]] : [['触发条件',item.trigger_rule],['去重组',item.dedup_group],['关联正向项',(item.overlap_positive_ids||[]).join(', ')],['失效正向项',(item.invalidates_positive_ids||[]).join(', ')],['分数上限',item.score_cap]]).filter(([,v])=>v!==null&&v!==undefined&&v!=='').map(([k,v])=>`<p><b>${k}：</b>${escapeHtml(v)}</p>`).join('')}</details></div>`).join('');
  }
  async function select(id) {
    selected=id; list(); const ticket=++request;
    const panel=$('question-detail'); panel.innerHTML='<p>正在载入评分标准…</p>';
    try {
      if(!cache.has(id)) cache.set(id, await readJson(`data/rubrics/${encodeURIComponent(id)}.json`));
      if(ticket!==request) return;
      const r=cache.get(id), q=questions.find(q=>q.id===id);
      panel.innerHTML=`<div class="question-id">${escapeHtml(id)}</div><h3>${escapeHtml(q.question)}</h3><span class="topic">${escapeHtml(q.topic)}</span><div class="rubric-tabs" role="group" aria-label="评分项类型"><button data-rubric="positive" aria-pressed="true">+ 正向项 ${r.positive.length}</button><button data-rubric="negative" aria-pressed="false">− 负向项 ${r.negative.length}</button></div><div id="rubric-items">${rubricItems(r,'positive')}</div><a class="text-link" href="data/rubrics/${encodeURIComponent(id)}.json" download>下载本题完整 rubric ↓</a>`;
      panel.scrollTop=0;
      panel.querySelectorAll('[data-rubric]').forEach(button=>button.addEventListener('click',()=>{
        panel.querySelectorAll('[data-rubric]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));
        $('rubric-items').innerHTML=rubricItems(r,button.dataset.rubric);
      }));
    } catch(error) { if(ticket===request) panel.innerHTML=`<p class="error">${escapeHtml(error.message)}。请刷新后重试。</p>`; }
  }
  function filter() {
    const term=$('question-search').value.trim().toLowerCase(),group=$('question-group').value;
    filtered=questions.filter(q=>(group==='all'||(group==='english')===q.id.startsWith('en120-'))&&`${q.id} ${q.topic} ${q.question}`.toLowerCase().includes(term));
    page=0;
    if(filtered.length) {select(filtered[0].id);} else {request++;list();$('question-detail').innerHTML='<p>请更换搜索词或题集筛选。</p>';}
  }
  $('question-list').addEventListener('click',event=>{const b=event.target.closest('[data-id]');if(b)select(b.dataset.id);});
  $('question-search').addEventListener('input',filter);
  $('question-group').addEventListener('change',filter);
  $('prev-page').addEventListener('click',()=>{page--;list();});
  $('next-page').addEventListener('click',()=>{page++;list();});
  list(); await select(selected);
}
$('copy-command').addEventListener('click',async()=>{
  try {await navigator.clipboard.writeText($('command').textContent);$('copy-command').textContent='已复制 ✓';}
  catch {const range=document.createRange();range.selectNodeContents($('command'));const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);$('copy-command').textContent='请按 Ctrl/Cmd+C';}
});
initScores().catch(error=>{$('score-rows').innerHTML=`<tr><td colspan="4" class="error">${escapeHtml(error.message)}。可下载榜单 JSON 查看。</td></tr>`;});
initQuestions().catch(error=>{$('match-count').textContent='加载失败';$('question-detail').innerHTML=`<p class="error">${escapeHtml(error.message)}。请刷新后重试，或下载完整题库。</p>`;});
