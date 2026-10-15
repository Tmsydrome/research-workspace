"""Local desktop export checks, version 1.0.4."""
import json,re,subprocess,tempfile
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from html_editor import HtmlEditor,EDITOR,desktop_directory
from workspace import VERSION

def main():
    assert desktop_directory().is_dir()
    with tempfile.TemporaryDirectory(prefix="research_editor_flow_") as tmp:
        base=Path(tmp);desktop=base/"Desktop";desktop.mkdir()
        document=base/"资料.html";document.write_text("<h1>归档内容</h1>",encoding="utf-8")
        original=document.read_bytes()
        bridge=HtmlEditor()
        try:
            url=bridge.url("fixture",document,base,base/"history")
            session=url.rsplit("/",1)[0]+"/"
            def post(route,body,origin=None):
                request=Request(session+route,json.dumps(body,ensure_ascii=False).encode("utf-8"),
                    {"Content-Type":"application/json","Origin":origin or bridge.origin})
                try:
                    with urlopen(request) as response:return response.status,json.load(response)
                except HTTPError as error:return error.code,json.load(error)
            text='<!doctype html><p><ins data-change="N001">新增</ins><del data-change="N002">删除</del></p><span class="review-comment" data-comment-id="N001">批注</span>'
            assert post("state",{"dirty":True})[0]==200
            with patch("html_editor.desktop_directory",return_value=desktop):
                status,exported=post("export",{"name":"资料_修订批注版.html","text":text})
                assert status==200 and Path(exported["path"]).parent==desktop
                assert Path(exported["path"]).read_text(encoding="utf-8")==text
                status,duplicate=post("export",{"name":"资料_修订批注版.html","text":text+"2"})
                assert status==200 and duplicate["name"]=="资料_修订批注版_2.html"
                assert Path(exported["path"]).read_text(encoding="utf-8")==text
                assert post("export",{"name":"../other.html","text":text})[0]==200
                assert not (base/"other.html").exists()
                assert post("export",{"name":"document.txt","text":text})[0]==400
                assert post("export",{"name":"other.html","text":[]})[0]==400
                assert post("export",{"name":"external.html","text":text},"https://example.com")[0]==403
                count=len(list(desktop.iterdir()))
                with patch("html_editor.os.fsync",side_effect=OSError("Write failure")):
                    assert post("export",{"name":"failed.html","text":text})[0]==400
                assert len(list(desktop.iterdir()))==count
                with urlopen(url) as response:html=response.read().decode("utf-8")
                assert 'HTML修订批注工具 v0.4.7' in html and 'id="toggleComments"' in html
                assert 'id="splitter"' in html and 'Workspace editor integration v1.0.4' in html
                assert '<div class="creator-profile" aria-label="Tmsydrome">' in html
                assert not re.search(r'<a[^>]*class="creator-profile"',html)
                functions=re.search(r'async function exportSelected\(\)\{.*?\n\}',html,re.S)[0]
                download=re.search(r'download=async \(text,name\)=>\{.*?\n  \};',html,re.S)[0]
                scripts=re.findall(r'<script>(.*?)</script>',html,re.S)
                config={"session":session,"origin":bridge.origin,"text":text,"functions":functions,"download":download,"scripts":scripts}
                # Node evaluates the export handlers and sends real HTTP requests to the temporary desktop.
                node="""const fs=require('fs'),vm=require('vm'),assert=require('assert');
const c=JSON.parse(fs.readFileSync(0,'utf8'));
for(const script of c.scripts)new vm.Script(script);
let message='',button={disabled:false},choice={value:'review'};
const context={fileName:'页面.html',archiveSession:c.session,exportDoc:()=>c.text,
  $:id=>id==='#export'?button:choice,status:text=>message=text,
  fetch:(url,options)=>fetch(url,{...options,headers:{...options.headers,Origin:c.origin}})};
vm.createContext(context);vm.runInContext(c.download+'\\n'+c.functions,context);
(async()=>{await context.exportSelected();assert(message.includes('已导出到桌面'));assert(!button.disabled);
choice.value='clean';await context.exportSelected();assert(message.includes('已导出到桌面'));assert(!button.disabled);
console.log('Export handlers passed')})().catch(e=>{console.error(e);process.exitCode=1});"""
                subprocess.run(["node","-e",node],input=json.dumps(config,ensure_ascii=False),text=True,encoding="utf-8",check=True,capture_output=True)
                assert (desktop/"页面_修订批注版.html").read_text(encoding="utf-8")==text
                assert (desktop/"页面_清洁批注版.html").read_text(encoding="utf-8")==text
                assert document.read_bytes()==original and bridge.has_unsaved()
            checks=["直接导出桌面及原文与批注保留","同名文件编号与路径边界","错误来源和格式校验及失败清理",
                    "页面导出处理程序及两类导出路径","静态头像与归档内容和未保存状态保留"]
        finally:bridge.close()
    report={"version":VERSION,"passed":len(checks),"failed":0,"checks":[{"test":name,"status":"PASS"} for name in checks]}
    Path("html_editor_flow_results.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False))

if __name__=="__main__":main()
