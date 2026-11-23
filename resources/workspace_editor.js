/* Workspace editor integration v1.0.11: local session, explicit save and conflict detection. */
const archiveSession=/\/review$/.test(location.pathname)?location.pathname.replace(/review$/,''):null;
let archiveBaseline='',archiveDirty=false;
function archiveSetDirty(value){
  archiveDirty=value;
  if(archiveSession)notifyHost({type:'workspace-dirty',dirty:value});
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
const documentExport=exportDoc;
exportDoc=clean=>{
  const parsed=new DOMParser().parseFromString(documentExport(clean),'text/html');
  parsed.querySelector('[data-workspace-base]')?.remove();
  parsed.querySelectorAll('style').forEach(style=>{if(style.textContent.includes('#review-comments-sidebar'))style.textContent=style.textContent.replace('html,body{background:#fff!important}','');});
  if(!commentsData(doc()).length){
    parsed.querySelector('#review-comments-sidebar')?.remove();
    parsed.querySelectorAll('style').forEach(s=>{if(s.textContent.includes('#review-comments-sidebar'))s.remove();});
  }
  return '<!doctype html>\n'+parsed.documentElement.outerHTML;
};

function notifyHost(message){
  if(workspaceParentOrigin)window.parent.postMessage(message,workspaceParentOrigin);
}

function restoreReviewBody(html){
  const template=doc().createElement('template');template.innerHTML=html;
  function reconcile(parent,desired){
    let cursor=parent.firstChild;
    for(const next of [...desired.childNodes]){
      const matches=node=>node&&node.nodeType===next.nodeType&&(next.nodeType!==1||(node.tagName===next.tagName&&node.id===next.id));
      let current=cursor;
      if(!matches(current)&&next.nodeType===1&&next.id)current=[...parent.children].find(node=>matches(node));
      if(!matches(current)){
        current=next.cloneNode(true);parent.insertBefore(current,cursor);
      }else{
        if(current!==cursor)parent.insertBefore(current,cursor);
        if(current.nodeType===1){
          for(const attribute of [...current.attributes])if(!next.hasAttribute(attribute.name))current.removeAttribute(attribute.name);
          for(const attribute of next.attributes)if(current.getAttribute(attribute.name)!==attribute.value)current.setAttribute(attribute.name,attribute.value);
          reconcile(current,next);
        }else if(current.nodeValue!==next.nodeValue)current.nodeValue=next.nodeValue;
      }
      cursor=current.nextSibling;
    }
    while(cursor){const next=cursor.nextSibling;cursor.remove();cursor=next;}
  }
  reconcile(doc().body,template.content);
}

if(archiveSession){
  const interfaceStyle=document.createElement('style');
  interfaceStyle.textContent='#open,#dropOpen,#export,#exportType{display:none}body{height:100vh;display:flex;flex-direction:column;overflow:hidden}header{flex:none}.layout{flex:1;min-height:0;height:auto}';
  document.head.appendChild(interfaceStyle);
  let archiveLoaded=false,changeJob=null;
  const changed=()=>{
    clearTimeout(changeJob);
    changeJob=setTimeout(()=>archiveSetDirty(archiveText()!==archiveBaseline),80);
  };
  for(const name of ['push','undo','redo']){
    const original=name==='push'?push:name==='undo'?undo:redo;
    const wrapped=(...args)=>{const result=original(...args);changed();return result;};
    if(name==='push')push=wrapped;else if(name==='undo')undo=wrapped;else redo=wrapped;
  }
  const originalLoad=load;
  load=async file=>{
    if(archiveLoaded)return;
    archiveLoaded=true;
    await originalLoad(file);
    const loaded=frame.onload;
    frame.onload=event=>{
      loaded.call(frame,event);
      const toolStyle=doc().querySelector('#review-tool-style');
      if(toolStyle)toolStyle.textContent=toolStyle.textContent.replace('background:var(--editor-paper,#fff)!important;color:var(--editor-ink,#222)!important;','');
      doc().querySelectorAll('button,input,select,textarea,canvas,svg').forEach(node=>node.contentEditable='false');
      commentNo=Math.max(0,...[...doc().querySelectorAll('[data-comment-id]')].map(node=>Number(node.dataset.commentId.replace(/^C/,''))||0));
      archiveBaseline=archiveText();archiveDirty=false;
      doc().addEventListener('input',event=>{if(!event.target.closest('button,input,select,textarea'))changed();});
      const shortcut=event=>{
        if(event.isTrusted&&(event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'){
          event.preventDefault();notifyHost({type:'workspace-save-shortcut'});
        }
      };
      doc().addEventListener('keydown',shortcut,true);
      document.addEventListener('keydown',shortcut,true);
      notifyHost({type:'workspace-ready'});
    };
  };
  window.addEventListener('message',event=>{
    if(event.source!==window.parent||event.origin!==workspaceParentOrigin)return;
    const message=event.data;
    if(!message||typeof message!=='object')return;
    if(message.type==='workspace-host-ready'&&ready)notifyHost({type:'workspace-ready'});
    if(message.type==='workspace-snapshot'&&ready){
      try{
        const text=message.exporting?exportDoc(message.clean===true):archiveText();
        notifyHost({type:'workspace-snapshot-result',id:message.id,text});
      }catch(error){notifyHost({type:'workspace-snapshot-result',id:message.id,error:error.message});}
    }
    if(message.type==='workspace-saved'&&ready){
      archiveBaseline=message.text;archiveSetDirty(archiveText()!==archiveBaseline);
    }
  });
  document.addEventListener('drop',event=>{event.preventDefault();event.stopImmediatePropagation();},true);
  fetch(archiveSession+'document').then(async response=>{
    const data=await response.json();
    if(!response.ok)throw new Error(data.error||'读取归档失败');
    fileName=data.name;
    await load(new File([data.text],data.name,{type:'text/html;charset=utf-8'}));
  }).catch(error=>{status(error.message);$('#drop strong').textContent='归档读取失败';});
}
