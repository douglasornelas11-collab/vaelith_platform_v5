from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import Response


CSS = r'''
:root{--bg:#080b09;--bg2:#0d120e;--panel:#121913;--panel2:#172019;--line:rgba(255,255,255,.09);--line2:rgba(255,255,255,.16);--text:#f4f7f3;--muted:#95a199;--accent:#c8ff3d;--danger:#ff6b6b;--warn:#f2b350;--ok:#50cf89;--shadow:0 24px 70px rgba(0,0,0,.30);--radius:18px;color-scheme:dark}
*{box-sizing:border-box}
html,body{width:100%;height:100%;margin:0;overflow:hidden}
body{background:#080b09;color:var(--text);font-family:"Segoe UI Variable Text","Segoe UI Variable","Segoe UI",Arial,sans-serif;font-size:14px;line-height:1.55;-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
button,input,select,textarea{font:inherit}
button{cursor:pointer}
.shell{width:100%;height:100vh;height:100dvh;display:grid;grid-template-columns:286px minmax(0,1fr);overflow:hidden}
.side{height:100%;min-height:0;display:grid;grid-template-rows:auto auto minmax(0,1fr) auto;overflow:hidden;padding:18px 14px 14px;background:radial-gradient(circle at 18% 0%,rgba(200,255,61,.09),transparent 25%),#090c0a;border-right:1px solid var(--line);box-shadow:12px 0 34px rgba(0,0,0,.18);z-index:30}
.brand{display:flex;align-items:center;gap:13px;padding:2px 8px 16px;color:#fff;text-decoration:none;border-bottom:1px solid var(--line)}
.brand svg{width:40px;height:40px;flex:none;color:var(--accent);filter:drop-shadow(0 0 14px rgba(200,255,61,.18))}
.brand strong{display:block;font-size:16px;line-height:1.1;letter-spacing:.15em}
.brand small{display:block;margin-top:4px;color:#738078;font-size:8px;line-height:1;letter-spacing:.28em}
.project-pick{min-width:0;margin:12px 0 8px;padding:10px 11px 11px;overflow:hidden;border:1px solid var(--line);border-radius:13px;background:linear-gradient(145deg,rgba(255,255,255,.055),rgba(255,255,255,.02))}
.project-pick span{display:block;margin-bottom:6px;color:#79867d;font-size:8px;line-height:1.2;letter-spacing:.16em;text-transform:uppercase;font-weight:800}
.project-pick select{display:block;width:100%;min-width:0;max-width:100%;height:34px;margin:0;padding:0 26px 0 0;overflow:hidden;border:0;outline:0;background:transparent;color:#fff;white-space:nowrap;text-overflow:ellipsis;font-size:11px;line-height:1.2;font-weight:750}
.project-pick option{background:#fff;color:#111}
.nav{min-width:0;min-height:0;display:block;overflow-x:hidden;overflow-y:auto;padding:2px 4px 20px 0;overscroll-behavior:contain;scrollbar-gutter:stable;scrollbar-width:thin;scrollbar-color:#3b473d transparent}
.nav::-webkit-scrollbar{width:7px}.nav::-webkit-scrollbar-thumb{background:#3b473d;border-radius:10px}
.nav-group{display:block;margin:14px 10px 6px;padding-top:3px;color:#68756c;font-size:8px;line-height:1;letter-spacing:.2em;font-weight:900}
.nav button{display:block;width:100%;min-width:0;min-height:39px;margin:2px 0;padding:0 13px;overflow:hidden;border:0;border-radius:10px;background:transparent;color:#98a39b;text-align:left;white-space:nowrap;text-overflow:ellipsis;font-size:12px;line-height:1.2;font-weight:750;transition:.16s ease}
.nav button:hover{background:rgba(255,255,255,.05);color:#fff}
.nav button.on{background:linear-gradient(90deg,rgba(200,255,61,.15),rgba(200,255,61,.035));color:#fff;box-shadow:inset 3px 0 var(--accent)}
.user{min-width:0;margin:0;padding:12px 8px 0;background:#090c0a;border-top:1px solid var(--line);color:#8f9a92}
.user b,.user span{display:block;max-width:100%;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}.user b{color:#fff}.user span{font-size:10px}
.main{width:100%;height:100%;min-height:0;overflow-x:hidden;overflow-y:auto;overscroll-behavior:contain;background:radial-gradient(circle at 86% -8%,rgba(200,255,61,.085),transparent 27%),linear-gradient(145deg,#0a0e0b,#101611 58%,#090c0a)}
.main::-webkit-scrollbar{width:10px}.main::-webkit-scrollbar-thumb{background:#374239;border-radius:10px;border:2px solid #0b100c}
.top{min-height:92px;position:sticky;top:0;z-index:20;display:flex;align-items:center;justify-content:space-between;gap:24px;padding:15px 32px;background:rgba(9,13,10,.9);border-bottom:1px solid var(--line);backdrop-filter:blur(22px)}
.top>div:first-child{min-width:0}.top-kicker,.eyebrow{display:block;color:var(--accent);font-size:8px;line-height:1.2;letter-spacing:.19em;font-weight:900}
.top h1{max-width:900px;margin:4px 0 0;overflow:hidden;color:#fff;white-space:nowrap;text-overflow:ellipsis;font-size:20px;line-height:1.15;letter-spacing:-.02em;font-weight:760}
.top p{margin:5px 0 0;color:var(--muted);font-size:10px;line-height:1.35}
.top-actions{display:flex;gap:9px;flex:none}
.btn{min-height:40px;padding:0 15px;border:1px solid var(--line2);border-radius:10px;background:rgba(255,255,255,.045);color:var(--text);font-weight:800;transition:.16s ease}
.btn:hover{transform:translateY(-1px);border-color:rgba(200,255,61,.45)}
.btn.primary,.btn.accent{background:var(--accent);border-color:var(--accent);color:#10140f;box-shadow:0 12px 26px rgba(143,213,27,.14)}
.btn.accent{width:100%;margin-top:13px}.btn.ghost{width:100%;margin-top:10px;background:transparent}
.content{width:100%;max-width:1640px;margin:0 auto;padding:30px 32px 72px}
.error{display:none;margin-bottom:14px;padding:11px 13px;border:1px solid rgba(255,107,107,.35);border-radius:10px;background:rgba(255,107,107,.08);color:#ffabab}.error.show{display:block}
.view{display:none;min-width:0}.view.on{display:block;height:auto;overflow:visible;animation:fade .2s ease}@keyframes fade{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
.overview-hero{min-height:252px;position:relative;display:grid;grid-template-columns:minmax(0,1fr) 230px;align-items:end;gap:30px;overflow:hidden;padding:34px;border:1px solid rgba(200,255,61,.18);border-radius:26px;background:linear-gradient(120deg,rgba(200,255,61,.035),transparent 42%),linear-gradient(135deg,#172019,#111713 58%,#1b261d);box-shadow:var(--shadow)}
.overview-hero:before{content:"";position:absolute;right:-90px;top:-180px;width:430px;height:430px;border-radius:50%;background:radial-gradient(circle,rgba(200,255,61,.18),transparent 65%)}
.overview-hero>div{position:relative;z-index:1;min-width:0}.overview-hero h2{max-width:820px;margin:12px 0 10px;color:#fff;font-size:39px;line-height:1.06;letter-spacing:-.045em;font-weight:760}.overview-hero p{max-width:720px;margin:0;color:#b3bdb5;font-size:14px;line-height:1.65}
.hero-state{min-width:0;display:flex;flex-direction:column;align-items:flex-end;justify-content:center;gap:8px;padding:20px;border:1px solid var(--line);border-radius:18px;background:rgba(6,10,7,.48);text-align:right}.hero-state span{display:inline-flex;max-width:100%;padding:6px 9px;border:1px solid var(--line2);border-radius:999px;color:#d8dfd9;font-size:8px;line-height:1.2;font-weight:900;white-space:nowrap}.hero-state b{display:block;margin:0;color:var(--accent);font-size:46px;line-height:.95;letter-spacing:-.05em;font-weight:780}.hero-state small{display:block;color:var(--muted);font-size:10px;line-height:1.25}
.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:13px;margin:18px 0}.metric{min-width:0;min-height:128px;display:flex;flex-direction:column;justify-content:center;padding:18px;overflow:hidden;border:1px solid var(--line);border-radius:16px;background:linear-gradient(145deg,rgba(255,255,255,.064),rgba(255,255,255,.025));box-shadow:0 14px 40px rgba(0,0,0,.12)}.metric.dark{border-color:rgba(200,255,61,.28);background:linear-gradient(145deg,rgba(200,255,61,.18),rgba(200,255,61,.045))}.metric span{display:block;color:var(--muted);font-size:9px;line-height:1.2;letter-spacing:.13em;text-transform:uppercase;font-weight:800}.metric b{display:block;margin-top:11px;overflow:hidden;color:#fff;white-space:nowrap;text-overflow:ellipsis;font-size:29px;line-height:1.05;letter-spacing:-.04em;font-weight:760}.metric small{display:block;margin-top:6px;color:#829087;font-size:11px;line-height:1.25}
.dashboard-grid{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(340px,.72fr);gap:14px;align-items:start}.dashboard-grid.second{grid-template-columns:repeat(2,minmax(0,1fr));margin-top:14px}.dashboard-grid>*,.grid>*,.metrics>*{min-width:0}
.panel{min-width:0;padding:21px;overflow:hidden;border:1px solid var(--line);border-radius:var(--radius);background:linear-gradient(145deg,rgba(255,255,255,.058),rgba(255,255,255,.023));box-shadow:0 18px 50px rgba(0,0,0,.14)}.panel.large{min-height:386px}.panel.spaced{margin-top:14px}.panel h3{margin:4px 0 5px;color:#fff;font-size:17px;line-height:1.25;font-weight:750}.panel p{margin:0;color:var(--muted);font-size:13px;line-height:1.6}.panel-title,.title-row{display:flex;align-items:flex-end;justify-content:space-between;gap:18px}.title-row{margin-bottom:20px}.title-row.compact{align-items:center;margin-bottom:8px}.title-row h2{margin:4px 0 0;color:#fff;font-size:31px;line-height:1.1;letter-spacing:-.04em}.title-row p{margin:6px 0 0;color:var(--muted)}
.link-btn{min-height:34px;padding:0 11px;border:1px solid rgba(200,255,61,.24);border-radius:9px;background:rgba(200,255,61,.065);color:var(--accent);font-size:11px;font-weight:800}.badge{display:inline-flex;align-items:center;padding:6px 10px;border:1px solid var(--line2);border-radius:999px;font-size:8px;font-weight:900}.badge.block{color:var(--danger)}.badge.ready{color:var(--ok)}
.unified-flow{display:grid;gap:8px;margin-top:15px}.flow-step{display:grid;grid-template-columns:29px minmax(0,1fr);align-items:center;gap:10px;padding:10px 11px;border:1px solid var(--line);border-radius:11px;background:rgba(255,255,255,.025)}.flow-step i{width:27px;height:27px;display:grid;place-items:center;border-radius:50%;background:#090d0a;color:var(--accent);font-style:normal;font-size:9px;font-weight:900}.flow-step span{overflow:hidden;color:#d4dbd5;white-space:nowrap;text-overflow:ellipsis;font-size:11px;font-weight:700}.flow-step.done{border-color:rgba(200,255,61,.22);background:linear-gradient(90deg,rgba(200,255,61,.09),transparent)}
.risk-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:15px}.risk-grid div{padding:14px;border:1px solid var(--line);border-radius:12px;background:rgba(255,255,255,.026)}.risk-grid span{display:block;color:var(--muted);font-size:9px}.risk-grid b{font-size:22px}
.workflow{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));margin-bottom:14px;overflow:hidden;border:1px solid var(--line);border-radius:14px;background:rgba(255,255,255,.026)}.workflow div{padding:15px;border-right:1px solid var(--line)}.workflow div:last-child{border:0}.workflow small{display:block;color:var(--muted);font-size:8px;text-transform:uppercase}.workflow b{font-size:11px}.workflow .done{box-shadow:inset 0 -3px var(--accent)}
.grid{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(300px,.55fr);gap:14px}.side-info{display:grid;gap:10px}.readiness{display:flex;align-items:center;justify-content:space-between;margin:12px 0}.bar{height:8px;overflow:hidden;border-radius:10px;background:rgba(255,255,255,.07)}.bar i{display:block;height:100%;background:linear-gradient(90deg,#8fd51b,var(--accent));box-shadow:0 0 18px rgba(200,255,61,.3)}
.matrix-wrap{max-width:100%;overflow:auto;margin-top:15px}.matrix{display:grid;min-width:650px;gap:4px}.cell{min-height:42px;display:grid;place-items:center;border:1px solid var(--line);border-radius:7px;background:rgba(255,255,255,.025);font-size:9px}.cell.head{border:0;background:transparent;color:var(--muted);font-weight:800}.cell.critical{background:rgba(255,107,107,.15);color:#ff9c9c}.cell.high{background:rgba(242,179,80,.13);color:#f8cb82}.cell.medium{background:rgba(200,255,61,.07);color:#c6d8b7}.cell.none{color:#69736b}.stage{display:flex;justify-content:space-between;padding:9px 0;border-bottom:1px solid var(--line)}.stage span{color:var(--muted)}
.list{display:grid;gap:10px;margin-top:15px}.issue-cards{grid-template-columns:repeat(2,minmax(0,1fr))}.issue{padding:14px 15px;border:1px solid var(--line);border-left:4px solid #6e796f;border-radius:12px;background:rgba(255,255,255,.032);transition:.16s ease}.issue:hover{transform:translateY(-1px);border-color:var(--line2)}.issue.critical{border-left-color:var(--danger)}.issue.high{border-left-color:var(--warn)}.issue header{display:flex;justify-content:space-between;gap:10px}.issue code{color:var(--accent);font-family:inherit;font-weight:900}.issue h4{margin:6px 0 4px;font-size:14px}.issue p{margin:0;color:var(--muted);font-size:11px}.issue small{display:block;margin-top:8px;color:#87938a}.empty{padding:30px;text-align:center;color:var(--muted)}
.drop{min-height:220px;display:grid;place-items:center;padding:25px;text-align:center;border:1px dashed rgba(200,255,61,.35);border-radius:18px;background:linear-gradient(145deg,rgba(200,255,61,.06),rgba(255,255,255,.018))}.drop b{font-size:18px}.drop input{display:none}.files{width:100%;margin-top:15px;border-collapse:separate;border-spacing:0;overflow:hidden;border:1px solid var(--line);border-radius:14px;background:rgba(255,255,255,.025)}.files th,.files td{padding:12px;border-bottom:1px solid var(--line);text-align:left}.files th{color:var(--muted);font-size:8px;letter-spacing:.13em;text-transform:uppercase}.files tr:last-child td{border-bottom:0}.files select,.files input{height:33px;max-width:170px;padding:0 8px;border:1px solid var(--line2);border-radius:7px;background:#101510;color:#fff}
.queue-item{padding:11px;border:1px solid var(--line);border-radius:10px;background:rgba(255,255,255,.025)}.queue-head{display:flex;justify-content:space-between;gap:10px}.queue-item small{display:block;color:var(--muted)}.progress{height:5px;overflow:hidden;margin-top:7px;border-radius:8px;background:rgba(255,255,255,.07)}.progress i{display:block;height:100%;background:var(--accent)}
.placeholder-page,.intelligence-page{min-height:590px;display:flex;flex-direction:column;justify-content:center;padding:58px;border:1px solid var(--line);border-radius:24px;background:radial-gradient(circle at 75% 25%,rgba(200,255,61,.1),transparent 32%),linear-gradient(145deg,rgba(255,255,255,.055),rgba(255,255,255,.018))}.placeholder-page h2,.intelligence-page h2{margin:9px 0;color:#fff;font-size:40px;line-height:1.06;letter-spacing:-.045em}.placeholder-page p,.intelligence-page p{max-width:740px;color:var(--muted);font-size:14px}.ai-mark{width:74px;height:74px;display:grid;place-items:center;margin-bottom:20px;border:1px solid var(--line2);border-radius:50%;background:#0b0e0c;color:var(--accent);font-size:29px}.ai-prompts{display:flex;flex-wrap:wrap;gap:8px;margin-top:20px}.ai-prompts button{min-height:40px;padding:0 13px;border:1px solid var(--line2);border-radius:10px;background:rgba(255,255,255,.04);color:#fff}
.modal{position:fixed;inset:0;z-index:60;display:none;align-items:flex-start;justify-content:center;overflow-y:auto;padding:24px;background:rgba(0,0,0,.76);backdrop-filter:blur(12px)}.modal.open{display:flex}.modal form{width:min(560px,calc(100% - 16px));max-height:calc(100dvh - 48px);margin:auto;padding:25px;overflow-y:auto;border:1px solid var(--line2);border-radius:20px;background:#151b16;color:#fff;box-shadow:var(--shadow)}.modal h2{margin:0 0 14px}.field{display:block;margin:11px 0}.field span{display:block;margin-bottom:5px;color:#a7b2a9;font-size:9px;font-weight:800}.field input,.field select,.field textarea{width:100%;min-height:42px;padding:9px 11px;border:1px solid var(--line2);border-radius:9px;background:#0f140f;color:#fff}.field textarea{min-height:105px;resize:vertical}.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.row{display:flex;justify-content:flex-end;gap:8px;margin-top:15px}
@media(max-width:1280px) and (min-width:821px){.shell{grid-template-columns:244px minmax(0,1fr)}.content{padding:24px 22px 58px}.overview-hero{grid-template-columns:minmax(0,1fr) 205px;padding:28px}.overview-hero h2{font-size:34px}.dashboard-grid,.dashboard-grid.second,.grid{grid-template-columns:1fr}.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.issue-cards{grid-template-columns:1fr}.top{padding-left:22px;padding-right:22px}}
@media(max-height:760px) and (min-width:821px){.side{padding-top:11px;padding-bottom:9px}.brand{padding-bottom:9px}.brand svg{width:34px;height:34px}.project-pick{margin:7px 0 4px;padding:7px 9px}.project-pick select{height:29px}.nav button{min-height:31px}.nav-group{margin-top:6px;margin-bottom:3px;padding-top:2px}.user{padding-top:7px}.top{min-height:74px}.content{padding-top:20px}}
@media(max-width:820px){html,body{height:auto;min-height:100%;overflow-x:hidden;overflow-y:auto}.shell{height:auto;min-height:100vh;display:block;overflow:visible}.side{width:100%;height:auto;position:sticky;top:0;display:grid;grid-template-columns:minmax(120px,auto) minmax(0,1fr);grid-template-areas:"brand project" "nav nav";grid-template-rows:auto auto;gap:8px 10px;padding:9px 10px 8px;border-right:0;border-bottom:1px solid var(--line)}.brand{grid-area:brand;padding:0;border-bottom:0}.brand svg{width:34px;height:34px}.brand small{display:none}.project-pick{grid-area:project;margin:0;padding:6px 8px}.project-pick span{display:none}.nav{grid-area:nav;display:flex;gap:6px;overflow-x:auto;overflow-y:hidden;padding:2px 0 4px;scrollbar-width:none}.nav::-webkit-scrollbar{display:none}.nav-group{display:none}.nav button{flex:0 0 auto;width:auto;min-height:36px;margin:0;padding:0 12px}.user{display:none}.main{height:auto;min-height:100vh;overflow:visible}.top{position:relative;min-height:70px;padding:12px 15px}.top-actions{display:none}.content{padding:18px 14px 48px}.overview-hero{min-height:0;grid-template-columns:1fr;padding:24px}.overview-hero h2{font-size:30px}.hero-state{align-items:flex-start;text-align:left}.metrics,.dashboard-grid,.dashboard-grid.second,.grid,.form-grid{grid-template-columns:1fr}.workflow{grid-template-columns:1fr}.workflow div{border-right:0;border-bottom:1px solid var(--line)}.title-row,.panel-title{align-items:flex-start;flex-direction:column}.files{display:block;overflow-x:auto;white-space:nowrap}.placeholder-page,.intelligence-page{min-height:420px;padding:28px 22px}.placeholder-page h2,.intelligence-page h2{font-size:30px}}
'''


