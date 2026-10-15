"""Project package and file icon checks, version 1.0.4. Hidden windows only."""
import copy,ctypes,json,os,struct,tempfile,time,tkinter as tk,zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from app import App
from workspace import VERSION,Workspace,restore_backup,file_hash
from native_drop import COMObject,FORMATETC,STGMEDIUM,POINTL,PVOID,DWORD,HRESULT,CALL,method

CHECKS=[]
def passed(name):CHECKS.append({"test":name,"status":"PASS"})
def rejects(action):
    try:action()
    except (ValueError,OSError,KeyError):return
    raise AssertionError("Invalid input accepted")
def drain(root,app):
    deadline=time.monotonic()+10
    while app.busy and time.monotonic()<deadline:
        root.update();time.sleep(.01)
    assert not app.busy

def main():
    with tempfile.TemporaryDirectory(prefix="research_package_flow_") as tmp:
        base=Path(tmp)
        os.environ["RESEARCH_WORKSPACE_CONFIG"]=str(base/"config")
        root=tk.Tk();root.withdraw()
        app=App(root)
        errors=[]
        root.report_callback_exception=lambda typ,e,tb:errors.append(repr(e))
        app.error=lambda e: (_ for _ in ()).throw(e)
        assert app.open_workspace(str(base/"source"))
        ws=app.ws
        project=ws.add_project("博士课题")
        folder=ws.add_project("第1章",project)
        nested=ws.add_project("实验资料",folder)
        sibling=ws.add_project("第2章",project)
        unrelated=ws.add_project("其他项目")
        first=ws.add_map(folder,"理论基础",starter=True)
        second=ws.add_map(nested,"实验记录",starter=True)
        third=ws.add_map(sibling,"研究方法",starter=True)
        fourth=ws.add_map(unrelated,"其他资料")
        n1=ws.data["mindmaps"][first]["rootNodeId"]
        n2=ws.data["mindmaps"][second]["rootNodeId"]
        n3=ws.data["mindmaps"][third]["rootNodeId"]
        n4=ws.data["mindmaps"][fourth]["rootNodeId"]
        kinds={}
        for name,kind in [("方案.DOCX","word"),("数据.xlsx","excel"),("报告.pptx","ppt"),
                          ("页面.html","html"),("笔记.md","markdown"),("图片.png","image")]:
            source=base/name
            source.write_bytes(("file byte fixture: "+name).encode("utf-8"))
            kinds[ws.import_attachment(n1,source)]=kind
        shared=next(iter(kinds))
        ws.data["nodes"][n2]["attachmentIds"].append(shared)
        resources=base/"页面资源";resources.mkdir()
        (resources/"assets").mkdir();(resources/"empty").mkdir()
        (resources/"index.html").write_text('<img src="assets/image.png">',encoding="utf-8")
        (resources/"assets/image.png").write_bytes(b"resource bytes")
        resource=ws.import_attachment(n2,resources,"index.html")
        extra=base/"其他.docx";extra.write_bytes(b"unselected bytes")
        excluded=ws.import_attachment(n4,extra)
        orphan_source=base/"归档笔记.txt";orphan_source.write_bytes(b"archived note")
        orphan=ws.import_attachment(n1,orphan_source)
        ws.data["nodes"][n1]["attachmentIds"].remove(orphan)
        ws.data["nodes"][n2]["title"]="实验记录\n多行内容"
        ws.data["nodes"][n2]["collapsed"]=True
        ws.data["nodes"][n2]["style"]={"background":"#124578","foreground":"#ffeedd"}
        ws.data["mindmaps"][second]["viewState"]["zoom"]=1.25
        app.refresh_projects();app.load_map(first)
        assert str(app.project_tree["selectmode"])=="extended"
        tree=app.project_tree
        # Call the native Treeview selection operations on the hidden widget.
        root.tk.call("ttk::treeview::SelectOp",str(tree),"m:"+first,"choose")
        root.tk.call("ttk::treeview::SelectOp",str(tree),"m:"+third,"toggle")
        app.select_project()
        assert set(tree.selection())=={"m:"+first,"m:"+third}
        root.tk.call("ttk::treeview::SelectOp",str(tree),"m:"+second,"choose")
        root.tk.call("ttk::treeview::SelectOp",str(tree),"m:"+third,"extend")
        assert "m:"+first in tree.selection() and "m:"+second in tree.selection() and "m:"+third in tree.selection()
        retained=tree.selection();app.refresh_projects()
        assert tree.selection()==retained
        tree.selection_set(["p:"+folder,"m:"+third])
        with patch.object(tree,"identify_row",return_value="p:"+folder),patch.object(app,"menu") as menu:
            app.project_context(SimpleNamespace(y=1,x_root=0,y_root=0))
            assert set(tree.selection())=={"p:"+folder,"m:"+third}
            assert any(call.kwargs.get("label")=="导出所选项目包…" for call in menu.return_value.add_command.call_args_list)
        app.project_press(SimpleNamespace(y=1,x=1,state=4));assert app.project_drag is None
        passed("左侧原生 Ctrl 切换、Shift 范围、多选保留及右键导出入口")

        package=base/"章节资料.rwp"
        with patch("app.filedialog.asksaveasfilename",return_value=str(package)):
            app.export_project_package()
        drain(root,app)
        with zipfile.ZipFile(package) as archive:
            assert archive.testzip() is None
            data=json.loads(archive.read("workspace.json"))
            assert set(data["mindmaps"])=={first,second,third}
            assert set(data["projects"])=={project,folder,nested,sibling}
            assert excluded not in data["attachments"]
            assert len(data["attachments"])==8 and orphan in data["attachments"]
            path=data["attachments"][shared]["relativePath"]
            assert archive.namelist().count(path)==1
        passed("多选文件夹和导图完整打包子树、共享附件去重及导出范围")

        restored=base/"restored"
        restore_backup(package,restored)
        reopened=Workspace(restored)
        assert reopened.data["projects"]==data["projects"]
        assert reopened.data["mindmaps"]==data["mindmaps"]
        assert reopened.data["nodes"]==data["nodes"]
        for item in data["attachments"]:
            original=ws.attachment_path(item);copy_path=reopened.attachment_path(item)
            if original.is_file():assert file_hash(original)==file_hash(copy_path)
            else:
                assert (copy_path/"empty").is_dir()
                assert file_hash(original/"assets/image.png")==file_hash(copy_path/"assets/image.png")
                assert reopened.attachment_path(item,True)==copy_path/"index.html"
        reopened.close()
        passed("项目包还原层级、全部节点内容样式、折叠缩放、附件字节及 HTML 资源入口")

        whole=base/"整个项目.rwp"
        ws.export_project_package(["p:"+project,"p:"+nested,"m:"+first],whole)
        with zipfile.ZipFile(whole) as archive:
            data2=json.loads(archive.read("workspace.json"))
            assert set(data2["mindmaps"])=={first,second,third}
        map_only=base/"单独导图.rwp";ws.export_project_package(["m:"+first],map_only)
        with zipfile.ZipFile(map_only) as archive:
            single=json.loads(archive.read("workspace.json"))
            assert set(single["mindmaps"])=={first} and orphan not in single["attachments"]
        empty_folder=ws.add_project("空文件夹",project)
        empty=base/"空文件夹.rwp";ws.export_project_package(["p:"+empty_folder],empty)
        restore_backup(empty,base/"empty-restored")
        empty_ws=Workspace(base/"empty-restored");assert not empty_ws.data["mindmaps"];empty_ws.close()
        before=package.read_bytes()
        rejects(lambda:ws.export_project_package(["p:"+project],package))
        assert package.read_bytes()==before
        passed("项目根层导出、重叠选择去重、空文件夹及已有文件保护")

        bad=base/"unsafe.rwp"
        with zipfile.ZipFile(bad,"w") as archive:
            archive.writestr("../escape.txt",b"escape")
            archive.writestr("workspace.json",json.dumps(data))
        rejects(lambda:restore_backup(bad,base/"unsafe-target"))
        assert not (base/"unsafe-target").exists() and not (base/"escape.txt").exists()
        missing=base/"missing.rwp"
        with zipfile.ZipFile(missing,"w") as archive:
            archive.writestr("project_package.json",json.dumps({"format":"ResearchWorkspaceProject","formatVersion":1}))
            archive.writestr("workspace.json",json.dumps(data))
        rejects(lambda:restore_backup(missing,base/"missing-target"))
        assert not (base/"missing-target").exists()
        passed("项目包路径边界和缺失附件校验")

        app.load_map(first);app.selected={n1};app.render()
        for item,kind in kinds.items():
            record=ws.data["attachments"][item]
            assert app.attachment_kind(record)==kind
            assert str(app.file_icons[kind]) in app.attach_tree.item(item,"image")
            shapes=[app.canvas.type(i) for i in app.canvas.find_withtag(item)]
            assert ("rectangle" if kind=="image" else "polygon") in shapes
        assert len({str(app.file_icons[kind]) for kind in kinds.values()})==6
        assert app.outline.item(n1,"image")
        passed("Word、Excel、PPT、HTML、Markdown、图片各有独立图形与颜色，覆盖导图大纲附件列表")

        ws.close();app.ws=None;app.map_id=None;app.dirty=False
        app.package_drop_bounds=(0,0,300,200)
        # A real CF_HDROP object containing the package; callbacks only enqueue.
        kernel=ctypes.windll.kernel32
        kernel.GlobalAlloc.argtypes=[ctypes.c_uint,ctypes.c_size_t];kernel.GlobalAlloc.restype=PVOID
        kernel.GlobalLock.argtypes=[PVOID];kernel.GlobalLock.restype=PVOID
        kernel.GlobalUnlock.argtypes=[PVOID]
        payload=struct.pack("<IiiII",20,0,0,0,1)+(str(package)+"\0\0").encode("utf-16-le")
        def get_data(this,form,medium):
            h=kernel.GlobalAlloc(0x42,len(payload));assert h
            memory=kernel.GlobalLock(h);ctypes.memmove(memory,payload,len(payload));kernel.GlobalUnlock(h)
            medium.contents.tymed=1;medium.contents.hGlobal=h;medium.contents.pUnkForRelease=None
            return 0
        callback=CALL(HRESULT,PVOID,ctypes.POINTER(FORMATETC),ctypes.POINTER(STGMEDIUM))(get_data)
        vtable=(PVOID*4)(None,None,None,ctypes.cast(callback,PVOID).value)
        obj=COMObject(ctypes.cast(vtable,ctypes.POINTER(PVOID)))
        target=ctypes.byref(app.native_drop.target.obj);effect=DWORD(1)
        enter=method(target,3,HRESULT,PVOID,DWORD,POINTL,ctypes.POINTER(DWORD))
        drop=method(target,6,HRESULT,PVOID,DWORD,POINTL,ctypes.POINTER(DWORD))
        with patch.object(root,"after",side_effect=AssertionError("Tk in COM callback")), \
             patch.object(root,"winfo_rootx",side_effect=AssertionError("Tk in COM callback")):
            enter(target,ctypes.byref(obj),0,POINTL(20,30),ctypes.byref(effect));assert effect.value==1
            drop(target,ctypes.byref(obj),0,POINTL(20,30),ctypes.byref(effect));assert effect.value==1
        assert app.native_drop_events.qsize()==1
        event=app.native_drop_events.get_nowait()
        assert event[2]==("package",None)
        import_parent=base/"imports";import_parent.mkdir()
        (import_parent/package.stem).mkdir()
        with patch("app.filedialog.askdirectory",return_value=str(import_parent)):
            app.accept_drop(event[1],event[2])
        drain(root,app)
        assert app.ws.root==import_parent/(package.stem+"_2")
        assert set(app.ws.data["mindmaps"])=={first,second,third}
        assert app.map_id in app.ws.data["mindmaps"]
        passed("空启动窗口接收项目包 OLE 拖入，队列还原到独立目录并打开导图")

        current=app.ws.root
        with patch("app.filedialog.askdirectory",return_value=""):
            app.open_project_package(str(package))
        assert app.ws.root==current and not app.busy
        with patch.object(app,"open_project_package") as open_package:
            app.handle_drop([str(package)],app.canvas,0,0)
            open_package.assert_called_once_with(str(package))
        with patch.object(app,"open_project_package") as open_package:
            app.accept_drop([str(package),str(extra)],("package",None))
            open_package.assert_not_called()
        app.ws.close();app.ws=None;app.native_drop.close();app.native_drop=None;root.destroy()
        assert not errors,errors
        passed("项目包打开取消、普通拖入分派及混合文件提示")
    report={"version":VERSION,"passed":len(CHECKS),"failed":0,"checks":CHECKS}
    Path("package_flow_results.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
