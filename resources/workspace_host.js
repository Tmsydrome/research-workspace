/* Workspace archive controls v1.0.11. */
const reviewFrame=document.querySelector('#review');
const statusNode=document.querySelector('#state');
const saveButton=document.querySelector('#save'),exportButton=document.querySelector('#export');
const session=location.pathname.replace(/editor$/,'');
const renderOrigin=new URL(workspaceHostConfig.review).origin;
const waiting=new Map();
let etag='',loaded=false,dirty=false,saving=false,stateQueue=Promise.resolve();
function buttons(){saveButton.disabled=exportButton.disabled=!loaded||saving;}
async function request(route,body){
  const response=await fetch(session+route,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const result=await response.json();
  if(!response.ok)throw new Error(result.error||'归档请求失败');
  return result;
}
function recordDirty(value){
  dirty=value;
  stateQueue=stateQueue.catch(()=>{}).then(()=>request('state',{dirty:value})).catch(()=>{});
}
function send(message){reviewFrame.contentWindow.postMessage(message,renderOrigin);}
function snapshot(clean,exporting){
  return new Promise((resolve,reject)=>{
    const id=crypto.randomUUID();
    const timer=setTimeout(()=>{waiting.delete(id);reject(new Error('读取网页内容超时，请重试'));},20000);
    waiting.set(id,{resolve,reject,timer});
    send({type:'workspace-snapshot',id,clean,exporting});
  });
}
async function save(){
  if(!loaded||saving)return;
  saving=true;buttons();statusNode.textContent='正在保存归档…';
  try{
    const text=await snapshot(false,false);
    const result=await request('save',{text,etag});
    etag=result.etag;send({type:'workspace-saved',text});
    statusNode.textContent='已保存归档 · '+result.savedAt;
  }catch(error){statusNode.textContent=error.message;alert(error.message);}
  finally{saving=false;buttons();}
}
async function exportFile(){
  if(!loaded||saving)return;
  saving=true;buttons();
  try{
    const clean=document.querySelector('#exportType').value==='clean';
    const text=await snapshot(clean,true);
    const name=workspaceHostConfig.name.replace(/\.html?$/i,'')+(clean?'_清洁批注版.html':'_修订批注版.html');
    const result=await request('export',{text,name});
    statusNode.textContent='已导出到桌面 · '+result.name;
  }catch(error){statusNode.textContent=error.message;alert(error.message);}
  finally{saving=false;buttons();}
}
window.addEventListener('message',event=>{
  if(event.source!==reviewFrame.contentWindow||event.origin!==renderOrigin)return;
  const message=event.data;
  if(!message||typeof message!=='object')return;
  if(message.type==='workspace-ready'){
    loaded=Boolean(etag);buttons();recordDirty(false);
    statusNode.textContent='网页已加载 · 可选择文字添加批注';
  }else if(message.type==='workspace-dirty'){
    recordDirty(message.dirty===true);
    if(dirty)statusNode.textContent='有未保存的文字修订或批注';
  }else if(message.type==='workspace-snapshot-result'){
    const pending=waiting.get(message.id);
    if(!pending)return;
    waiting.delete(message.id);clearTimeout(pending.timer);
    if(message.error)pending.reject(new Error(message.error));
    else if(typeof message.text==='string'&&message.text.trim())pending.resolve(message.text);
    else pending.reject(new Error('网页保存内容为空'));
  }else if(message.type==='workspace-save-shortcut'){
    saveButton.focus();statusNode.textContent='按 Enter 保存归档';
  }
});
saveButton.addEventListener('click',event=>{if(event.isTrusted)save();});
exportButton.addEventListener('click',event=>{if(event.isTrusted)exportFile();});
document.querySelector('#reload').addEventListener('click',event=>{
  if(!event.isTrusted||saving)return;
  if(!dirty||confirm('放弃当前未保存修改，重新读取归档？')){dirty=false;location.reload();}
});
document.addEventListener('keydown',event=>{
  if(event.isTrusted&&(event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'){
    event.preventDefault();save();
  }
});
window.addEventListener('beforeunload',event=>{if(dirty||saving){event.preventDefault();event.returnValue='';}});
request('document').then(data=>{etag=data.etag;send({type:'workspace-host-ready'});}).catch(error=>{statusNode.textContent=error.message;});
