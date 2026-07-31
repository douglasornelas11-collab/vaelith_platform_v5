(()=>{
  const C={projectId:'',revisions:null,impacts:null,planning:null,changes:null,reports:[],bim:null};
  const esc=value=>String(value??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const money=value=>(Number(value)||0).toLocaleString('pt-BR',{style:'currency',currency:'BRL'});
  const fmtDate=value=>value?new Date(value).toLocaleDateString('pt-BR'):'—';
  const pid=()=>window.S?.projectId||S?.projectId||'';
  const req=(url,opt={})=>window.api?window.api(url,opt):api(url,opt);
  const alertError=message=>window.fail?window.fail(message):fail(message);
  const setBusy=(button,busy,label)=>{if(!button)return;button.disabled=busy;if(label)button.textContent=label};
  const staticTemplate=()=>{
    const revisions=document.getElementById('revisions');
    revisions.innerHTML=`<div class="title-row"><div><span class="eyebrow">REVISÕES</span><h2>Controle documental e versões</h2><p>Defina a revisão ativa, aprove documentos e mantenha a rastreabilidade das versões superadas.</p></div><button class="btn" id="reloadRevisions">Atualizar</button></div>
    <div class="metrics"><div class="metric"><span>Arquivos controlados</span><b id="revFiles">0</b></div><div class="metric"><span>Conflitos</span><b id="revConflicts">0</b></div><div class="metric"><span>Aguardando revisão</span><b id="revPending">0</b></div><div class="metric"><span>Disciplinas</span><b id="revGroups">0</b></div></div><div class="complete-stack" id="revisionGroups"></div>`;

    const impacts=document.getElementById('impacts');
    impacts.innerHTML=`<div class="title-row"><div><span class="eyebrow">IMPACTOS</span><h2>Custo, prazo e cadeia de consequência</h2><p>Consolida todos os impactos registrados nas ocorrências e identifica os itens de maior exposição.</p></div><button class="btn" id="reloadImpacts">Atualizar</button></div>
    <div class="metrics"><div class="metric"><span>Registros</span><b id="impactRecords">0</b></div><div class="metric"><span>Ocorrências afetadas</span><b id="impactIssues">0</b></div><div class="metric"><span>Impacto financeiro</span><b id="impactCost">R$ 0</b></div><div class="metric"><span>Impacto em prazo</span><b id="impactDays">0 dias</b></div></div><article class="panel"><h3>Memórias de impacto</h3><div class="complete-stack" id="impactList"></div></article>`;

    const planning=document.getElementById('planning');
    planning.innerHTML=`<div class="title-row"><div><span class="eyebrow">PLANEJAMENTO</span><h2>Cronograma operacional</h2><p>Atividades, responsáveis, criticidade, avanço, restrições e vínculo com ocorrências.</p></div><button class="btn" id="generatePlan">Gerar a partir das ocorrências</button></div>
    <div class="metrics"><div class="metric"><span>Atividades</span><b id="planTotal">0</b></div><div class="metric"><span>Avanço médio</span><b id="planProgress">0%</b></div><div class="metric"><span>Atrasadas</span><b id="planDelayed">0</b></div><div class="metric"><span>Bloqueadas</span><b id="planBlocked">0</b></div></div>
    <article class="panel spaced"><h3>Nova atividade</h3><form id="planningForm" class="complete-form"><input id="planName" placeholder="Nome da atividade" required><input id="planOwner" placeholder="Responsável"><input id="planStart" type="date"><input id="planEnd" type="date"><label class="check-field"><input id="planCritical" type="checkbox"> Caminho crítico</label><button class="btn primary">Adicionar</button></form></article>
    <article class="panel spaced"><h3>Plano de execução</h3><div class="complete-stack" id="planningList"></div></article>`;

    const changes=document.getElementById('changes');
    changes.innerHTML=`<div class="title-row"><div><span class="eyebrow">MUDANÇAS</span><h2>Controle integrado de alterações</h2><p>Solicitação, análise, aprovação, execução, verificação e encerramento com impacto associado.</p></div><button class="btn" id="reloadChanges">Atualizar</button></div>
    <div class="metrics"><div class="metric"><span>Mudanças</span><b id="changeTotal">0</b></div><div class="metric"><span>Em aberto</span><b id="changeOpen">0</b></div><div class="metric"><span>Variação financeira</span><b id="changeCost">R$ 0</b></div><div class="metric"><span>Variação de prazo</span><b id="changeDays">0 dias</b></div></div>
    <article class="panel spaced"><h3>Registrar mudança</h3><form id="changeForm" class="complete-form change-form"><input id="changeTitle" placeholder="Título" required><input id="changeReason" placeholder="Justificativa" required><textarea id="changeDescription" placeholder="Descrição técnica" required></textarea><input id="changeDisciplines" placeholder="Disciplinas: ARQ, EST, HID"><input id="changeCostDelta" type="number" step="0.01" min="0" placeholder="Impacto R$"><input id="changeScheduleDelta" type="number" min="0" placeholder="Impacto em dias"><button class="btn primary">Registrar</button></form></article>
    <article class="panel spaced"><h3>Registro de alterações</h3><div class="complete-stack" id="changeList"></div></article>`;

    const report=document.getElementById('report');
    report.innerHTML=`<div class="title-row"><div><span class="eyebrow">RELATÓRIOS</span><h2>Relatórios controlados</h2><p>Gere snapshots imutáveis com documentos, compatibilização, ocorrências, custo, prazo, mudanças e planejamento.</p></div><div class="top-actions"><button class="btn" id="reportExecutive">Relatório executivo</button><button class="btn primary" id="reportCoordination">Relatório de coordenação</button></div></div>
    <article class="panel"><h3>Relatórios gerados</h3><div class="complete-stack" id="reportHistory"></div></article><article class="panel spaced"><h3>Trilha de auditoria</h3><div class="complete-stack compact-stack" id="auditList"></div></article>`;

    const intelligence=document.getElementById('intelligence');
    intelligence.innerHTML=`<div class="intelligence-page"><div class="ai-mark">✦</div><span class="eyebrow">VAELITH INTELLIGENCE</span><h2>Assistente técnico do empreendimento</h2><p>Respostas fundamentadas exclusivamente nos registros da plataforma, sempre com indicação dos módulos utilizados.</p><div class="ai-prompts"><button data-question="Quais são as ocorrências críticas?">Ocorrências críticas</button><button data-question="O que pode atrasar a entrega?">Riscos de prazo</button><button data-question="Qual é o impacto financeiro?">Impacto financeiro</button><button data-question="Existem conflitos de revisão?">Conflitos de revisão</button></div><form id="intelligenceForm" class="intelligence-form"><input id="intelligenceQuestion" placeholder="Pergunte sobre custo, prazo, revisões, mudanças ou prioridades" required><button class="btn accent">Analisar empreendimento</button></form><article class="ai-answer" id="intelligenceAnswer"><span>Faça uma pergunta para consultar os dados do empreendimento.</span></article></div>`;

    const geometry=document.getElementById('geometry');
    if(geometry){
      const panel=geometry.closest('.panel');
      panel.innerHTML=`<span class="eyebrow">MOTOR BIM GEOMÉTRICO</span><h3>IfcOpenShell Clash Engine</h3><p>Selecione de 2 a 4 modelos IFC. O motor processa a geometria, detecta interseções, colisões ou folgas e pode transformar resultados em ocorrências.</p><div id="bimStatus" class="mini-status">Verificando ambiente...</div><div id="bimFiles" class="bim-files"></div><div class="bim-controls"><select id="bimMode"><option value="intersection">Interseção</option><option value="collision">Colisão</option><option value="clearance">Folga mínima</option></select><input id="bimTolerance" type="number" min="0" max="5" step="0.001" value="0.002" title="Tolerância em metros"><label class="check-field"><input id="bimCreateIssues" type="checkbox"> Criar ocorrências</label><button class="btn accent" id="runBim">Executar BIM</button></div><div id="bimResult" class="complete-stack compact-stack"></div>`;
    }
  };

  async function loadRevisions(){
    if(!pid())return;
    C.revisions=await req(`/api/projects/${pid()}/revisions`);
    document.getElementById('revFiles').textContent=C.revisions.files;
    document.getElementById('revConflicts').textContent=C.revisions.conflicts;
    document.getElementById('revPending').textContent=C.revisions.pendingReview;
    document.getElementById('revGroups').textContent=C.revisions.groups.length;
    const root=document.getElementById('revisionGroups');root.replaceChildren();
    if(!C.revisions.groups.length){root.innerHTML='<div class="empty">Nenhum documento disponível.</div>';return}
    C.revisions.groups.forEach(group=>{
      const card=document.createElement('article');card.className='panel revision-card'+(group.conflict?' warning-card':'');
      card.innerHTML=`<div class="complete-card-head"><div><span class="eyebrow">${esc(group.disciplineCode)}</span><h3>${esc(group.discipline)}</h3></div><span class="badge ${group.conflict?'block':'ready'}">${group.conflict?'CONTROLE PENDENTE':'CONTROLADA'}</span></div><div class="version-list"></div>`;
      const list=card.querySelector('.version-list');
      group.versions.forEach(file=>{
        const row=document.createElement('div');row.className='version-row';
        row.innerHTML=`<div><b>${esc(file.name)}</b><small>${esc(file.revision)} · ${esc(file.controlStatus)}${file.approved?' · aprovado':''}</small></div><div class="row-actions"></div>`;
        const actions=row.querySelector('.row-actions');
        [['Ativar','active',true],['Revisar','review',false],['Arquivar','archived',false]].forEach(([label,status,approved])=>{
          const button=document.createElement('button');button.className='btn';button.textContent=label;
          button.onclick=async()=>{try{setBusy(button,true,'Salvando...');await req(`/api/projects/${pid()}/revisions/${file.id}`,{method:'PATCH',headers:{'content-type':'application/json'},body:JSON.stringify({status,approved,notes:status==='active'?'Revisão liberada como base ativa.':''})});await loadRevisions()}catch(e){alertError(e.message)}finally{setBusy(button,false,label)}};
          actions.append(button);
        });
        list.append(row);
      });
      root.append(card);
    });
  }

  async function loadImpacts(){
    if(!pid())return;
    C.impacts=await req(`/api/projects/${pid()}/impacts`);
    const s=C.impacts.summary;
    document.getElementById('impactRecords').textContent=s.records;
    document.getElementById('impactIssues').textContent=s.issuesAffected;
    document.getElementById('impactCost').textContent=money(s.cost);
    document.getElementById('impactDays').textContent=`${s.days} dias`;
    const root=document.getElementById('impactList');root.replaceChildren();
    if(!C.impacts.records.length){root.innerHTML='<div class="empty">Nenhum impacto registrado nas ocorrências.</div>';return}
    C.impacts.records.forEach(item=>{
      const row=document.createElement('div');row.className='complete-item';
      row.innerHTML=`<div><b>${esc(item.code)} · ${esc(item.title)}</b><small>${esc(item.basis)} · ${esc(item.confidence)}</small></div><div class="impact-values"><strong>${money(item.cost_amount)}</strong><span>${Number(item.schedule_days)||0} dias</span></div>`;
      root.append(row);
    });
  }

  async function loadPlanning(){
    if(!pid())return;
    C.planning=await req(`/api/projects/${pid()}/planning`);
    const s=C.planning.summary;
    document.getElementById('planTotal').textContent=s.total;
    document.getElementById('planProgress').textContent=`${s.averageProgress}%`;
    document.getElementById('planDelayed').textContent=s.delayed;
    document.getElementById('planBlocked').textContent=s.blocked;
    const root=document.getElementById('planningList');root.replaceChildren();
    if(!C.planning.activities.length){root.innerHTML='<div class="empty">Nenhuma atividade cadastrada.</div>';return}
    C.planning.activities.forEach(item=>{
      const row=document.createElement('div');row.className='planning-row'+(item.delayed?' delayed':'');
      row.innerHTML=`<div class="planning-main"><b>${esc(item.code)} · ${esc(item.name)}</b><small>${esc(item.owner||'Sem responsável')} · ${fmtDate(item.start_date)} → ${fmtDate(item.end_date)}${item.critical?' · caminho crítico':''}</small></div><select class="status-select"><option value="not_started">Não iniciada</option><option value="in_progress">Em andamento</option><option value="blocked">Bloqueada</option><option value="completed">Concluída</option><option value="cancelled">Cancelada</option></select><input class="progress-input" type="number" min="0" max="100" value="${Number(item.progress)||0}"><button class="btn save-plan">Salvar</button><button class="btn delete-plan">Excluir</button>`;
      const status=row.querySelector('.status-select');status.value=item.status;
      row.querySelector('.save-plan').onclick=async()=>{try{await req(`/api/projects/${pid()}/planning/activities/${item.id}`,{method:'PATCH',headers:{'content-type':'application/json'},body:JSON.stringify({status:status.value,progress:Number(row.querySelector('.progress-input').value)})});await loadPlanning()}catch(e){alertError(e.message)}};
      row.querySelector('.delete-plan').onclick=async()=>{if(!confirm('Excluir esta atividade?'))return;try{await req(`/api/projects/${pid()}/planning/activities/${item.id}`,{method:'DELETE'});await loadPlanning()}catch(e){alertError(e.message)}};
      root.append(row);
    });
  }

  async function loadChanges(){
    if(!pid())return;
    C.changes=await req(`/api/projects/${pid()}/changes`);
    const s=C.changes.summary;
    document.getElementById('changeTotal').textContent=s.total;
    document.getElementById('changeOpen').textContent=s.open;
    document.getElementById('changeCost').textContent=money(s.costDelta);
    document.getElementById('changeDays').textContent=`${s.scheduleDelta} dias`;
    const root=document.getElementById('changeList');root.replaceChildren();
    if(!C.changes.changes.length){root.innerHTML='<div class="empty">Nenhuma mudança registrada.</div>';return}
    C.changes.changes.forEach(item=>{
      const row=document.createElement('article');row.className='change-card';
      row.innerHTML=`<div class="complete-card-head"><div><span class="eyebrow">${esc(item.code)}</span><h3>${esc(item.title)}</h3></div><select class="change-status"><option value="requested">Solicitada</option><option value="in_analysis">Em análise</option><option value="approved">Aprovada</option><option value="rejected">Rejeitada</option><option value="implemented">Implementada</option><option value="verified">Verificada</option><option value="closed">Encerrada</option></select></div><p>${esc(item.description)}</p><small>${esc(item.reason)} · ${money(item.cost_delta)} · ${Number(item.schedule_delta)||0} dias · ${esc((item.disciplines||[]).join(', '))}</small><div class="row-actions"><input class="change-decision" placeholder="Decisão ou observação" value="${esc(item.decision||'')}"><button class="btn save-change">Atualizar</button></div>`;
      const select=row.querySelector('.change-status');select.value=item.status;
      row.querySelector('.save-change').onclick=async()=>{try{await req(`/api/projects/${pid()}/changes/${item.id}`,{method:'PATCH',headers:{'content-type':'application/json'},body:JSON.stringify({status:select.value,decision:row.querySelector('.change-decision').value})});await loadChanges()}catch(e){alertError(e.message)}};
      root.append(row);
    });
  }

  async function loadReports(){
    if(!pid())return;
    C.reports=await req(`/api/projects/${pid()}/reports`);
    const root=document.getElementById('reportHistory');root.replaceChildren();
    if(!C.reports.length)root.innerHTML='<div class="empty">Nenhum relatório controlado foi gerado.</div>';
    C.reports.forEach(item=>{
      const row=document.createElement('div');row.className='complete-item';
      row.innerHTML=`<div><b>${esc(item.title)}</b><small>${esc(item.report_type)} · ${fmtDate(item.created)} · ${esc(item.created_by)}</small></div><div class="row-actions"><a class="btn" target="_blank" href="/api/projects/${pid()}/reports/${item.id}/html">Visualizar</a><a class="btn primary" href="/api/projects/${pid()}/reports/${item.id}/pdf">PDF</a></div>`;
      root.append(row);
    });
    const audit=await req(`/api/projects/${pid()}/audit`);
    const auditRoot=document.getElementById('auditList');auditRoot.replaceChildren();
    if(!audit.length)auditRoot.innerHTML='<div class="empty">A trilha será formada conforme as operações forem executadas.</div>';
    audit.slice(0,40).forEach(item=>{
      const row=document.createElement('div');row.className='audit-row';
      row.innerHTML=`<b>${esc(item.action)}</b><span>${esc(item.actor)} · ${fmtDate(item.created)} · ${esc(item.entity_type)}</span>`;
      auditRoot.append(row);
    });
  }

  async function loadBim(){
    if(!pid())return;
    const status=await req(`/api/projects/${pid()}/bim/status`);
    C.bim=status;
    const statusEl=document.getElementById('bimStatus');
    statusEl.textContent=status.available?`Motor ativo · IfcOpenShell ${status.version||''}`:'Motor não instalado no ambiente';
    statusEl.className='mini-status '+(status.available?'ready':'fail');
    const files=(S.files||[]).filter(f=>(f.ext||'').toLowerCase()==='.ifc');
    const root=document.getElementById('bimFiles');root.replaceChildren();
    if(files.length<2){root.innerHTML='<div class="empty">Envie pelo menos dois modelos IFC reais.</div>';return}
    files.forEach(file=>{
      const label=document.createElement('label');label.className='bim-file';
      label.innerHTML=`<input type="checkbox" value="${esc(file.id)}"><span><b>${esc(file.name)}</b><small>${esc(file.discipline)} · ${esc(file.revision)} · ${(Number(file.size||0)/1024/1024).toFixed(2)} MB</small></span>`;
      root.append(label);
    });
  }

  async function loadView(view){
    try{
      if(C.projectId!==pid()){C.projectId=pid();C.revisions=C.impacts=C.planning=C.changes=null}
      if(view==='revisions')await loadRevisions();
      if(view==='impacts')await loadImpacts();
      if(view==='planning')await loadPlanning();
      if(view==='changes')await loadChanges();
      if(view==='report')await loadReports();
      if(view==='coordination')await loadBim();
    }catch(e){alertError(e.message)}
  }

  function bind(){
    document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>setTimeout(()=>loadView(button.dataset.view),40)));
    document.getElementById('projectSelect').addEventListener('change',()=>setTimeout(()=>{C.projectId='';const current=document.querySelector('.view.on')?.id;loadView(current);loadBim()},500));
    document.getElementById('reloadRevisions').onclick=()=>loadRevisions().catch(e=>alertError(e.message));
    document.getElementById('reloadImpacts').onclick=()=>loadImpacts().catch(e=>alertError(e.message));
    document.getElementById('reloadChanges').onclick=()=>loadChanges().catch(e=>alertError(e.message));
    document.getElementById('generatePlan').onclick=async()=>{try{const result=await req(`/api/projects/${pid()}/planning/from-issues`,{method:'POST'});alertError(`${result.created} atividade(s) criada(s) a partir das ocorrências.`);await loadPlanning()}catch(e){alertError(e.message)}};
    document.getElementById('planningForm').onsubmit=async event=>{event.preventDefault();try{await req(`/api/projects/${pid()}/planning/activities`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({name:document.getElementById('planName').value,owner:document.getElementById('planOwner').value,startDate:document.getElementById('planStart').value||null,endDate:document.getElementById('planEnd').value||null,critical:document.getElementById('planCritical').checked})});event.target.reset();await loadPlanning()}catch(e){alertError(e.message)}};
    document.getElementById('changeForm').onsubmit=async event=>{event.preventDefault();try{await req(`/api/projects/${pid()}/changes`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({title:document.getElementById('changeTitle').value,reason:document.getElementById('changeReason').value,description:document.getElementById('changeDescription').value,disciplines:document.getElementById('changeDisciplines').value.split(',').map(x=>x.trim().toUpperCase()).filter(Boolean),costDelta:Number(document.getElementById('changeCostDelta').value||0),scheduleDelta:Number(document.getElementById('changeScheduleDelta').value||0)})});event.target.reset();await loadChanges()}catch(e){alertError(e.message)}};
    const generate=async type=>{try{const result=await req(`/api/projects/${pid()}/reports`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({type})});await loadReports();window.open(`/api/projects/${pid()}/reports/${result.id}/html`,'_blank')}catch(e){alertError(e.message)}};
    document.getElementById('reportExecutive').onclick=()=>generate('executive');
    document.getElementById('reportCoordination').onclick=()=>generate('coordination');
    const ask=async question=>{const box=document.getElementById('intelligenceAnswer');box.innerHTML='<span>Analisando os registros...</span>';try{const result=await req(`/api/projects/${pid()}/intelligence/query`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({question})});box.replaceChildren();const p=document.createElement('p');p.textContent=result.answer;box.append(p);const sources=document.createElement('div');sources.className='source-chips';(result.sources||[]).forEach(source=>{const chip=document.createElement('span');chip.textContent=`${source.module}: ${source.label||''}`;sources.append(chip)});box.append(sources);const small=document.createElement('small');small.textContent=result.disclaimer;box.append(small)}catch(e){box.textContent=e.message}};
    document.querySelectorAll('[data-question]').forEach(button=>button.onclick=()=>ask(button.dataset.question));
    document.getElementById('intelligenceForm').onsubmit=event=>{event.preventDefault();ask(document.getElementById('intelligenceQuestion').value)};
    document.getElementById('bimMode').onchange=event=>{document.getElementById('bimTolerance').value=event.target.value==='clearance'?'0.100':'0.002'};
    document.getElementById('runBim').onclick=async()=>{
      const button=document.getElementById('runBim');
      const selected=[...document.querySelectorAll('#bimFiles input:checked')].map(input=>input.value);
      if(selected.length<2||selected.length>4){alertError('Selecione de 2 a 4 modelos IFC.');return}
      const resultBox=document.getElementById('bimResult');resultBox.innerHTML='<div class="empty">Processando geometrias IFC. Esta operação pode levar alguns minutos.</div>';
      try{
        setBusy(button,true,'Processando...');
        const result=await req(`/api/projects/${pid()}/bim/analyze`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({fileIds:selected,mode:document.getElementById('bimMode').value,tolerance:Number(document.getElementById('bimTolerance').value),createIssues:document.getElementById('bimCreateIssues').checked})});
        resultBox.innerHTML=`<div class="bim-summary"><b>${result.summary.clashes} colisão(ões)</b><span>${result.summary.critical} críticas · ${result.summary.shapes} geometrias processadas</span></div>`;
        (result.clashes||[]).slice(0,100).forEach(item=>{const row=document.createElement('div');row.className='complete-item';row.innerHTML=`<div><b>${esc(item.classA)} × ${esc(item.classB)}</b><small>${esc(item.nameA||item.guidA)} ↔ ${esc(item.nameB||item.guidB)} · ${esc(item.fileAName)} / ${esc(item.fileBName)}</small></div><span class="severity ${esc(item.severity)}">${esc(item.severity)}</span>`;resultBox.append(row)});
        if(document.getElementById('bimCreateIssues').checked&&window.loadOperational)await window.loadOperational();
      }catch(e){resultBox.innerHTML=`<div class="empty">${esc(e.message)}</div>`;alertError(e.message)}finally{setBusy(button,false,'Executar BIM')}
    };
  }

  function start(){
    staticTemplate();
    bind();
    const timer=setInterval(()=>{
      if(pid()&&C.projectId!==pid()){C.projectId=pid();clearInterval(timer);loadBim().catch(()=>{})}
    },250);
  }
  start();
})();
