"""Integration acceptance checks, version 1.0.1; test revision 1. Uses temporary fixtures only."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace
from workspace import (VERSION, Workspace, validate, branch, ordered_nodes, restore_backup,
                       contained, file_hash, html_warnings)

RESULTS=[]
def check(label, function):
    print("RUN",label,flush=True)
    start=time.monotonic()
    try:
        function()
        RESULTS.append({"test":label,"status":"PASS","seconds":round(time.monotonic()-start,3)})
    except Exception as e:
        RESULTS.append({"test":label,"status":"FAIL","error":repr(e)})
        import traceback
        traceback.print_exc()

def rejects(function):
    try:
        function()
    except (ValueError,FileNotFoundError,OSError):
        return
    raise AssertionError("Expected rejection")

def main():
    with tempfile.TemporaryDirectory(prefix="research_workspace_test_") as temporary:
        base=Path(temporary)
        ws=Workspace(base/"workspace")
        source=base/"source"
        source.mkdir()
        ids={}
        def hierarchy():
            p1=ws.add_project("研究项目")
            p2=ws.add_project("材料",p1)
            p3=ws.add_project("实验",p2)
            other=ws.add_project("影像研究")
            m1=ws.add_map(p3,"实验设计")
            m2=ws.add_map(other,"资料整理")
            ids.update(p1=p1,p2=p2,p3=p3,other=other,m1=m1,m2=m2,
                       root1=ws.data["mindmaps"][m1]["rootNodeId"],root2=ws.data["mindmaps"][m2]["rootNodeId"])
            ws.data["preferences"]["sidebarWidth"]=340
            ws.data["preferences"]["lastMindmap"]=m2
            ws.save()
            disk=json.loads(ws.metadata.read_text(encoding="utf-8"))
            assert len(disk["projects"])==4 and len(disk["mindmaps"])==2
            assert disk["preferences"]["sidebarWidth"]==340
            rejects(lambda:Workspace(ws.root))
        check("01 三层项目、两张导图、持久化及单实例锁",hierarchy)

        def tree_edit():
            a=ws.add_node(ids["root1"],"标题含中文")
            b=ws.add_node(ids["root1"],"第二分支")
            ids.update(a=a,b=b)
            for index in range(24):
                ws.add_node(a,f"数据 {index+1}")
            ws.checkpoint()
            ws.move_node(b,a)
            ws.data["nodes"][a]["collapsed"]=True
            assert ws.data["nodes"][b]["parentId"]==a
            assert ws.undo() and ws.data["nodes"][b]["parentId"]==ids["root1"]
            assert ws.undo(True) and ws.data["nodes"][b]["parentId"]==a
            rejects(lambda:ws.move_node(a,b))
            validate(ws.data)
            assert len(ordered_nodes(ws.data,ids["m1"]))==27
        check("02 二十余节点、移动、循环阻止、折叠及撤销重做",tree_edit)

        def rich_text():
            node=ws.data["nodes"][ids["a"]]
            node["bodyRichText"]={"text":"中文正文与高亮片段\n原始文字 😀","highlights":[{"start":0,"end":4,"color":"#fff0a6"}]}
            node["notes"]="样本备注关键字"
            node["style"]={"background":"#def4e4","foreground":"#172947"}
            ws.save()
            loaded=json.loads(ws.metadata.read_text(encoding="utf-8"))
            assert loaded["nodes"][ids["a"]]["bodyRichText"]==node["bodyRichText"]
            assert loaded["nodes"][ids["a"]]["notes"]==node["notes"]
        check("03 颜色、片段高亮、多行正文及备注保存",rich_text)

        def archive():
            # OOXML container fixtures exercise original-byte preservation; Office opening is a separate check.
            for suffix in [".docx",".xlsx"]:
                file=source/("成果"+suffix)
                with zipfile.ZipFile(file,"w") as z:
                    z.writestr("[Content_Types].xml","<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'/>")
                    z.writestr("fixture.txt","字节保留测试")
                ids[suffix]=ws.import_attachment(ids["a"],file)
            html=source/"index.html"
            html.write_text('<html><p>独立成果</p><img src="missing.png"><script src="https://example.com/a.js"></script></html>',encoding="utf-8")
            ids["html"]=ws.import_attachment(ids["a"],html)
            site=source/"HTML资源"
            (site/"assets").mkdir(parents=True)
            (site/"empty").mkdir()
            (site/"index.html").write_text('<html><link href="assets/site.css"><img src="assets/a.png"></html>',encoding="utf-8")
            (site/"assets/site.css").write_bytes(b"body{color:navy}")
            (site/"assets/a.png").write_bytes(b"fixture-image-bytes")
            ids["site"]=ws.import_attachment(ids["a"],site,"index.html")
            duplicate=source/"duplicate"
            duplicate.mkdir()
            (duplicate/"成果.docx").write_bytes(b"another document")
            ids["duplicate"]=ws.import_attachment(ids["root2"],duplicate/"成果.docx")
            ids["empty"]=ws.import_attachment(ids["a"],site/"empty")
            for f in source.glob("*.*"):
                f.unlink()
            assert ws.attachment_path(ids[".docx"]).exists()
            assert ws.attachment_path(ids["site"],True).read_text(encoding="utf-8").startswith("<html>")
            assert (ws.attachment_path(ids["site"])/"assets/site.css").exists()
            assert ws.attachment_path(ids["duplicate"]).read_bytes()==b"another document"
            ws.data["projects"][ids["p1"]]["name"]="项目重命名"
            assert ws.attachment_path(ids[".docx"]).exists()
            warnings=html_warnings(ws.attachment_path(ids["html"]),ws.attachment_path(ids["html"]).parent,False)
            assert any("远端" in w for w in warnings) and any("依赖" in w for w in warnings)
        check("04 多类型归档、同名文件、源文件移除与 HTML 资源目录",archive)

        def external_edit():
            p=ws.attachment_path(ids[".docx"])
            p.write_bytes(p.read_bytes()+b"external saved modification")
            old=p.read_bytes()
            ws.refresh_attachment(ids[".docx"])
            ws.save()
            assert p.read_bytes()==old and ws.data["attachments"][ids[".docx"]]["size"]==len(old)
        check("05 外部修改保留及附件大小刷新",external_edit)

        def basket():
            ws.basket_add("node",[ids["a"],ids["root2"]])
            ws.basket_add("attachment",[ids[".docx"]])
            ws.basket_add("node",[ids["a"]])
            assert len(ws.data["basket"])==3
            ws.data["nodes"][ids["b"]]["attachmentIds"].append(ids[".docx"])
            plan=ws.export_plan(ws.data["basket"],True)
            assert len(plan["attachments"])==6 and plan["duplicates"]==2
            ids["plan"]=plan
        check("06 跨项目选择篮、共享附件和 UUID 去重",basket)

        def exports():
            parent=base/"export"
            parent.mkdir()
            result=ws.export(ids["plan"],parent,False,True,True)
            result_zip=ws.export(ids["plan"],parent,True,True,True)
            assert result["failed"]==0 and result_zip["failed"]==0
            root=Path(result["output"])
            manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8"))
            assert manifest["nodes"] and "样本备注关键字" in (root/"outline.md").read_text(encoding="utf-8")
            assert all(not Path(a["path"]).is_absolute() for a in manifest["attachments"])
            assert all("sourceNodes" in a for a in manifest["attachments"])
            assert any(a["warnings"] for a in manifest["attachments"])
            with zipfile.ZipFile(result_zip["output"]) as z:
                assert z.testzip() is None
                for name in result["files"]:
                    assert z.read(name)==(root/name).read_bytes()
                assert {"manifest.json","README.md","outline.md"}.issubset(z.namelist())
            for a in manifest["attachments"]:
                for f in a["files"]:
                    assert file_hash(root/f["path"])==f["sha256"]
            assert sum(p.name=="成果.docx" for p in root.rglob("*"))==2
            ids["export_root"]=root
            plain=ws.export(ids["plan"],parent,False,False,False)
            plain_root=Path(plain["output"])
            assert not (plain_root/"outline.md").exists() and not (plain_root/"manifest.json").exists()
            rejects(lambda:ws.export(ids["plan"],ws.root,False))
        check("07 目录与 ZIP 字节一致、AI 来源/备注、文件模式及资源目录",exports)

        def search():
            for query in ["中文","备注关键字","成果.docx","实验设计","项目重命名"]:
                assert ws.search(query),query
            assert not ws.search("确定不存在的关键字")
        check("08 中文与部分搜索、附件名、备注及无结果",search)

        def backup_restore():
            backup=base/"backup.zip"
            ws.backup(backup)
            restored=restore_backup(backup,base/"restored")
            rw=Workspace(restored)
            try:
                assert rw.data["id"]==ws.data["id"]
                for a in ws.data["attachments"]:
                    p,q=ws.attachment_path(a),rw.attachment_path(a)
                    if p.is_file():
                        assert file_hash(p)==file_hash(q)
                    else:
                        assert p.is_dir() and q.is_dir()
                        for f in p.rglob("*"):
                            if f.is_file():
                                assert file_hash(f)==file_hash(q/f.relative_to(p))
            finally:
                rw.close()
            rejects(lambda:restore_backup(backup,restored))
            rejects(lambda:ws.backup(backup))
        check("09 工作区 ZIP 备份、独立目录恢复和附件校验",backup_restore)

        def recovery():
            ws.save()
            workspace_root=ws.root
            ws.close()
            workspace_root.joinpath("workspace.json").write_text("{broken",encoding="utf-8")
            recovered=Workspace(workspace_root)
            try:
                assert recovered.recovered_from
                assert recovered.data["projects"]
                recovered.save()
                assert list((workspace_root/"recovery").glob("*.json"))
            finally:
                recovered.close()
            stale=workspace_root/".workspace.lock"
            stale.write_text(json.dumps({"pid":4294967294}),encoding="utf-8")
            reopened=Workspace(workspace_root)
            reopened.close()
        check("10 损坏元数据快照恢复、损坏副本保留和异常退出锁恢复",recovery)

        def boundaries():
            for relative in ["../outside.txt","projects/../../outside.txt","C:/outside.txt","/outside.txt"]:
                rejects(lambda r=relative:contained(base/"workspace",r))
            bad=base/"bad.zip"
            with zipfile.ZipFile(bad,"w") as z:
                z.writestr("../escape.txt","bad")
                z.writestr("workspace.json",json.dumps(ws.data))
            rejects(lambda:restore_backup(bad,base/"bad_restore"))
            assert not (base/"escape.txt").exists()
            cycle=copy.deepcopy(ws.data)
            cycle["projects"][ids["p1"]]["parentId"]=ids["p3"]
            rejects(lambda:validate(cycle))
            link=base/"junction_source"
            if os.name=="nt":
                subprocess.run(["cmd","/c","mklink","/J",str(link),str(base/"export")],
                               check=True,capture_output=True)
                try:
                    rejects(lambda:Workspace(link))
                finally:
                    os.rmdir(link)
        check("11 路径越界、恶意 ZIP、循环和 Windows 重解析点阻止",boundaries)

        def gui():
            import tkinter as tk
            from app import App
            os.environ["RESEARCH_WORKSPACE_CONFIG"]=str(base/"config")
            root=tk.Tk()
            root.withdraw()
            app=App(root)
            errors=[]
            root.report_callback_exception=lambda typ,e,tb:errors.append(repr(e))
            # Prevent startup's directory dialog by providing a chosen workspace immediately.
            app.config["workspace"]=str(base/"gui_workspace")
            app.open_workspace(str(base/"gui_workspace"))
            p=app.ws.add_project("界面项目")
            m=app.ws.add_map(p,"界面导图")
            r=app.ws.data["mindmaps"][m]["rootNodeId"]
            a=app.ws.add_node(r,"界面节点 A")
            b=app.ws.add_node(r,"界面节点 B")
            app.load_map(m)
            app.select_node(a)
            app.select_node(b,ctrl=True)
            assert app.selected=={a,b}
            app.view.set("outline")
            app.show_view()
            assert app.selected=={a,b}
            assert set(app.outline.selection())=={a,b}
            app.view.set("map")
            app.show_view()
            assert app.selected=={a,b}
            app.load_editor(b)
            app.body.insert("1.0","界面正文 😀 中文")
            root.update()
            app.editor_changed()
            assert app.ws.data["nodes"][b]["bodyRichText"]["text"]=="界面正文 😀 中文"
            app.add_highlight_tag(0,4,"#fff0a6")
            app.editor_changed()
            assert app.ws.data["nodes"][b]["bodyRichText"]["highlights"][0]["end"]==4
            app.selected={a}
            app.focus_node=a
            app.ws.basket_add("node",[a])
            assert app.ws.data["basket"][0]["id"]==a
            root.deiconify()
            root.update()
            app.main.sash_place(0,325,0)
            app.sidebar_resize()
            assert app.ws.data["preferences"]["sidebarWidth"]==325
            app.toggle_sidebar()
            app.toggle_sidebar()
            app.change_zoom(.8)
            app.fit_view()
            for _ in range(5):
                root.update()
                time.sleep(.04)
            assert not errors,errors
            assert app.save()
            from unittest.mock import patch
            with patch("app.messagebox.askyesnocancel",return_value=True):app.close()
            persisted=Workspace(base/"gui_workspace")
            assert persisted.data["preferences"]["lastMindmap"]==m
            assert persisted.data["nodes"][b]["bodyRichText"]["highlights"]
            persisted.close()
        if "--headless" not in sys.argv:
            check("12 原生 Tk 界面、双视图多选、正文高亮、侧栏与保存",gui)

    summary={"version":VERSION,"testRevision":1,"passed":sum(r["status"]=="PASS" for r in RESULTS),
             "failed":sum(r["status"]=="FAIL" for r in RESULTS),"checks":RESULTS}
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    if "--report" in sys.argv:
        Path(sys.argv[sys.argv.index("--report")+1]).write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    return int(summary["failed"]>0)
if __name__=="__main__":
    raise SystemExit(main())
