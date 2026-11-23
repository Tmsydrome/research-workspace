"""Local desktop export checks, version 1.0.11."""
import json,re,subprocess,tempfile
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from urllib.parse import quote
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
                with urlopen(url) as response:host=response.read().decode("utf-8")
                assert 'id="review"' in host and 'Workspace archive controls v1.0.11' in host
                assert 'event.isTrusted' in host and 'workspace-snapshot-result' in host
                review_url=bridge.render_origin+url[len(bridge.origin):].replace('/editor','/review')
                with urlopen(review_url) as response:html=response.read().decode("utf-8")
                assert 'HTML修订批注工具 v0.4.7' in html and 'id="toggleComments"' in html
                assert 'id="splitter"' in html and 'Workspace editor integration v1.0.11' in html
                assert '<div class="creator-profile" aria-label="Tmsydrome">' in html
                assert 'sandbox="allow-same-origin allow-scripts"' in html
                assert 'frame.src=location.pathname.replace(/review$/' in html
                assert 'restoreReviewBody(state.html)' in html
                assert not re.search(r'<a[^>]*class="creator-profile"',html)
                assert post("save",{"text":text,"etag":"fixture"},bridge.render_origin)[0]==403
                blocked=session+'files/'+quote(document.name)
                try:urlopen(blocked);raise AssertionError("Expected isolated resource origin")
                except HTTPError as error:assert error.code==403
                rendering_request=Request(review_url.replace('/review','/save'),b'{}',{"Content-Type":"application/json","Origin":bridge.origin})
                try:urlopen(rendering_request);raise AssertionError("Expected read-only renderer")
                except HTTPError as error:assert error.code==403
                scripts=re.findall(r'<script(?: type="module")?>(.*?)</script>',host+html,re.S)
                node="const vm=require('vm'),fs=require('fs');for(const script of JSON.parse(fs.readFileSync(0,'utf8')))new vm.Script(script);"
                subprocess.run(["node","-e",node],input=json.dumps(scripts),text=True,check=True,capture_output=True)
                assert document.read_bytes()==original and bridge.has_unsaved()
            checks=["直接导出桌面及原文与批注保留","同名文件编号与路径边界","错误来源和格式校验及失败清理",
                    "动态网页脚本入口、保存控件与渲染来源隔离","静态头像与归档内容和未保存状态保留"]
        finally:bridge.close()
    report={"version":VERSION,"passed":len(checks),"failed":0,"checks":[{"test":name,"status":"PASS"} for name in checks]}
    Path("html_editor_flow_results.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False))

if __name__=="__main__":main()
