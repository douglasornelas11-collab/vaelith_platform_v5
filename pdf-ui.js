(()=>{
  const state={loadedProject:'',data:null};
  const esc=v=>String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const pid=()=>window.S?.projectId||S?.projectId||'';
  const req=(url,opt={})=>window.api?window.api(url,opt):api(url,opt);
  const failMsg=m=>window.fail?window.fail(m):fail(m);

  function ensurePanel(){
    const base=document.getElementById('base');
    if(!base||document.getElementById('pdfIntelligencePanel'))return;
    const table=base.querySelector('table.files');
    const panel=document.createElement('article');
    panel.id='pdfIntelligencePanel';panel.className='panel spaced';
    panel.innerHTML=`<div class="title-row compact"><div><span class="eyebrow">PDF INTELLIGENCE</span><h3>Leitura e comparação de PDFs técnicos</h3><p>Extrai texto e metadados, identifica PDFs escaneados e compara revisões sem confundir PDF 2D com modelo BIM.</p></div><button class="btn" id="reloadPdfAnalysis">Atualizar</button></div>
    <div class="metrics"><div class="metric"><span>PDFs</span><b id="pdfTotal">0</b></div><div class="metric"><span>Analisados</span><b id="pdfAnalyzed">0</b></div><div class="metric"><span>Possível escaneado</span><b id="pdfScanned">0</b></div><div class="metric"><span>Páginas lidas</span><b id="pdfPages">0</b></div></div>
    <div class="complete-stack" id="pdfAnalysisList"></div>
    <div id="pdfCompareBox" class="pdf-compare-box"></div>`;
    table?.parentNode?.insertBefore(panel,table);
    document.getElementById('reloadPdfAnalysis').onclick=()=>load().catch(e=>failMsg(e.message));
  }

  async function analyze(fileId,button){
    try{button.disabled=true;button.textContent='Analisando...';const result=await req(`/api/projects/${pid()}/pdf/${fileId}/analyze`,{method:'POST'});await load();showDetail(result)}catch(e){failMsg(e.message)}finally{button.disabled=false;button.textContent='Analisar'}
  }

  async function detail(fileId){
    try{const result=await req(`/api/projects/${pid()}/pdf/${fileId}`);showDetail(result)}catch(e){failMsg(e.message)}
  }

  function showDetail(item){
    const box=document.getElementById('pdfCompareBox');if(!box)return;
    box.innerHTML=`<div class="complete-card-head"><div><span class="eyebrow">LEITURA DO PDF</span><h3>${esc(item.name||'PDF')}</h3></div><span class="badge ${item.scannedLikely?'block':'ready'}">${item.scannedLikely?'SEM TEXTO EXTRAÍVEL':'TEXTO LIDO'}</span></div>
      <div class="pdf-detail-meta"><span>${Number(item.pages)||0} página(s)</span><span>${Number(item.textPages)||0} com texto</span><span>${Number(item.characters)||0} caracteres</span><span>${esc(item.revision||'sem revisão')}</span></div>
      ${item.scannedLikely?'<p class="panel-note">Este PDF parece ser imagem/escaneado. A plataforma preserva e controla o arquivo, mas não inventa conteúdo; OCR será tratado separadamente.</p>':`<pre class="pdf-preview">${esc(item.preview||item.text||'')}</pre>`}`;
  }

  async function compare(a,b){
    try{
      const result=await req(`/api/projects/${pid()}/pdf/compare`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({fileA:a,fileB:b})});
      const box=document.getElementById('pdfCompareBox');
      box.innerHTML=`<div class="complete-card-head"><div><span class="eyebrow">COMPARAÇÃO DE REVISÕES PDF</span><h3>Similaridade ${result.similarity}%</h3></div><span class="badge">${result.addedCount} adições · ${result.removedCount} remoções</span></div>
      <div class="pdf-diff-grid"><div><h4>Adicionado na revisão mais nova</h4>${(result.added||[]).slice(0,30).map(x=>`<p class="pdf-added">+ ${esc(x)}</p>`).join('')||'<p class="empty">Nenhuma linha adicionada.</p>'}</div><div><h4>Removido da revisão anterior</h4>${(result.removed||[]).slice(0,30).map(x=>`<p class="pdf-removed">− ${esc(x)}</p>`).join('')||'<p class="empty">Nenhuma linha removida.</p>'}</div></div>`;
    }catch(e){failMsg(e.message)}
  }

  function render(){
    ensurePanel();
    const d=state.data||{pdfs:[],total:0,analyzed:0,scannedLikely:0};
    document.getElementById('pdfTotal').textContent=d.total||0;
    document.getElementById('pdfAnalyzed').textContent=d.analyzed||0;
    document.getElementById('pdfScanned').textContent=d.scannedLikely||0;
    document.getElementById('pdfPages').textContent=(d.pdfs||[]).reduce((s,x)=>s+(Number(x.pages)||0),0);
    const root=document.getElementById('pdfAnalysisList');root.replaceChildren();
    if(!d.pdfs?.length){root.innerHTML='<div class="empty">Nenhum PDF enviado neste empreendimento.</div>';return}
    d.pdfs.forEach(item=>{
      const row=document.createElement('div');row.className='complete-item pdf-item';
      row.innerHTML=`<div><b>${esc(item.name)}</b><small>${esc(item.discipline||'Não classificado')} · ${esc(item.revision||'sem revisão')} · ${item.analyzed?`${item.pages} pág. · ${item.characters} caracteres`:'ainda não analisado'}</small></div><div class="row-actions"></div>`;
      const actions=row.querySelector('.row-actions');
      const analyzeBtn=document.createElement('button');analyzeBtn.className='btn';analyzeBtn.textContent=item.analyzed?'Reanalisar':'Analisar';analyzeBtn.onclick=()=>analyze(item.id,analyzeBtn);actions.append(analyzeBtn);
      if(item.analyzed){const open=document.createElement('button');open.className='btn';open.textContent='Ver leitura';open.onclick=()=>detail(item.id);actions.append(open)}
      const peers=(d.pdfs||[]).filter(x=>x.id!==item.id&&x.disciplineCode===item.disciplineCode);
      if(peers.length){const cmp=document.createElement('button');cmp.className='btn';cmp.textContent='Comparar revisão';cmp.onclick=()=>compare(peers[0].id,item.id);actions.append(cmp)}
      root.append(row);
    });
  }

  async function load(){
    ensurePanel();if(!pid())return;
    state.loadedProject=pid();state.data=await req(`/api/projects/${pid()}/pdf`);render();
  }

  function decorateRows(){
    const rows=[...document.querySelectorAll('#fileRows tr')];
    const files=(window.S?.files||S?.files||[]);
    rows.forEach((row,index)=>{
      const file=files[index];if(!file||String(file.ext).toLowerCase()!=='.pdf')return;
      const actions=row.lastElementChild;if(!actions||actions.querySelector('.pdf-inline'))return;
      const btn=document.createElement('button');btn.className='btn pdf-inline';btn.textContent='PDF';btn.title='Analisar conteúdo deste PDF';btn.onclick=()=>analyze(file.id,btn);actions.append(btn);
    });
  }

  function boot(){
    ensurePanel();
    const baseButton=document.querySelector('[data-view="base"]');baseButton?.addEventListener('click',()=>setTimeout(()=>load().catch(()=>{}),80));
    const project=document.getElementById('projectSelect');project?.addEventListener('change',()=>setTimeout(()=>load().catch(()=>{}),650));
    const observer=new MutationObserver(()=>{decorateRows();if(pid()&&state.loadedProject!==pid())load().catch(()=>{})});
    const rows=document.getElementById('fileRows');if(rows)observer.observe(rows,{childList:true,subtree:true});
    setInterval(()=>decorateRows(),1200);
  }
  boot();
})();
