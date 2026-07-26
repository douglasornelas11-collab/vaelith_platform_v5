from __future__ import annotations

import hashlib, json, os, secrets, sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import Cookie, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

BASE = Path(__file__).resolve().parent
DATA = Path('/tmp/vaelith-v6') if os.getenv('VERCEL') else BASE / 'data'
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / 'vaelith.db'
APP_VERSION = '6.0-production-beta'
COOKIE_SECURE = bool(os.getenv('VERCEL')) or os.getenv('COOKIE_SECURE') == '1'
MAX_UPLOAD_MB = 4 if os.getenv('VERCEL') else int(os.getenv('MAX_UPLOAD_MB', '50'))
app = FastAPI(title='VAELITH LABS', version=APP_VERSION)

DISCIPLINES = ['Arquitetura','Estrutura','Elétrica','Hidráulica','Sanitária','Incêndio','Climatização','Orçamento','Planejamento','Escopo e memoriais']
EXT_DISC = {'.ifc':'Modelo BIM','.rvt':'Modelo BIM','.dwg':'Projeto 2D','.pdf':'Documento','.docx':'Escopo e memoriais','.xlsx':'Orçamento/Planejamento','.csv':'Orçamento/Planejamento','.mpp':'Planejamento'}

def now(): return datetime.now(timezone.utc).isoformat()
def conn():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

def hash_pw(password:str, salt:str|None=None):
    salt=salt or secrets.token_hex(16)
    digest=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),180000).hex()
    return salt,digest

