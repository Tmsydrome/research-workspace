"""Project folder, deletion and explicit-save checks, version 1.0.1."""
import json,os,tempfile,tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from app import App
from workspace import VERSION,Workspace,children
CHECKS=[]
def passed(name):CHECKS.append({"test":name,"status":"PASS"})
def hidden_app(base,config):
    os.environ["RESEARCH_WORKSPACE_CONFIG"]=str(base/config)
    root=tk.Tk();root.withdraw()
    app=App(root)
    root.report_callback_exception=lambda typ,e,tb: (_ for _ in ()).throw(e)
    app.error=lambda e: (_ for _ in ()).throw(e)
    return root,app
def main():
    with tempfile.TemporaryDirectory(prefix="research_project_flow_") as tmp, \
         patch("app.messagebox.askyesno",side_effect=AssertionError("Unexpected deletion popup")):
        base=Path(tmp)
        root,app=hidden_app(base,"config1")
        path=base/"课题项目"
        assert app.github_avatar.width()==32 and app.github_avatar.height()==32
        assert app.github_button["text"]=="Tmsydrome" and app.github_button["image"]
        widgets=app.search_group.winfo_children()
        assert widgets.index(app.github_button)+1==widgets.index(app.search_entry)
        with patch("app.webbrowser.open_new_tab") as browser:
            app.github_button.invoke()
            browser.assert_called_once_with("https://github.com/Tmsydrome")
        passed("GitHub 头像与名称位于搜索框左侧，按钮打开本人主页")
        assert app.ws is None
        with patch("app.filedialog.askdirectory",return_value=str(path)) as choose, \
             patch("app.simpledialog.askstring",return_value="博士课题"):
            app.add_project()
            choose.assert_called_once()
        assert app.ws.root==path.resolve()
        assert len(app.ws.data["projects"])==1 and not app.ws.data["mindmaps"]
        project=next(iter(app.ws.data["projects"]))
        assert (path/"workspace.json").exists() and not app.dirty
        passed("新项目选择独立本地目录，初始项目文件保存，导图按章节创建")
        with patch("app.simpledialog.askstring",return_value="文献资料"):
            app.add_folder(project)
        folder=next(i for i in app.ws.data["projects"] if i!=project)
        assert app.ws.data["projects"][folder]["parentId"]==project
        assert not app.ws.data["mindmaps"]
        maps=[]
        for chapter in range(1,8):
            app.project_tree.selection_set("p:"+project)
            with patch("app.simpledialog.askstring",return_value=f"第{chapter}章"):
                app.add_map()
            maps.append(app.map_id)
        app.project_tree.selection_set("p:"+folder)
        with patch("app.simpledialog.askstring",return_value="资料导图"):app.add_map()
        folder_map=app.map_id
        assert len(app.ws.data["mindmaps"])==8
        assert all(app.ws.data["mindmaps"][i]["projectId"]==project for i in maps)
        assert app.ws.data["mindmaps"][folder_map]["projectId"]==folder
        assert all(len(app.ws.data["nodes"])>=4 for i in maps)
        passed("项目直属七章导图，子文件夹独立导图，建文件夹后按需建图")
        active=app.ws.data["mindmaps"][folder_map]["rootNodeId"]
        leaf=children(app.ws.data,active)[0]
        app.select_node(leaf);app.delete_nodes()
        assert leaf not in app.ws.data["nodes"] and not app.outline.exists(leaf)
        app.undo();assert leaf in app.ws.data["nodes"]
        app.undo(True);assert leaf not in app.ws.data["nodes"]
        app.undo()
        passed("节点直接删除、界面同步、撤销及重做")
        app.select_node(active);app.delete_nodes()
        assert folder_map not in app.ws.data["mindmaps"] and not app.project_tree.exists("m:"+folder_map)
        app.undo()
        assert folder_map in app.ws.data["mindmaps"] and app.project_tree.exists("m:"+folder_map)
        passed("根节点直接删除整张导图并可撤销")
        app.load_map(folder_map);app.project_tree.selection_set("m:"+folder_map)
        app.shortcut("delete",SimpleNamespace(widget=app.project_tree))
        assert folder_map not in app.ws.data["mindmaps"]
        assert not app.project_tree.exists("m:"+folder_map)
        assert app.map_id in app.ws.data["mindmaps"]
        app.undo()
        passed("左侧导图 Delete 正确删除当前导图，刷新切换有效图")
        app.load_map(folder_map);app.project_tree.selection_set("p:"+folder)
        app.selection_source="project";app.delete_selection()
        assert folder not in app.ws.data["projects"] and folder_map not in app.ws.data["mindmaps"]
        assert not app.project_tree.exists("p:"+folder)
        assert len(app.ws.data["mindmaps"])==7
        assert app.save()
        persisted=json.loads((path/"workspace.json").read_text(encoding="utf-8"))
        assert folder not in persisted["projects"] and folder_map not in persisted["mindmaps"]
        app.undo()
        passed("左侧文件夹及其导图删除，保存后元数据同步，撤销恢复")
        app.delete_project_item("p",project)
        assert not app.ws.data["projects"] and not app.ws.data["mindmaps"]
        assert app.map_id is None and not app.project_tree.get_children()
        assert not app.attach_tree.get_children()
        app.undo();assert project in app.ws.data["projects"]
        passed("整个项目结构删除到空状态及恢复，界面刷新完整")
        active=app.ws.data["mindmaps"][app.map_id]["rootNodeId"]
        app.edit_title(active)
        entry=app.inline_edit["entry"];entry.delete("1.0","end");entry.insert("1.0","手动保存内容")
        assert app.save() and app.inline_edit is None
        saved=json.loads((path/"workspace.json").read_text(encoding="utf-8"))
        assert saved["nodes"][active]["title"]=="手动保存内容"
        assert root.bind_all("<Control-s>")
        assert any(w.cget("text")=="保存" for w in app.toolbar.winfo_children() if w.winfo_class()=="TButton")
        passed("左上保存按钮、Ctrl+S 绑定、保存提交原位编辑内容")
        app.ws.data["nodes"][active]["title"]="关闭时不保存";app.changed()
        assert app.save_job is None and app.dirty
        assert json.loads((path/"workspace.json").read_text(encoding="utf-8"))["nodes"][active]["title"]=="手动保存内容"
        with patch("app.messagebox.askyesnocancel",return_value=None) as prompt:
            app.close();prompt.assert_called_once()
        assert root.winfo_exists() and app.dirty
        with patch("app.messagebox.askyesnocancel",return_value=False):app.close()
        ws=Workspace(path);assert ws.data["nodes"][active]["title"]=="手动保存内容";ws.close()
        passed("关闭必问保存：取消保留窗口，不保存保留上次保存的内容")
        root,app=hidden_app(base,"config2")
        app.open_workspace(str(path))
        app.ws.data["nodes"][active]["title"]="关闭时保存";app.changed()
        other=base/"第二项目"
        with patch("app.messagebox.askyesnocancel",return_value=None):
            assert app.open_workspace(str(other)) is False
        assert app.ws.root==path.resolve() and not other.exists()
        with patch("app.messagebox.askyesnocancel",return_value=True):
            assert app.open_workspace(str(other))
        old=Workspace(path);assert old.data["nodes"][active]["title"]=="关闭时保存";old.close()
        assert not app.ws.data["projects"] and not app.ws.data["mindmaps"]
        with patch("app.filedialog.askdirectory",return_value=str(other)), \
             patch("app.simpledialog.askstring",return_value="第二项目"):
            app.add_project()
        assert len(app.ws.data["projects"])==1
        assert not app.ws.data["mindmaps"]
        assert len(app.project_tree.get_children())==1
        passed("切换项目可取消或保存；独立目录互不混入，空目录可建立项目")
        app.ws.data["name"]="关闭保存项目名";app.changed()
        with patch("app.messagebox.askyesnocancel",return_value=True):app.close()
        ws=Workspace(other);assert ws.data["name"]=="关闭保存项目名";ws.close()
        passed("关闭选择保存后持久化项目修改")
    result={"version":VERSION,"passed":len(CHECKS),"failed":0,"checks":CHECKS}
    Path("project_flow_results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
