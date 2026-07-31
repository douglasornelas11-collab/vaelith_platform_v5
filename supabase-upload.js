(()=>{
  let maxFileMb=50;
  let maxBytes=maxFileMb*1024*1024;
  const input=document.getElementById('fileInput');
  const uploadButton=document.getElementById('upload');
  const dropZone=document.getElementById('dropZone');
  if(!input||!uploadButton||!dropZone)return;

  const originalRender=renderQueue;
  window.vaelithStorageReady=false;

  async function storageStatus(){
    try{
      const r=await fetch('/api/storage/status',{cache:'no-store'});
      const d=await r.json();
      if(Number(d.maxFileMb)>0){
        maxFileMb=Number(d.maxFileMb);
        maxBytes=maxFileMb*1024*1024;
      }
      window.vaelithStorageReady=Boolean(d.configured&&d.directUpload);
      const badge=document.querySelector('#base .title-row .badge');
      if(badge) badge.textContent=window.vaelithStorageReady?`ATÉ ${maxFileMb} MB POR ARQUIVO · ARMAZENAMENTO PERMANENTE`:'ARMAZENAMENTO AINDA NÃO CONECTADO';
      return d;
    }catch{return {configured:false,maxFileMb:4}}
  }

  function persistentSetQueue(files){
    S.queue=[...files].map((file,i)=>({
      id:Date.now()+'-'+i,
      file,
      status:file.size>maxBytes?'blocked':'waiting',
      progress:0,
      message:file.size>maxBytes?`Arquivo acima do limite atual de ${maxFileMb} MB.`:'Aguardando upload permanente'
    }));
    originalRender();
  }

  function directPut(q,signed){
    return new Promise((resolve,reject)=>{
      const xhr=new XMLHttpRequest();
      q.status='uploading';q.message='Enviando diretamente ao armazenamento privado...';originalRender();
      xhr.open('PUT',signed.signedUrl,true);
      xhr.setRequestHeader('Content-Type',q.file.type||signed.mime||'application/octet-stream');
      xhr.upload.onprogress=e=>{if(e.lengthComputable){q.progress=Math.round((e.loaded/e.total)*100);originalRender()}};
      xhr.onload=()=>xhr.status>=200&&xhr.status<300?resolve():reject(new Error(`Supabase recusou o arquivo (${xhr.status}).`));
      xhr.onerror=()=>reject(new Error('Falha de conexão com o armazenamento.'));
      xhr.send(q.file);
    });
  }

  async function uploadPersistent(q){
    try{
      const signed=await api(`/api/projects/${S.projectId}/uploads/sign`,{
        method:'POST',headers:{'content-type':'application/json'},
        body:JSON.stringify({name:q.file.name,size:q.file.size,mime:q.file.type})
      });
      await directPut(q,signed);
      q.message='Validando persistência do arquivo...';originalRender();
      await api(`/api/projects/${S.projectId}/uploads/confirm`,{
        method:'POST',headers:{'content-type':'application/json'},
        body:JSON.stringify({fileId:signed.fileId,path:signed.path,name:q.file.name,size:q.file.size,mime:q.file.type})
      });
      q.status='ok';q.progress=100;q.message='Arquivo persistido e registrado no banco.';
    }catch(e){q.status='fail';q.message=e.message||'Falha no upload permanente.'}
    originalRender();
  }

  input.onchange=e=>persistentSetQueue(e.target.files);
  dropZone.ondragover=e=>e.preventDefault();
  dropZone.ondrop=e=>{e.preventDefault();persistentSetQueue(e.dataTransfer.files)};
  uploadButton.onclick=async()=>{
    const status=await storageStatus();
    if(!status.configured){fail('O armazenamento permanente ainda não está disponível neste ambiente.');return}
    uploadButton.disabled=true;
    for(const q of S.queue.filter(x=>x.status==='waiting')) await uploadPersistent(q);
    await loadProject();show('base');await loadBudget();
  };
  storageStatus();
})();