def init_db():
    with conn() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,name TEXT,email TEXT UNIQUE,salt TEXT,pw TEXT);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id TEXT,expires TEXT);
        CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,user_id TEXT,name TEXT,client TEXT,location TEXT,phase TEXT,created TEXT);
        CREATE TABLE IF NOT EXISTS files(id TEXT PRIMARY KEY,project_id TEXT,name TEXT,ext TEXT,size INTEGER,discipline TEXT,revision TEXT,uploaded TEXT);
        CREATE TABLE IF NOT EXISTS analyses(id TEXT PRIMARY KEY,project_id TEXT,result TEXT,created TEXT);
        ''')
        u=c.execute('SELECT * FROM users WHERE email=?',('demo@vaelithlabs.com.br',)).fetchone()
        if not u:
            uid=uuid4().hex; salt,pw=hash_pw('vaelith')
            c.execute('INSERT INTO users VALUES(?,?,?,?,?)',(uid,'Douglas Demo','demo@vaelithlabs.com.br',salt,pw))
        else: uid=u['id']
        p=c.execute('SELECT * FROM projects WHERE user_id=?',(uid,)).fetchone()
        if not p:
            pid=uuid4().hex
            c.execute('INSERT INTO projects VALUES(?,?,?,?,?,?,?)',(pid,uid,'Empreendimento demonstrativo','Cliente exemplo','Betim/MG','Pré-obra',now()))
            demo=[('ARQ_R01.ifc','.ifc','Arquitetura','R01'),('EST_R01.ifc','.ifc','Estrutura','R01'),('ELE_R00.dwg','.dwg','Elétrica','R00'),('ORC_R01.xlsx','.xlsx','Orçamento','R01'),('CRONO_R01.mpp','.mpp','Planejamento','R01'),('MEMORIAL_R01.pdf','.pdf','Escopo e memoriais','R01')]
            for name,ext,disc,rev in demo:
                c.execute('INSERT INTO files VALUES(?,?,?,?,?,?,?,?)',(uuid4().hex,pid,name,ext,1024,disc,rev,now()))
init_db()

def current_user(token:str|None):
    if not token: return None
    with conn() as c:
        row=c.execute('''SELECT users.* FROM sessions JOIN users ON users.id=sessions.user_id WHERE token=? AND expires>?''',(token,now())).fetchone()
        return dict(row) if row else None

def require_user(token):
    u=current_user(token)
    if not u: raise HTTPException(401,'Sessão expirada. Entre novamente.')
    return u

def owns(project_id,user_id):
    with conn() as c: return c.execute('SELECT * FROM projects WHERE id=? AND user_id=?',(project_id,user_id)).fetchone()

def host(request:Request): return request.headers.get('host','').split(':')[0].lower()

@app.get('/')
def home(request:Request):
    if host(request).startswith('app.'):
        return RedirectResponse('/login',307)
    return FileResponse(BASE/'index.html')
@app.get('/login')
def login_page(): return FileResponse(BASE/'login.html')
@app.get('/app')
def app_page(): return FileResponse(BASE/'app.html')

@app.get('/api/health')
def health(): return {'ok':True,'version':APP_VERSION,'environment':'vercel' if os.getenv('VERCEL') else 'local','maxUploadMb':MAX_UPLOAD_MB,'storage':'temporary' if os.getenv('VERCEL') else 'local'}

@app.post('/api/auth/login')
async def login(request:Request):
    body=await request.json(); email=str(body.get('email','')).lower().strip(); password=str(body.get('password',''))
    with conn() as c: u=c.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
    if not u: raise HTTPException(401,'E-mail ou senha inválidos.')
    _,digest=hash_pw(password,u['salt'])
    if not secrets.compare_digest(digest,u['pw']): raise HTTPException(401,'E-mail ou senha inválidos.')
    token=secrets.token_urlsafe(32); expires=(datetime.now(timezone.utc)+timedelta(days=14)).isoformat()
    with conn() as c: c.execute('INSERT INTO sessions VALUES(?,?,?)',(token,u['id'],expires))
    r=Response(status_code=204); r.set_cookie('vaelith_session',token,httponly=True,secure=COOKIE_SECURE,samesite='lax',max_age=1209600,path='/'); return r

@app.post('/api/auth/logout')
def logout(vaelith_session:str|None=Cookie(None)):
    if vaelith_session:
        with conn() as c: c.execute('DELETE FROM sessions WHERE token=?',(vaelith_session,))
    r=Response(status_code=204); r.delete_cookie('vaelith_session',path='/'); return r

@app.get('/api/me')
def me(vaelith_session:str|None=Cookie(None)):
    u=require_user(vaelith_session); return {'id':u['id'],'name':u['name'],'email':u['email']}

@app.get('/api/projects')
def projects(vaelith_session:str|None=Cookie(None)):
    u=require_user(vaelith_session)
    with conn() as c:
        rows=c.execute('''SELECT p.*,COUNT(f.id) file_count FROM projects p LEFT JOIN files f ON f.project_id=p.id WHERE p.user_id=? GROUP BY p.id ORDER BY p.created DESC''',(u['id'],)).fetchall()
    return [dict(x) for x in rows]

@app.post('/api/projects')
async def create_project(request:Request,vaelith_session:str|None=Cookie(None)):
    u=require_user(vaelith_session); b=await request.json(); name=str(b.get('name','')).strip()
    if not name: raise HTTPException(400,'Informe o nome do empreendimento.')
    pid=uuid4().hex
    with conn() as c: c.execute('INSERT INTO projects VALUES(?,?,?,?,?,?,?)',(pid,u['id'],name,str(b.get('client','')),str(b.get('location','')),str(b.get('phase','Pré-obra')),now()))
    return {'id':pid,'name':name}

@app.get('/api/projects/{pid}/files')
def files(pid:str,vaelith_session:str|None=Cookie(None)):
    u=require_user(vaelith_session)
    if not owns(pid,u['id']): raise HTTPException(404,'Empreendimento não encontrado.')
    with conn() as c: rows=c.execute('SELECT * FROM files WHERE project_id=? ORDER BY uploaded DESC',(pid,)).fetchall()
    return [dict(x) for x in rows]

@app.post('/api/projects/{pid}/upload')
async def upload(pid:str,uploads:list[UploadFile]=File(...),vaelith_session:str|None=Cookie(None)):
    u=require_user(vaelith_session)
    if not owns(pid,u['id']): raise HTTPException(404,'Empreendimento não encontrado.')
    saved=[]
    for f in uploads:
        raw=await f.read(MAX_UPLOAD_MB*1024*1024+1)
        if len(raw)>MAX_UPLOAD_MB*1024*1024: raise HTTPException(413,f'{f.filename}: limite de {MAX_UPLOAD_MB} MB por arquivo.')
        name=f.filename or 'arquivo'; ext=Path(name).suffix.lower(); upper=name.upper()
        disc=next((d for d in DISCIPLINES if d.upper()[:4] in upper),'Não identificada')
        if 'ARQ' in upper: disc='Arquitetura'
        elif 'EST' in upper: disc='Estrutura'
        elif 'ELE' in upper: disc='Elétrica'
        elif 'HID' in upper: disc='Hidráulica'
        elif 'ORC' in upper or 'ORÇ' in upper: disc='Orçamento'
        elif 'CRONO' in upper or ext=='.mpp': disc='Planejamento'
        rev='R'+upper.split('_R')[-1][:2] if '_R' in upper else 'Não informada'
        fid=uuid4().hex
        with conn() as c: c.execute('INSERT INTO files VALUES(?,?,?,?,?,?,?,?)',(fid,pid,name,ext,len(raw),disc,rev,now()))
        saved.append({'id':fid,'name':name,'discipline':disc,'revision':rev,'type':EXT_DISC.get(ext,'Arquivo')})
    return {'saved':saved}

@app.post('/api/projects/{pid}/compatibility')
def compatibility(pid:str,vaelith_session:str|None=Cookie(None)):
    u=require_user(vaelith_session)
    if not owns(pid,u['id']): raise HTTPException(404,'Empreendimento não encontrado.')
    with conn() as c: rows=[dict(x) for x in c.execute('SELECT * FROM files WHERE project_id=?',(pid,)).fetchall()]
    discs=sorted({x['discipline'] for x in rows}); revisions=sorted({x['revision'] for x in rows if x['revision']!='Não informada'})
    missing=[d for d in DISCIPLINES if d not in discs]
    findings=[]
    if 'Arquitetura' in discs and 'Estrutura' in discs: findings.append({'code':'INT-001','severity':'Alta','title':'Verificar interfaces entre arquitetura e estrutura','reason':'Os modelos das duas disciplinas foram recebidos e exigem conferência geométrica federada.'})
    if len(revisions)>1: findings.append({'code':'REV-001','severity':'Alta','title':'Revisões divergentes no conjunto','reason':f'Foram identificadas revisões {", ".join(revisions)}. Confirme a versão-base antes da análise definitiva.'})
    if missing: findings.append({'code':'DOC-001','severity':'Média','title':'Disciplinas ainda não recebidas','reason':f'Pendências: {", ".join(missing[:5])}.'})
    if not any(x['discipline']=='Orçamento' for x in rows): findings.append({'code':'ORC-001','severity':'Média','title':'Orçamento não localizado','reason':'Não é possível verificar impactos de custo sem uma base orçamentária.'})
    result={'id':uuid4().hex,'projectId':pid,'createdAt':now(),'files':len(rows),'disciplines':discs,'missing':missing,'findings':findings,'summary':{'critical':0,'high':sum(x['severity']=='Alta' for x in findings),'medium':sum(x['severity']=='Média' for x in findings)}}
    with conn() as c: c.execute('INSERT INTO analyses VALUES(?,?,?,?)',(result['id'],pid,json.dumps(result,ensure_ascii=False),now()))
    return result

@app.get('/api/projects/{pid}/export')
def export(pid:str,vaelith_session:str|None=Cookie(None)):
    u=require_user(vaelith_session)
    if not owns(pid,u['id']): raise HTTPException(404,'Empreendimento não encontrado.')
    with conn() as c: row=c.execute('SELECT result FROM analyses WHERE project_id=? ORDER BY created DESC LIMIT 1',(pid,)).fetchone()
    if not row: raise HTTPException(404,'Execute a compatibilização primeiro.')
    return JSONResponse(json.loads(row['result']),headers={'Content-Disposition':f'attachment; filename=vaelith-{pid[:8]}.json'})