UNIFIED_JS = r'''
(()=>{
  const byId=id=>document.getElementById(id);
  const money=v=>Number(v||0).toLocaleString('pt-BR',{style:'currency',currency:'BRL'});
  const flow=['Empreendimento','Documentos','Compatibilização','Ocorrências','Revisões','Impactos','Orçamento','Planejamento','Mudanças','Relatório','Intelligence'];
  function renderFlow(){const root=byId('unifiedFlow');if(!root)return;root.innerHTML=flow.map((name,i)=>`<div class="flow-step ${i<4?'done':''}"><i>${String(i+1).padStart(2,'0')}</i><span>${name}</span></div>`).join('')}
  function issueHtml(i){const sev=i.severity||'media';return `<article class="issue ${sev==='critica'?'critical':sev==='alta'?'high':''}"><header><code>${i.code||'VLT'}</code><b>${String(sev).toUpperCase()}</b></header><h4>${i.title||'Ocorrência'}</h4><p>${i.description||''}</p><small>${i.location||'Local não informado'} · ${i.assignee||'Sem responsável'} · ${String(i.status||'identificada').replaceAll('_',' ')}</small></article>`}
  async function loadOperational(){if(typeof S==='undefined'||!S.projectId)return;try{const d=await api(`/api/projects/${S.projectId}/operational/dashboard`);byId('opOpen').textContent=d.openIssues||0;byId('opCritical').textContent=`${d.criticalIssues||0} críticas`;byId('opCost').textContent=money(d.estimatedCost);byId('opDays').textContent=`${d.estimatedDays||0} dias`;byId('issueOpen').textContent=d.openIssues||0;byId('issueCritical').textContent=d.criticalIssues||0;byId('issueCost').textContent=money(d.estimatedCost);byId('issueDays').textContent=`${d.estimatedDays||0} dias`;const sev=d.bySeverity||{};byId('riskCritical').textContent=sev.critica||0;byId('riskHigh').textContent=sev.alta||0;byId('riskMedium').textContent=sev.media||0;byId('riskLow').textContent=sev.baixa||0;const html=(d.recent||[]).map(issueHtml).join('')||'<div class="empty">Nenhuma ocorrência operacional registrada.</div>';byId('overviewIssues').innerHTML=html;byId('issueList').innerHTML=html}catch(e){const el=byId('overviewIssues');if(el)el.innerHTML='<div class="empty">Nenhuma ocorrência operacional registrada.</div>'}}
  function sync(){if(typeof S==='undefined')return;const files=S.files||[];byId('opFiles').textContent=files.length;byId('opDisciplines').textContent=`${new Set(files.map(f=>f.discipline_code)).size} disciplinas`;const a=S.analysis;const readiness=a?.readiness||0;byId('overviewReadiness').textContent=`${readiness}%`;byId('overviewCompat').textContent=`${readiness}%`;byId('overviewCompatBar').style.width=`${readiness}%`;byId('overviewGate').textContent=a?.gate||'RODADA NÃO EXECUTADA';byId('overviewCompatText').textContent=a?`Rodada com ${a.files} arquivos, ${a.disciplines?.length||0} disciplinas e ${a.interfacePackages?.length||0} interfaces.`:'Execute uma rodada para avaliar a base.'}
  function openIssue(){byId('issueModal')?.classList.add('open')}
  byId('createIssue')?.addEventListener('click',openIssue);byId('quickIssue')?.addEventListener('click',openIssue);byId('cancelIssue')?.addEventListener('click',()=>byId('issueModal')?.classList.remove('open'));
  byId('issueForm')?.addEventListener('submit',async e=>{e.preventDefault();if(typeof S==='undefined'||!S.projectId)return;const payload={title:byId('iTitle').value,description:byId('iDescription').value,issueType:byId('iType').value,severity:byId('iSeverity').value,location:byId('iLocation').value,disciplines:byId('iDisciplines').value.split(',').map(v=>v.trim()).filter(Boolean),assignee:byId('iAssignee').value};try{await api(`/api/projects/${S.projectId}/operational/issues`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});e.target.reset();byId('issueModal').classList.remove('open');await loadOperational();show('issues')}catch(err){if(typeof fail==='function')fail(err.message)}});
  document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>{document.querySelector('.main')?.scrollTo({top:0,behavior:'auto'})}));
  if(typeof render==='function'){const originalRender=render;render=function(){originalRender();sync();loadOperational()}}
  if(typeof loadProject==='function'){const originalLoad=loadProject;loadProject=async function(){await originalLoad();sync();await loadOperational()}}
  renderFlow();setTimeout(()=>{sync();loadOperational()},600);
})();
'''


def _response(content: str, media_type: str) -> Response:
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Cache-Control": "no-store, max-age=0, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


def install(app: FastAPI) -> None:
    @app.get("/platform-v3.css", include_in_schema=False)
    def platform_v3_css():
        return _response(CSS, "text/css")

    @app.get("/app.css", include_in_schema=False)
    def app_css():
        return _response(CSS, "text/css")

    @app.get("/ui-fixes.css", include_in_schema=False)
    def ui_fixes_css():
        return _response("/* consolidated into platform stylesheet */", "text/css")

    @app.get("/unified-ui.js", include_in_schema=False)
    def unified_ui_js():
        return _response(UNIFIED_JS, "application/javascript")

    @app.get("/supabase-upload.js", include_in_schema=False)
    def supabase_upload_js():
        return _response("/* optional direct-upload runtime disabled in this preview */", "application/javascript")
