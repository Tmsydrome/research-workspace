"""Attachment clipboard checks using an isolated clipboard sink, version 1.0.10."""
import ctypes,json,os,struct,tempfile,tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from app import App
from workspace import VERSION
from native_drop import copy_files_to_clipboard

def main():
    checks=[]
    real=ctypes.WinDLL("kernel32",use_last_error=True)
    for name,args,result in [("GlobalAlloc",[ctypes.c_uint,ctypes.c_size_t],ctypes.c_void_p),
            ("GlobalLock",[ctypes.c_void_p],ctypes.c_void_p),("GlobalUnlock",[ctypes.c_void_p],ctypes.c_int),
            ("GlobalFree",[ctypes.c_void_p],ctypes.c_void_p)]:
        function=getattr(real,name);function.argtypes=args;function.restype=result
    kernel=SimpleNamespace(**{name:Mock(wraps=getattr(real,name)) for name in ["GlobalAlloc","GlobalLock","GlobalUnlock","GlobalFree"]})
    held={}
    def clear():
        for handle in held.values():real.GlobalFree(handle)
        held.clear();return True
    def publish(kind,handle):held[kind]=handle;return handle
    user=SimpleNamespace(OpenClipboard=Mock(return_value=True),EmptyClipboard=Mock(side_effect=clear),
        CloseClipboard=Mock(return_value=True),RegisterClipboardFormatW=Mock(return_value=0xc001),
        SetClipboardData=Mock(side_effect=publish))
    def load(name,**kwargs):return user if name=="user32" else kernel
    def read_paths():
        shell=ctypes.windll.shell32
        shell.DragQueryFileW.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_wchar_p,ctypes.c_uint]
        paths=[]
        for index in range(shell.DragQueryFileW(held[15],0xffffffff,None,0)):
            size=shell.DragQueryFileW(held[15],index,None,0)
            text=ctypes.create_unicode_buffer(size+1)
            shell.DragQueryFileW(held[15],index,text,size+1);paths.append(text.value)
        return paths
    try:
        with tempfile.TemporaryDirectory(prefix="research_clipboard_") as tmp:
            base=Path(tmp);first=base/"原稿 😀.html";first.write_bytes(b"<h1>Fixture</h1>")
            second=base/"数据.xlsx";second.write_bytes(b"Spreadsheet fixture")
            folder=base/"网页资料";folder.mkdir();(folder/"index.html").write_text('<link href="style.css">',encoding="utf-8")
            (folder/"style.css").write_text("body{color:navy}",encoding="utf-8")
            with patch("native_drop.ctypes.WinDLL",side_effect=load),patch("native_drop.time.sleep"):
                assert copy_files_to_clipboard([first,second,folder,first],1234)==3
                assert read_paths()==[str(p.resolve()) for p in (first,second,folder)]
                pointer=real.GlobalLock(held[0xc001])
                try:assert struct.unpack("<I",ctypes.string_at(pointer,4))[0]==1
                finally:real.GlobalUnlock(held[0xc001])
                assert user.OpenClipboard.call_args.args==(1234,) and not kernel.GlobalFree.called
                checks.append("Windows Shell 解析中文与多选文件、目录，复制模式及内存所有权正确")
                snapshot=dict(held);user.EmptyClipboard.reset_mock();kernel.GlobalFree.reset_mock()
                user.OpenClipboard.return_value=False
                try:copy_files_to_clipboard([first],1234);raise AssertionError("Expected clipboard busy")
                except OSError:pass
                assert held==snapshot and not user.EmptyClipboard.called and kernel.GlobalFree.call_count==2
                user.OpenClipboard.return_value=True;kernel.GlobalFree.reset_mock()
                user.SetClipboardData.side_effect=lambda kind,handle:publish(kind,handle) if kind==15 else 0
                try:copy_files_to_clipboard([second],1234);raise AssertionError("Expected transfer failure")
                except OSError:pass
                assert kernel.GlobalFree.call_count==1 and read_paths()==[str(second.resolve())]
                assert user.CloseClipboard.called
                checks.append("剪贴板占用时保留原内容，部分写入失败时释放剩余内存并关闭接口")
            os.environ["RESEARCH_WORKSPACE_CONFIG"]=str(base/"config")
            root=tk.Tk();root.withdraw();app=App(root);app.open_workspace(str(base/"workspace"))
            try:
                project=app.ws.add_project("附件测试");mindmap=app.ws.add_map(project,"资料")
                parent=app.ws.data["mindmaps"][mindmap]["rootNodeId"]
                nodes=[app.ws.add_node(parent,name) for name in ["原稿","数据","资源"]]
                ids=[app.ws.import_attachment(node,file,"index.html" if file.is_dir() else None) for node,file in zip(nodes,[first,second,folder])]
                app.load_map(mindmap);app.select_node(nodes[0])
                with patch("native_drop.copy_files_to_clipboard",side_effect=lambda paths,owner:len(paths)) as copied, \
                     patch("app.filedialog.askdirectory",side_effect=AssertionError("Unexpected directory chooser")):
                    assert app.copy_selected_attachments()=="break"
                    assert copied.call_args.args[0]==[app.ws.attachment_path(ids[0])]
                    assert "1 个附件" in app.status.get()
                    app.select_node(nodes[1],ctrl=True);app.attach_tree.selection_set(ids[:2])
                    with patch.object(app.attach_tree,"identify_row",return_value=ids[1]),patch.object(app,"menu") as menu:
                        app.attachment_context(SimpleNamespace(y=10,x_root=0,y_root=0))
                        action=next(call.kwargs for call in menu.return_value.add_command.call_args_list if call.kwargs["label"]=="复制附件")
                        assert action["accelerator"]=="Ctrl+C" and action["state"]=="normal"
                        action["command"]()
                    assert set(app.attach_tree.selection())==set(ids[:2])
                    assert set(copied.call_args.args[0])=={app.ws.attachment_path(i) for i in ids[:2]}
                    app.attach_tree.selection_set(ids[1]);app.copy_selected_attachments()
                    assert copied.call_args.args[0]==[app.ws.attachment_path(ids[1])]
                    assert "copy_selected_attachments" in app.attach_tree.bind("<Control-c>")
                    checks.append("单个与多个节点汇总附件，右键保留多选范围，支持部分选择和 Ctrl+C")
                    app.select_node(nodes[2]);before=json.dumps(app.ws.data,sort_keys=True)
                    app.copy_selected_attachments();target=app.ws.attachment_path(ids[2])
                    assert copied.call_args.args[0]==[target] and target.is_dir()
                    assert (target/"style.css").read_bytes()==(folder/"style.css").read_bytes()
                    assert json.dumps(app.ws.data,sort_keys=True)==before
                    checks.append("HTML 资源附件复制整个目录，项目数据与归档文件保持一致")
                    copied.reset_mock();app.attach_tree.selection_remove(*app.attach_tree.selection())
                    app.copy_selected_attachments();copied.assert_not_called()
                    app.select_node(nodes[0]);app.ws.attachment_path(ids[0]).unlink()
                    with patch.object(app,"error") as error:app.copy_selected_attachments();error.assert_called_once()
                    copied.assert_not_called()
                    checks.append("空选择和缺失附件先行检查，复制仅操作已选附件")
            finally:
                app.ws.close();app.native_drop.close();root.destroy()
    finally:clear()
    report={"version":VERSION,"passed":len(checks),"failed":0,"checks":[{"test":name,"status":"PASS"} for name in checks]}
    Path("clipboard_flow_results.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False))

if __name__=="__main__":main()
