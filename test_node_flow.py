"""Hidden-window regression checks for Research Workspace 1.0.4."""
import ctypes,json,os,struct,tempfile,time,tkinter as tk
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from workspace import VERSION,Workspace,file_hash,children,branch
from app import App
from themes import THEMES,SELECTION_EDGE
from native_drop import COMObject,FORMATETC,STGMEDIUM,POINTL,PVOID,DWORD,HRESULT,CALL,method
CHECKS=[]
def passed(label):
    CHECKS.append({"test":label,"status":"PASS"})
def main():
    with tempfile.TemporaryDirectory(prefix="research_node_flow_") as tmp:
        base=Path(tmp)
        os.environ["RESEARCH_WORKSPACE_CONFIG"]=str(base/"config")
        root=tk.Tk();root.withdraw()
        errors=[]
        root.report_callback_exception=lambda typ,e,tb:errors.append(repr(e))
        app=App(root,str(base/"workspace"))
        app.open_workspace(str(base/"workspace"))
        app.config["workspace"]=str(base/"workspace")
        project=app.ws.add_project("研究")
        mindmap=app.ws.add_map(project,"研究主题",starter=True)
        node=app.ws.data["mindmaps"][mindmap]["rootNodeId"]
        assert len(app.ws.data["nodes"])==4
        assert app.ws.data["preferences"]["theme"]=="ocean"
        app.load_map(mindmap)
        passed("初始根节点和三级子节点、深蓝默认主题")
        first_child=children(app.ws.data,node)[0]
        second_child=children(app.ws.data,first_child)[0]
        leaf=children(app.ws.data,second_child)[0]
        original_nodes=json.dumps(app.ws.data["nodes"],sort_keys=True)
        selection=set(app.selected)
        def fold_event(i):
            x1,y1,x2,y2=app.fold_hits[i]
            assert x2-x1>=24 and y2-y1>=24
            return SimpleNamespace(x=(x1+x2)/2-app.canvas.canvasx(0),
                                   y=(y1+y2)/2-app.canvas.canvasy(0),state=0)
        assert set(app.fold_hits)=={node,first_child,second_child} and leaf not in app.fold_hits
        with patch.object(app,"open_attachment") as opened:
            e=fold_event(node)
            assert app.canvas_press(e)=="break"
            app.canvas_release(e)
            assert not opened.called and app.drag is None
        assert app.visible==[node] and not app.outline.item(node,"open")
        assert app.selected==selection and len(app.ws.data["nodes"])==4
        app.undo();assert len(app.visible)==4 and app.outline.item(node,"open")
        app.undo(True);assert app.visible==[node]
        app.canvas_press(fold_event(node))
        assert json.dumps(app.ws.data["nodes"],sort_keys=True)==original_nodes
        passed("导图折叠按钮命中、整分支收放、内容保留、撤销重做及选择保留")
        app.toggle_node(second_child)
        app.toggle_node(first_child)
        app.toggle_node(first_child)
        assert second_child in app.visible and leaf not in app.visible
        app.toggle_node(second_child)
        app.outline.focus(first_child)
        app.outline.event_generate("<<TreeviewClose>>")
        assert app.ws.data["nodes"][first_child]["collapsed"] and second_child not in app.boxes
        app.outline.event_generate("<<TreeviewOpen>>")
        assert not app.ws.data["nodes"][first_child]["collapsed"] and leaf in app.boxes
        app.canvas.xview_moveto(.2);app.canvas.yview_moveto(.1)
        assert app.fold_at(fold_event(first_child).x,fold_event(first_child).y)==first_child
        app.canvas.xview_moveto(0);app.canvas.yview_moveto(0)
        app.set_collapsed(first_child,True);assert app.save()
        on_disk=json.loads((app.ws.root/"workspace.json").read_text(encoding="utf-8"))
        assert on_disk["nodes"][first_child]["collapsed"]
        app.set_collapsed(first_child,False)
        passed("嵌套折叠状态保留、双视图事件同步、滚动后按钮命中及保存")
        for palette in THEMES.values():
            app.theme=palette;app.apply_theme();app.select_node(first_child)
            assert app.style.lookup("Outline.Treeview","background",("selected",))==palette["outline_selection"]
            assert int(app.style.lookup("Outline.Treeview","indicatorsize"))==21
            checked=app.outline_image(first_child)
            assert checked.width()>=32 and checked.height()==32
            assert str(checked) in app.outline.item(first_child,"image")
            assert "☑" not in app.outline.item(first_child,"text")
            assert any(app.canvas.itemcget(item,"outline")==SELECTION_EDGE for item in app.canvas.find_withtag(first_child)
                       if app.canvas.type(item)=="polygon")
        app.theme=THEMES["ocean"];app.apply_theme();app.select_node(node)
        for zoom in (.2,.6,1,2.5):
            app.zoom=zoom;app.render()
            for i,box in app.fold_hits.items():
                assert box[2]-box[0]>=24
                for child_id in children(app.ws.data,i):
                    if child_id in app.boxes:assert box[2]<=app.boxes[child_id][0]
        app.zoom=1;app.render()
        passed("五套主题淡色选择、大纲大箭头与勾选图标、缩放按钮点击空间")
        legacy=app.ws.data["nodes"][node]
        legacy.update(title="研究主题",bodyRichText={"text":"既有内容","highlights":[]},notes="补充记录")
        expected="研究主题\n既有内容\n补充记录"
        assert app.node_content(node)==expected
        app.render();app.edit_title(node)
        assert app.inline_edit["entry"].get("1.0","end-1c")==expected
        app.finish_inline(False)
        assert legacy["notes"]=="补充记录"
        app.edit_title(node)
        entry=app.inline_edit["entry"]
        entry.delete("1.0","end");entry.insert("1.0","统一内容\n第二行 😀")
        app.finish_inline()
        assert app.node_content(node)=="统一内容\n第二行 😀"
        assert legacy["bodyRichText"]["text"]==legacy["notes"]==""
        assert app.outline["columns"]==("files",)
        app.edit_title(node);app.inline_tab(None)
        child=app.focus_node
        assert app.ws.data["nodes"][child]["parentId"]==node
        passed("隐藏 Tk 多行原位编辑、取消保留、统一保存、Tab 子节点")
        app.view.set("outline");app.show_view()
        with patch.object(app.outline,"bbox",return_value=(0,20,600,30)):
            app.edit_title(child)
            assert app.inline_edit and app.inline_edit["node"]==child
            app.inline_edit["entry"].delete("1.0","end")
            app.inline_edit["entry"].insert("1.0","大纲内容\\n第二行")
            app.finish_inline()
        assert app.node_content(child)=="大纲内容\\n第二行"
        with patch.object(app.outline,"winfo_viewable",return_value=True), \
             patch.object(app.outline,"bbox",side_effect=lambda i: (0,20,600,30) if i==child else ""), \
             patch.object(app.outline,"winfo_rootx",return_value=100), \
             patch.object(app.outline,"winfo_rooty",return_value=200):
            app.refresh_drop_regions()
            assert app.native_location(120,230)==("node",child)
            with patch.object(root,"after_idle") as scheduled:
                app.outline_scrolled("0.2","0.8")
                assert scheduled.call_args.args[0]==app.refresh_drop_regions
        app.view.set("map");app.show_view()
        passed("隐藏大纲原位多行编辑、行坐标命中及滚动刷新")
        # CF_HDROP data passed through an actual ctypes IDataObject vtable.
        sources=[]
        for name,data in (("参考资料.html",b'<!doctype html><h1>Research</h1><a href="https://example.com/reference">Link</a>'),
                          ("研究方案.docx",b"archive-word-bytes"),("数据表.xlsx",b"archive-excel-bytes")):
            p=base/name;p.write_bytes(data);sources.append(p)
        kernel=ctypes.windll.kernel32
        kernel.GlobalAlloc.argtypes=[ctypes.c_uint,ctypes.c_size_t];kernel.GlobalAlloc.restype=PVOID
        kernel.GlobalLock.argtypes=[PVOID];kernel.GlobalLock.restype=PVOID
        kernel.GlobalUnlock.argtypes=[PVOID]
        payload=struct.pack("<IiiII",20,0,0,0,1)+("\0".join(map(str,sources))+"\0\0").encode("utf-16-le")
        def get_data(this,form,medium):
            assert form.contents.cfFormat==15 and form.contents.tymed==1
            h=kernel.GlobalAlloc(0x42,len(payload))
            assert h
            memory=kernel.GlobalLock(h)
            ctypes.memmove(memory,payload,len(payload));kernel.GlobalUnlock(h)
            medium.contents.tymed=1;medium.contents.hGlobal=h;medium.contents.pUnkForRelease=None
            return 0
        get_cb=CALL(HRESULT,PVOID,ctypes.POINTER(FORMATETC),ctypes.POINTER(STGMEDIUM))(get_data)
        table=(PVOID*4)(None,None,None,ctypes.cast(get_cb,PVOID).value)
        obj=COMObject(ctypes.cast(table,ctypes.POINTER(PVOID)))
        target=ctypes.byref(app.native_drop.target.obj)
        app.drop_regions=[(("node",child),(10,10,150,100))]
        app.drop_exclusion=None
        effect=DWORD(1)
        enter=method(target,3,HRESULT,PVOID,DWORD,POINTL,ctypes.POINTER(DWORD))
        over=method(target,4,HRESULT,DWORD,POINTL,ctypes.POINTER(DWORD))
        drop=method(target,6,HRESULT,PVOID,DWORD,POINTL,ctypes.POINTER(DWORD))
        # Native callbacks must use snapshots and a queue; Tcl access fails this check.
        with patch.object(app.root,"after",side_effect=AssertionError("Tk called in OLE callback")), \
             patch.object(app.canvas,"delete",side_effect=AssertionError("Tk called in OLE callback")):
            assert enter(target,ctypes.byref(obj),0,POINTL(20,30),ctypes.byref(effect))==0 and effect.value==1
            over(target,0,POINTL(200,300),ctypes.byref(effect));assert effect.value==0
            over(target,0,POINTL(20,30),ctypes.byref(effect));assert effect.value==1
            drop(target,ctypes.byref(obj),0,POINTL(20,30),ctypes.byref(effect));assert effect.value==1
        assert app.native_drop_events.qsize()==1
        passed("注册/COM vtable/CF_HDROP 多文件解析、落点效果、回调仅排队")
        app.poll_drop_events()
        deadline=time.monotonic()+8
        while app.busy and time.monotonic()<deadline:
            root.update();time.sleep(.01)
        assert not app.busy
        file_nodes=children(app.ws.data,child)
        assert len(file_nodes)==3
        assert app.ws.data["nodes"][child]["attachmentIds"]==[]
        for i,p in zip(file_nodes,sources):
            n=app.ws.data["nodes"][i];assert n["title"]==p.name and len(n["attachmentIds"])==1
            a=n["attachmentIds"][0]
            assert file_hash(p)==file_hash(app.ws.attachment_path(a))
            assert (i,a) in app.attachment_hits
        assert app.focus_node==file_nodes[-1]
        passed("队列到后台复制，HTML/Word/Excel 各创建文件名子节点，原件与副本字节一致")
        a=app.ws.data["nodes"][file_nodes[0]]["attachmentIds"][0]
        with patch("app.os.startfile") as opener, \
             patch("app.messagebox.askyesno",side_effect=AssertionError("Unexpected open prompt")), \
             patch("html_editor.HtmlEditor.open",side_effect=AssertionError("Unexpected built-in editor")):
            for attachment_node in file_nodes[1:]:
                attachment=app.ws.data["nodes"][attachment_node]["attachmentIds"][0]
                app.open_attachment(attachment)
                assert opener.call_args.args[0]==str(app.ws.attachment_path(attachment,True))
            unknown=base/"附件.custom";unknown.write_bytes(b"other file fixture")
            unknown_id=app.ws.import_attachment(child,unknown)
            app.open_attachment(unknown_id)
            assert opener.call_args.args[0]==str(app.ws.attachment_path(unknown_id,True))
            app.ws.data["nodes"][child]["attachmentIds"].remove(unknown_id)
        passed("Word、Excel 和其他扩展名直接调用系统默认应用")
        with patch("html_editor.HtmlEditor.open",return_value="test") as opener, \
             patch("app.os.startfile") as system_open, \
             patch("app.messagebox.askyesno",side_effect=AssertionError("Unexpected HTML open prompt")):
            app.open_attachment(a)
            assert opener.call_args.args[1]==app.ws.attachment_path(a,True)
            system_open.assert_not_called()
        app.html_bridge.close();app.html_bridge=None
        passed("HTML 默认打开软件内置修订批注工具并加载归档副本")
        app.select_node(file_nodes[0]);app.select_node(file_nodes[2],ctrl=True)
        shown=app.attach_tree.get_children()
        assert len(shown)==2 and set(shown)==set(app.selected_attachment_ids())
        assert "2 节点" in app.attachment_summary.get()
        assert "2 个附件" in app.export_button["text"]
        assert app.inspector_tabs.select()==str(app.attachment_panel)
        graphic=[app.canvas.type(item) for item in app.canvas.find_withtag(a)]
        assert "polygon" in graphic and "text" in graphic
        assert not any(app.canvas.itemcget(item,"text")=="↗" for item in app.canvas.find_all() if app.canvas.type(item)=="text")
        assert not any("选择篮" in w.cget("text") for w in app.toolbar.winfo_children() if w.winfo_class() in ("TButton","Button"))
        assert "篮" not in app.count_var.get()
        passed("多选节点右侧汇总、文件类型图形、简化工具栏和状态")
        export_parent=base/"exports";export_parent.mkdir()
        def export_now(ids):
            if ids:app.attach_tree.selection_set(ids)
            else:app.attach_tree.selection_remove(*app.attach_tree.selection())
            with patch("app.filedialog.askdirectory",return_value=str(export_parent)) as chooser:
                app.export_selected_attachments()
                chooser.assert_called_once()
            deadline=time.monotonic()+8
            while app.busy and time.monotonic()<deadline:root.update();time.sleep(.01)
            assert not app.busy and app.last_export["failed"]==0
            return Path(app.last_export["output"])
        output=export_now([a])
        assert sorted(p.name for p in output.iterdir())==[sources[0].name]
        assert file_hash(output/sources[0].name)==file_hash(sources[0])
        output=export_now([])
        assert {p.name for p in output.iterdir()}=={sources[0].name,sources[2].name}
        passed("右侧勾选部分或全部附件直接选择目录导出，文件名及字节保留")
        duplicate_dir=base/"duplicate";duplicate_dir.mkdir()
        duplicate_file=duplicate_dir/sources[0].name;duplicate_file.write_bytes(b"<h1>Different source</h1>")
        duplicate_node=app.ws.add_node(child,duplicate_file.name)
        duplicate_id=app.ws.import_attachment(duplicate_node,duplicate_file)
        shared_node=app.ws.add_node(child,"共享资料")
        app.ws.data["nodes"][shared_node]["attachmentIds"].append(a)
        folder=base/"resourceFolder";folder.mkdir()
        (folder/"index.html").write_text('<link href="style.css" rel="stylesheet">',encoding="utf-8")
        (folder/"style.css").write_text("body{color:navy}",encoding="utf-8")
        folder_node=app.ws.add_node(child,"网页资源")
        folder_id=app.ws.import_attachment(folder_node,folder,"index.html")
        with patch("html_editor.HtmlEditor.open",return_value="test") as opener, \
             patch("app.os.startfile") as system_open:
            app.open_attachment(folder_id)
            assert opener.call_args.args[1]==app.ws.attachment_path(folder_id,True)
            assert opener.call_args.args[2]==app.ws.attachment_path(folder_id)
            system_open.assert_not_called()
        app.html_bridge.close();app.html_bridge=None
        app.selected={file_nodes[0],duplicate_node,shared_node,folder_node}
        app.focus_node=file_nodes[0];app.render();app.load_editor(app.focus_node)
        assert len(app.attach_tree.get_children())==3
        output=export_now([])
        exported=list(output.glob("*.html"))
        assert len(exported)==2 and len({p.name.casefold() for p in exported})==2
        assert {file_hash(p) for p in exported}=={file_hash(sources[0]),file_hash(duplicate_file)}
        assert file_hash(output/folder.name/"style.css")==file_hash(folder/"style.css")
        assert not (output/"manifest.json").exists() and not (output/"outline.md").exists()
        passed("共享附件去重、同名附件独立命名、资源目录完整复制")
        with patch("app.filedialog.askdirectory",return_value=""):
            app.export_selected_attachments()
        assert not app.busy
        app.select_node(next(i for i,n in app.ws.data["nodes"].items() if not children(app.ws.data,i) and not n["attachmentIds"]))
        assert not app.attach_tree.get_children() and app.export_button.instate(["disabled"])
        passed("取消目录选择与附件空列表状态")
        app.ws.data["nodes"][child]["collapsed"]=True
        app.render();app.select_node(child)
        expected=set(branch(app.ws.data,child))
        assert app.selected==expected and app.focus_node==child
        expected_files=set(app.selected_attachment_ids())
        assert expected_files and set(app.attach_tree.get_children())==expected_files
        assert set(app.attach_tree.selection())==expected_files
        clicked=app.ws.data["nodes"][file_nodes[2]]["attachmentIds"][0]
        with patch.object(app.attach_tree,"identify_row",return_value=clicked), \
             patch.object(app,"menu") as menu,patch.object(app,"open_attachment") as opened:
            app.attachment_context(SimpleNamespace(y=0,x_root=0,y_root=0))
            action=next(c.kwargs["command"] for c in menu.return_value.add_command.call_args_list
                        if c.kwargs.get("label")=="打开附件")
            action();opened.assert_called_once_with(clicked)
        app.attach_tree.selection_set([a])
        app.render()
        assert set(app.attach_tree.selection())=={a}
        app.select_node(child,ctrl=True)
        assert not app.selected and not app.attach_tree.get_children()
        app.select_node(child,ctrl=True)
        assert app.selected==expected and set(app.attach_tree.selection())==expected_files
        app.ws.data["nodes"][child]["collapsed"]=False
        app.render()
        app.select_node(file_nodes[0])
        app.outline.selection_set(child);app.outline.focus(child);app.outline_select()
        assert app.selected==expected and app.focus_node==child
        assert set(app.outline.selection())==expected
        assert set(app.attach_tree.selection())==expected_files
        passed("选择父节点包含折叠后代，Ctrl 整分支切换，大纲和右侧附件自动全选")
        # Failed file copies clean up their provisional child node.
        before=set(app.ws.data["nodes"])
        app.select_node(child)
        with patch("app.messagebox.showwarning"):
            app.import_files(paths=[base/"missing.html"],file_nodes=True)
            deadline=time.monotonic()+8
            while app.busy and time.monotonic()<deadline:root.update();time.sleep(.01)
        assert set(app.ws.data["nodes"])==before and not app.busy
        passed("失败复制清理临时子节点、保留已有资料")
        app.select_node(file_nodes[0]);selected=set(app.selected)
        data_before=json.dumps(app.ws.data["nodes"],sort_keys=True)
        app.canvas.configure(scrollregion=(0,0,3200,2400))
        app.canvas.xview_moveto(.3);app.canvas.yview_moveto(.3)
        origin=(app.canvas.canvasx(0),app.canvas.canvasy(0))
        before_items=app.canvas.find_all()
        with patch.object(app,"node_at",return_value=None), \
             patch.object(app,"render",side_effect=AssertionError("Full render while panning")):
            app.canvas_press(SimpleNamespace(x=120,y=120,state=0))
            assert app.drag["pan"] and app.canvas["cursor"]=="hand2"
            app.canvas_motion(SimpleNamespace(x=160,y=190,state=0))
            moved=(app.canvas.canvasx(0),app.canvas.canvasy(0))
            assert tuple(moved[i]-origin[i] for i in (0,1))==(-40.,-70.)
            app.canvas_release(SimpleNamespace(x=160,y=190,state=0))
            assert app.drag is None and app.selected==selected
            app.canvas.xview_moveto(0);app.canvas.yview_moveto(0)
            edge_origin=(app.canvas.canvasx(0),app.canvas.canvasy(0))
            app.canvas_press(SimpleNamespace(x=120,y=120,state=0))
            app.canvas_motion(SimpleNamespace(x=160,y=190,state=0))
            edge_moved=(app.canvas.canvasx(0),app.canvas.canvasy(0))
            assert tuple(edge_moved[i]-edge_origin[i] for i in (0,1))==(-40.,-70.)
            app.canvas_release(SimpleNamespace(x=160,y=190,state=0))
        assert json.dumps(app.ws.data["nodes"],sort_keys=True)==data_before
        assert app.canvas.find_withtag("drag-ghost")==()
        passed("空白处左键自动手掌平移、位移准确、保留选择和内容、复用画布")
        short=app.ws.add_node(node,"短节点")
        long=app.ws.add_node(node,"不同长度的节点内容 "*12)
        short_child=app.ws.add_node(short,"短分支下的子节点")
        long_child=app.ws.add_node(long,"长分支下的子节点")
        for zoom in (.6,1.,1.8):
            app.zoom=zoom;app.render()
            for i in app.visible:
                parent=app.ws.data["nodes"][i]["parentId"]
                if parent in app.boxes:
                    assert abs(app.boxes[i][0]-app.boxes[parent][2]-56*zoom)<.0001
            assert app.boxes[short_child][0]<app.boxes[long_child][0]
            for pos,i in enumerate(app.visible):
                a_box=app.boxes[i]
                for j in app.visible[pos+1:]:
                    b_box=app.boxes[j]
                    assert not (min(a_box[2],b_box[2])>max(a_box[0],b_box[0]) and
                                min(a_box[3],b_box[3])>max(a_box[1],b_box[1]))
        passed("各父子节点恒定短间距、不同分支独立位置、三种缩放及框体互不重叠")
        saved=app.ws.root;assert app.save()
        with patch("app.messagebox.askyesnocancel",return_value=True):app.close()
        ws=Workspace(saved)
        assert len(children(ws.data,child))==6
        assert ws.data["nodes"][node]["title"]=="统一内容\n第二行 😀"
        ws.close();assert not errors,errors
        passed("多行内容、附件子节点保存重开与 OLE 注销")
    result={"version":VERSION,"passed":len(CHECKS),"failed":0,"checks":CHECKS}
    Path("node_flow_results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
