from fastapi.testclient import TestClient
import server

client = TestClient(server.app)

def test_flow():
    assert client.get('/api/health').json()['ok'] is True
    r=client.post('/api/auth/login',json={'email':'demo@vaelithlabs.com.br','password':'vaelith'})
    assert r.status_code==204, r.text
    me=client.get('/api/auth/me')
    assert me.status_code==200
    projects=client.get('/api/projects').json()
    assert projects
    pid=projects[0]['id']
    state=client.get(f'/api/projects/{pid}/state')
    assert state.status_code==200
    data=state.json()
    assert len(data['files'])>=7
    analysis=client.post(f'/api/projects/{pid}/compatibility')
    assert analysis.status_code==200,analysis.text
    a=analysis.json()
    assert a['mode']=='compatibility'
    assert 'scopeMatrix' in a and 'geometric' in a
    assert a['metrics']['files']>=7
    baseline=client.post(f'/api/projects/{pid}/baseline',json={'status':'Aprovada com ressalvas'})
    assert baseline.status_code==200,baseline.text
    change=client.post(f'/api/projects/{pid}/changes',json={'title':'Deslocar porta P-034','requestText':'Mover a porta para a parede lateral','reason':'Melhorar circulação','element':'Porta P-034','location':'Sala 02','stage':'Projeto'})
    assert change.status_code==200,change.text
    cid=change.json()['id']
    ca=client.post(f'/api/projects/{pid}/changes/{cid}/analyze')
    assert ca.status_code==200,ca.text
    assert ca.json()['mode']=='change'
    for fmt in ['json','xlsx','docx','pdf']:
        out=client.get(f'/api/projects/{pid}/export/compatibility/{fmt}')
        assert out.status_code==200, (fmt,out.text[:100])

if __name__=='__main__':
    test_flow()
    print('OK')
