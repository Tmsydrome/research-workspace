/* Workspace editor integration v1.0.4: local session, explicit save and conflict detection. */
const archiveSession=/\/editor$/.test(location.pathname)?location.pathname.replace(/editor$/,''):null;
let archiveEtag='',archiveBaseline='',archiveDirty=false,archiveSaving=false;
let archiveStateQueue=Promise.resolve();
function archiveSetDirty(value){
  archiveDirty=value;
  if(archiveSession)archiveStateQueue=archiveStateQueue.catch(()=>{}).then(()=>fetch(archiveSession+'state',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({dirty:value})})).catch(()=>{});
}
function archiveText(){
  const out=doc().cloneNode(true);
  out.body.classList.remove('review-editing','hide-review');
  out.querySelectorAll('[contenteditable]').forEach(n=>n.removeAttribute('contenteditable'));
  out.querySelector('#review-tool-style')?.remove();
  out.querySelector('[data-workspace-base]')?.remove();
  out.querySelector('#review-pen-cursor')?.remove();
  out.body.style.removeProperty('--editor-paper');
  out.body.style.removeProperty('--editor-ink');
  const layer=out.querySelector('#review-drawing-layer');
  if(layer){
    layer.style.pointerEvents='none';layer.style.cursor='auto';
    if(!layer.querySelector('path,polyline,line,circle,rect'))layer.remove();
  }
  out.querySelectorAll('meta[charset],meta[http-equiv="Content-Type" i]').forEach(n=>n.remove());
  const charset=out.createElement('meta');charset.setAttribute('charset','utf-8');out.head.prepend(charset);
  if(!out.querySelector('#review-document-style')){
    const style=out.createElement('style');style.id='review-document-style';
    style.textContent='ins[data-change]{color:#1565c0;text-decoration:underline;background:#e9f3ff}del[data-change]{color:#c62828;text-decoration:line-through;background:#ffeded}.review-comment{background:#fff0a8;border-bottom:2px solid #d2a800}';
    out.head.appendChild(style);
  }
  return '<!doctype html>\n'+out.documentElement.outerHTML;
}
async function saveArchive(){
  if(!archiveSession||!ready||archiveSaving)return;
  const button=$('#archiveSave');
  archiveSaving=true;button.disabled=true;
  try{
    const text=archiveText();
    const response=await fetch(archiveSession+'save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text,etag:archiveEtag})});
    const result=await response.json();
    if(!response.ok)throw new Error(result.error||'保存失败');
    archiveEtag=result.etag;archiveBaseline=text;
    archiveSetDirty(archiveText()!==archiveBaseline);
    status('已保存归档副本 · '+result.savedAt);
  }catch(error){status(error.message);alert(error.message);}
  finally{archiveSaving=false;button.disabled=false;}
}
async function exportSelected(){
  const base=fileName.replace(/\.html?$/i,''),clean=$('#exportType').value==='clean',button=$('#export');
  button.disabled=true;
  try{
    const name=await download(exportDoc(clean),base+(clean?'_清洁批注版.html':'_修订批注版.html'));
    status(archiveSession?'已导出到桌面 · '+name:'已导出'+(clean?'清洁＋批注版':'修订＋批注版'));
  }catch(error){status('导出失败：'+error.message);}
  finally{button.disabled=false;}
}

if(archiveSession){
  download=async (text,name)=>{
    const response=await fetch(archiveSession+'export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text,name})});
    const result=await response.json();
    if(!response.ok)throw new Error(result.error||'导出失败');
    return result.name;
  };
  $('#export').textContent='导出到桌面';
  $('#export').onclick=exportSelected;
  const originalLoad=load;
  let archiveLoaded=false;
  load=async file=>{
    if(archiveLoaded){status('当前会话编辑归档副本，请从工作区打开其他附件。');return;}
    archiveLoaded=true;
    const parsed=new DOMParser().parseFromString(await file.text(),'text/html');
    parsed.querySelectorAll('base').forEach(n=>n.remove());
    const base=parsed.createElement('base');base.href=window.workspaceBaseURL;base.dataset.workspaceBase='true';parsed.head.prepend(base);
    await originalLoad(new File(['<!doctype html>\n'+parsed.documentElement.outerHTML],file.name,{type:'text/html;charset=utf-8'}));
    const loaded=frame.onload;
    frame.onload=event=>{
      loaded.call(frame,event);
      commentNo=Math.max(0,...[...doc().querySelectorAll('[data-comment-id]')].map(n=>Number(n.dataset.commentId.replace(/^C/,''))||0));
      window.dispatchEvent(new Event('review-ready'));
    };
  };
  const button=document.createElement('button');button.id='archiveSave';button.className='primary';button.textContent='保存归档';button.title='Ctrl+S';
  $('#export').parentElement.after(button);button.onclick=saveArchive;
  $('#open').textContent='重新加载归档';
  $('#open').onclick=()=>{if(!archiveDirty||confirm('放弃当前未保存修改，重新读取归档？'))location.reload();};
  document.addEventListener('drop',e=>{e.preventDefault();e.stopImmediatePropagation();status('当前编辑归档副本，请从工作区打开其他附件。');},true);
  window.addEventListener('beforeunload',e=>{if(archiveDirty||archiveSaving){e.preventDefault();e.returnValue='';}});
  const saveKey=e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();e.stopImmediatePropagation();saveArchive();}};
  document.addEventListener('keydown',saveKey,true);
  window.addEventListener('review-ready',()=>{
    doc().addEventListener('keydown',saveKey,true);
    archiveBaseline=archiveText();archiveDirty=false;
    // ponytail: debounced document serialization; incremental tracking if large documents need it.
    let job=null;
    const changed=()=>{clearTimeout(job);job=setTimeout(()=>{archiveSetDirty(archiveText()!==archiveBaseline);},80);};
    new MutationObserver(changed).observe(doc().body,{childList:true,subtree:true,characterData:true,attributes:true});
    doc().addEventListener('input',()=>{archiveSetDirty(true);changed();});
  });
  fetch(archiveSession+'document').then(async response=>{
    const data=await response.json();
    if(!response.ok)throw new Error(data.error||'读取归档失败');
    archiveEtag=data.etag;window.workspaceBaseURL=data.base;
    document.title=data.name+' · HTML修订批注工具 v0.4.7';
    await load(new File([data.text],data.name,{type:'text/html;charset=utf-8'}));
  }).catch(error=>{status(error.message);$('#drop strong').textContent='归档读取失败';});
}
