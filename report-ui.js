(()=>{
  const T={
    executive:{name:'Relatório Executivo',desc:'Diretoria, cliente e tomada de decisão: prontidão, riscos, custo, prazo e prioridades.',code:'EXEC'},
    coordination:{name:'Relatório de Compatibilização',desc:'Documentos, revisões, interfaces, compatibilização e resultados BIM/IFC.',code:'COMP'},
    operational:{name:'Relatório Operacional',desc:'Ocorrências, responsáveis, planejamento, impactos e acompanhamento da execução.',code:'OPER'},
    change_control:{name:'Controle de Mudanças',desc:'Alterações, justificativas, aprovações e variações de custo e prazo.',code:'MUD'}
  };
  let selected='executive',loaded='';
  const esc=v=>String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const pid=()=>window.S?.projectId||S?.projectId||'';
  const req=(url,opt={})=>window.api?window.api(url,opt):api(url,opt);
  const failMsg=m=>window.fail?window.fail(m):fail(m);
  const userName=()=>document.getElementById('userName')?.textContent?.trim()||'Equipe técnica';
  const projectName=()=>document.getElementById('projectTitle')?.textContent?.trim()||'Empreendimento';
  const today=()=>{const d=new Date();return `${d.getFullYear()}${String(d.getMonth()+1).padStart(2,'0')}${String(d.getDate()).padStart(2,'0')}`};

  function template(){
    const report=document.getElementById('report');if(!report)return;
    report.innerHTML=`<div class="title-row"><div><span class="eyebrow">RELATÓRIOS PROFISSIONAIS</span><h2>Emissão de documentos controlados</h2><p>Escolha o modelo, defina código e revisão e exporte um PDF com identidade VAELITH, indicadores e rastreabilidade.</p></div><span class="badge ready">PDF CONTROLADO</span></div>
      <div class="report-template-grid" id="reportTemplateGrid"></div>
      <article class="panel spaced professional-report-form"><div><span class="eyebrow">IDENTIFICAÇÃO DO DOCUMENTO</span><h3>Dados da emissão</h3></div>
        <form id="professionalReportForm" class="report-form-grid">
          <label><span>Título</span><input id="reportCustomTitle" placeholder="Título do relatório"></label>
          <label><span>Código do documento</span><input id="reportDocumentCode" required></label>
          <label><span>Revisão</span><input id="reportRevision" value="R00" required></label>
          <label><span>Responsável pela emissão</span><input id="reportPreparedBy" required></label>
          <label class="wide"><span>Observações da emissão</span><textarea id="reportNotes" placeholder="Observações, premissas ou finalidade desta emissão"></textarea></label>
          <label class="report-check"><input id="reportAppendices" type="checkbox" checked> Incluir anexos e decisões registradas</label>
          <button class="btn primary report-generate" id="generateProfessionalReport">Gerar e baixar PDF</button>
        </form>
      </article>
      <article class="panel spaced"><div class="title-row compact"><div><span class="eyebrow">HISTÓRICO</span><h3>Relatórios emitidos</h3></div><button class="btn" id="reloadProfessionalReports">Atualizar</button></div><div class="complete-stack" id="professionalReportHistory"></div></article>`;
    drawTemplates();
    syncForm();
    document.getElementById('professionalReportForm').onsubmit=generate;
    document.getElementById('reloadProfessionalReports').onclick=()=>loadHistory().catch(e=>failMsg(e.message));
  }

  function drawTemplates(){
    const root=document.getElementById('reportTemplateGrid');if(!root)return;root.replaceChildren();
    Object.entries(T).forEach(([id,item])=>{
      const button=document.createElement('button');button.type='button';button.className='report-template-card'+(id===selected?' selected':'');button.dataset.template=id;
      button.innerHTML=`<span>${esc(item.code)}</span><b>${esc(item.name)}</b><small>${esc(item.desc)}</small><i>${id===selected?'MODELO SELECIONADO':'SELECIONAR MODELO'}</i>`;
      button.onclick=()=>{selected=id;drawTemplates();syncForm(false)};root.append(button);
    });
  }

  function syncForm(resetTitle=true){
    const item=T[selected];
    const code=document.getElementById('reportDocumentCode');
    const prepared=document.getElementById('reportPreparedBy');
    const title=document.getElementById('reportCustomTitle');
    if(code)code.value=`VAE-${item.code}-${today()}`;
    if(prepared&&!prepared.value)prepared.value=userName();
    if(title&&(resetTitle||!title.value))title.value=`${item.name} - ${projectName()}`;
  }

  async function generate(event){
    event.preventDefault();if(!pid()){failMsg('Selecione um empreendimento.');return}
    const button=document.getElementById('generateProfessionalReport');
    const body={template:selected,title:document.getElementById('reportCustomTitle').value.trim(),documentCode:document.getElementById('reportDocumentCode').value.trim(),revision:document.getElementById('reportRevision').value.trim(),preparedBy:document.getElementById('reportPreparedBy').value.trim(),notes:document.getElementById('reportNotes').value.trim(),includeAppendices:document.getElementById('reportAppendices').checked};
    try{button.disabled=true;button.textContent='Gerando documento...';const result=await req(`/api/projects/${pid()}/professional-reports`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});await loadHistory();window.location=result.pdfUrl}catch(e){failMsg(e.message)}finally{button.disabled=false;button.textContent='Gerar e baixar PDF'}
  }

  async function loadHistory(){
    if(!pid())return;
    const rows=await req(`/api/projects/${pid()}/reports`);
    const root=document.getElementById('professionalReportHistory');if(!root)return;root.replaceChildren();
    if(!rows.length){root.innerHTML='<div class="empty">Nenhum relatório emitido neste empreendimento.</div>';return}
    const recent=rows.slice(0,30);
    const previews=await Promise.all(recent.map(async row=>{try{return await req(`/api/projects/${pid()}/professional-reports/${row.id}/preview`)}catch{return null}}));
    recent.forEach((row,index)=>{
      const p=previews[index];const isProfessional=!!p?.documentCode;
      const item=document.createElement('div');item.className='professional-report-row';
      item.innerHTML=`<div><span class="eyebrow">${isProfessional?esc((T[p.template]||{}).code||p.template):'LEGADO'}</span><b>${esc(row.title)}</b><small>${esc(p?.documentCode||'Modelo anterior')} · ${esc(p?.revision||'sem revisão')} · ${new Date(row.created).toLocaleString('pt-BR')} · ${esc(row.created_by)}</small></div><div class="row-actions"></div>`;
      const actions=item.querySelector('.row-actions');
      if(isProfessional){const pdf=document.createElement('a');pdf.className='btn primary';pdf.textContent='Baixar PDF';pdf.href=p.pdfUrl;actions.append(pdf)}
      else{const old=document.createElement('a');old.className='btn';old.textContent='PDF antigo';old.href=`/api/projects/${pid()}/reports/${row.id}/pdf`;actions.append(old)}
      root.append(item);
    });
  }

  async function load(){
    if(!pid())return;if(!document.getElementById('professionalReportForm'))template();
    if(loaded!==pid()){loaded=pid();syncForm();}
    await loadHistory();
  }

  function boot(){
    template();
    document.querySelector('[data-view="report"]')?.addEventListener('click',()=>setTimeout(()=>load().catch(e=>failMsg(e.message)),80));
    document.getElementById('projectSelect')?.addEventListener('change',()=>setTimeout(()=>{loaded='';load().catch(()=>{})},650));
  }
  boot();
})();
