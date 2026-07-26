from __future__ import annotations
import json, zipfile
from pathlib import Path
from fastapi.testclient import TestClient
import server

base=Path(__file__).resolve().parent
results=[]
def check(name,cond,detail=''):
    results.append({'name':name,'passed':bool(cond),'detail':detail})
    if not cond: raise AssertionError(f'{name}: {detail}')

client=TestClient(server.app)
check('Health endpoint',client.get('/api/health').status_code==200)
r=client.post('/api/auth/login',json={'email':'demo@vaelithlabs.com.br','password':'vaelith'})
check('Login demonstrativo',r.status_code==204,r.text)
check('Cookie HTTP-only','vaelith_session' in client.cookies)
projects=client.get('/api/projects')
check('Lista de empreendimentos',projects.status_code==200 and len(projects.json())>=1)
pid=projects.json()[0]['id']
state=client.get(f'/api/projects/{pid}/state')
check('Estado do empreendimento',state.status_code==200)
check('Arquivos demonstrativos',len(state.json()['files'])>=7,str(len(state.json()['files'])))
analysis=client.post(f'/api/projects/{pid}/compatibility')
check('Compatibilização geral',analysis.status_code==200,analysis.text[:300])
a=analysis.json()
check('Modo principal correto',a['mode']=='compatibility')
check('Matriz de escopo',len(a.get('scopeMatrix',[]))>=10)
check('Maquete IFC preparada',a['geometric']['status']=='ready')
check('Orçamento reconhecido',a['budget']['rowCount']>=1)
check('Cronograma reconhecido',a['schedule']['rowCount']>=1)
check('Ocorrências rastreáveis',all(i.get('code') and i.get('confidence') for i in a['issues']))
base_resp=client.post(f'/api/projects/{pid}/baseline',json={'status':'Aprovada com ressalvas'})
check('Aprovação da versão-base',base_resp.status_code==200,base_resp.text)
change=client.post(f'/api/projects/{pid}/changes',json={'title':'Mover porta P-034','requestText':'Deslocar a porta para a parede lateral','reason':'Melhorar circulação','element':'Porta P-034','location':'Sala 02','stage':'Projeto'})
check('Cadastro de mudança',change.status_code==200,change.text)
cid=change.json()['id']
change_analysis=client.post(f'/api/projects/{pid}/changes/{cid}/analyze')
check('Análise complementar de mudança',change_analysis.status_code==200,change_analysis.text[:300])
check('Disciplinas impactadas',len(change_analysis.json().get('impactedDisciplines',[]))>=1)
# Gestão de ocorrência
issue_id=a['issues'][0]['id']
upd=client.patch(f'/api/issues/{issue_id}',json={'status':'Em tratamento','responsible':'Coordenação BIM','resolution':'Em validação'})
check('Atualização de ocorrência',upd.status_code==200,upd.text)
state2=client.get(f'/api/projects/{pid}/state').json()
updated=next(i for i in state2['issues'] if i['id']==issue_id)
check('Persistência da ocorrência',updated['status']=='Em tratamento' and updated['responsible']=='Coordenação BIM')
# Salvar uma triagem geométrica simulada vinda do viewer
cl=client.post(f'/api/projects/{pid}/clashes',json={'clashes':[{'disciplineA':'Arquitetura','disciplineB':'Estrutura','elementA':'Porta P-034','elementB':'Pilar P-12','modelA':'ARQ_R01.ifc','modelB':'EST_R01.ifc','volume':0.025,'center':{'x':1,'y':2,'z':3}}]})
check('Salvamento de pré-clash',cl.status_code==200 and len(cl.json()['saved'])==1,cl.text)
# Exportações
for fmt,magic in [('json',b'{'),('xlsx',b'PK'),('docx',b'PK'),('pdf',b'%PDF')]:
    out=client.get(f'/api/projects/{pid}/export/compatibility/{fmt}')
    check(f'Exportação {fmt.upper()}',out.status_code==200 and out.content.startswith(magic),str(out.status_code))
# Arquivos e sintaxe
for path in ['index.html','login.html','app.html','assets/styles.css','assets/app.js','assets/ifc-viewer.js','server.py','Dockerfile','start.bat']:
    check(f'Arquivo {path}',(base/path).exists())
check('CSS balanceado',(base/'assets/styles.css').read_text().count('{')==(base/'assets/styles.css').read_text().count('}'))
# IDs duplicados simples
import re
for html in ['index.html','login.html','app.html']:
    ids=re.findall(r'\bid="([^"]+)"',(base/html).read_text())
    check(f'IDs únicos em {html}',len(ids)==len(set(ids)),str([x for x in set(ids) if ids.count(x)>1]))
summary={'passed':sum(x['passed'] for x in results),'total':len(results),'results':results}
(base/'TEST_RESULTS.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
print(json.dumps({'passed':summary['passed'],'total':summary['total']}))
