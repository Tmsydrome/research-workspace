"""Node paste and clipboard decoding checks, version 1.0.10."""
import base64,ctypes,json,os,struct,tempfile,time,tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from app import App
from native_drop import read_clipboard,dib_to_bmp
from workspace import VERSION


def main():
    checks=[]
    png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWQAAAABJRU5ErkJggg==')
    dib=struct.pack('<IiiHHIIiiII',40,2,1,1,24,0,8,0,0,0,0)+bytes([0,0,255,0,255,0,0,0])
    bmp=dib_to_bmp(dib)
    assert bmp[:2]==b'BM' and struct.unpack_from('<I',bmp,10)[0]==54
    for invalid in (b'',bytes(40)):
        try:dib_to_bmp(invalid);raise AssertionError('Expected invalid image')
        except ValueError:pass
    checks.append('DIB bitmap header, pixels and invalid-image validation')
    real=ctypes.WinDLL('kernel32',use_last_error=True)
    for name,args,result in [('GlobalAlloc',[ctypes.c_uint,ctypes.c_size_t],ctypes.c_void_p),
        ('GlobalLock',[ctypes.c_void_p],ctypes.c_void_p),('GlobalUnlock',[ctypes.c_void_p],ctypes.c_int),
        ('GlobalFree',[ctypes.c_void_p],ctypes.c_void_p)]:
        fn=getattr(real,name);fn.argtypes=args;fn.restype=result
    handles={}
    user=SimpleNamespace(OpenClipboard=Mock(return_value=True),CloseClipboard=Mock(),
        GetClipboardData=Mock(side_effect=lambda k:handles[k]),
        IsClipboardFormatAvailable=Mock(side_effect=lambda k:k in handles),RegisterClipboardFormatW=Mock(return_value=0xc001))
    def set_formats(formats):
        for h in handles.values():real.GlobalFree(h)
        handles.clear()
        for kind,data in formats.items():
            h=real.GlobalAlloc(0x42,len(data));p=real.GlobalLock(h)
            ctypes.memmove(p,data,len(data));real.GlobalUnlock(h);handles[kind]=h
    def dll(name,**kwargs):return user if name=='user32' else real if name=='kernel32' else ctypes.windll.shell32
    try:
        with patch('native_drop.ctypes.WinDLL',side_effect=dll),patch('native_drop.time.sleep'):
            set_formats({13:'中文 😀\t单元格\n第二行\0'.encode('utf-16-le')})
            assert read_clipboard(123)['text']=='中文 😀\t单元格\n第二行'
            set_formats({8:dib,13:'图片说明\0'.encode('utf-16-le')})
            assert read_clipboard(123)=={'text':'图片说明'}
            set_formats({8:dib})
            assert read_clipboard(123)=={'image':('.bmp',bmp)}
            set_formats({0xc001:png,8:dib})
            assert read_clipboard(123)=={'image':('.png',png)}
            files=['C:\\资料\\视频.mp4','C:\\资料\\数据.xlsx']
            set_formats({15:struct.pack('<IiiII',20,0,0,0,1)+('\0'.join(files)+'\0\0').encode('utf-16-le'),0xc001:png})
            assert read_clipboard(123)=={'files':files}
            assert handles and user.CloseClipboard.call_count==5
            user.OpenClipboard.return_value=False
            try:read_clipboard(123);raise AssertionError('Expected busy clipboard')
            except OSError:pass
            checks.append('Native Unicode, file priority, PNG/DIB image priority and clipboard release')
    finally:
        for h in handles.values():real.GlobalFree(h)
    with tempfile.TemporaryDirectory(prefix='research_paste_') as tmp:
        base=Path(tmp);os.environ['RESEARCH_WORKSPACE_CONFIG']=str(base/'config')
        root=tk.Tk();app=App(root);app.open_workspace(str(base/'workspace'))
        errors=[];app.error=lambda e:errors.append(str(e))
        try:
            project=app.ws.add_project('粘贴测试');mindmap=app.ws.add_map(project,'资料')
            parent=app.ws.data['mindmaps'][mindmap]['rootNodeId'];node=app.ws.add_node(parent,'当前节点')
            child=app.ws.add_node(node,'子节点');app.load_map(mindmap);app.select_node(node)
            root.update();app.canvas.focus_force();root.update()
            def paste(payload,keyboard=False):
                with patch('native_drop.read_clipboard',return_value=payload) as reader:
                    if keyboard:app.canvas.event_generate('<Control-v>');root.update()
                    else:assert app.paste_to_node()=='break'
                    deadline=time.monotonic()+10
                    while app.busy and time.monotonic()<deadline:root.update();time.sleep(.02)
                    assert not app.busy and not errors,errors
                    reader.assert_called_once()
            paste({'text':'第一段\t数据\n第二行'},True)
            assert app.ws.data['nodes'][node]['bodyRichText']['text']=='第一段\t数据\n第二行'
            paste({'text':'追加文本'})
            assert app.ws.data['nodes'][node]['bodyRichText']['text'].endswith('\n追加文本')
            app.undo();assert app.ws.data['nodes'][node]['bodyRichText']['text']=='第一段\t数据\n第二行'
            assert not app.ws.data['nodes'][child]['bodyRichText']['text']
            checks.append('Ctrl+V routes Unicode text to focused node body, appends and supports undo')
            files=[]
            for suffix in ['.docx','.txt','.xlsx','.pptx','.mp4','.mp3','.zip','.stl','.json','.unknown']:
                file=base/('资料'+suffix);file.write_bytes(('fixture '+suffix).encode());files.append(file)
            folder=base/'文件夹';folder.mkdir();(folder/'说明.txt').write_text('资源',encoding='utf-8')
            files.append(folder)
            paste({'files':[str(p) for p in files]})
            ids=list(app.ws.data['nodes'][node]['attachmentIds'])
            assert len(ids)==len(files) and not app.ws.data['nodes'][child]['attachmentIds']
            assert len(app.ws.data['nodes'])==3
            for attachment,source in zip(ids,files):
                archived=app.ws.attachment_path(attachment)
                assert archived.is_dir() if source.is_dir() else archived.read_bytes()==source.read_bytes()
            checks.append('Multiple file formats and folders attach to current node with source bytes preserved')
            paste({'image':('.png',png)});paste({'image':('.bmp',bmp)})
            for attachment,data in zip(app.ws.data['nodes'][node]['attachmentIds'][-2:],[png,bmp]):
                target=app.ws.attachment_path(attachment);assert target.read_bytes()==data
                assert app.attachment_kind(app.ws.data['attachments'][attachment])=='image'
            checks.append('PNG and screenshot DIB images archived as independent node attachments')
            with patch('native_drop.read_clipboard') as reader:
                assert app.paste_to_node(SimpleNamespace(widget=app.body)) is None
                assert app.paste_to_node(SimpleNamespace(widget=app.search_entry)) is None
                reader.assert_not_called()
            checks.append('Text editor and search entry keep normal paste behavior')
            for suffix,kind in {'.mp4':'video','.MP3':'audio','.7z':'archive','.stl':'model','.json':'code','.txt':'text','.pdf':'pdf','.xyz':'file'}.items():
                assert app.attachment_kind({'originalName':'样本'+suffix})==kind
                assert kind in app.file_icons
            app.inspector_tabs.select(app.canvas_settings);root.update()
            assert app.style.lookup('TNotebook.Tab','background',('selected',))==app.theme['accent']
            assert '12' in str(app.style.lookup('TNotebook.Tab','font',('selected',)))
            assert '10' in str(app.style.lookup('TNotebook.Tab','font',('!selected',)))
            checks.append('File icons resolve by extension; selected inspector tab is highlighted and larger')
            app.ws.save()
        finally:
            app.ws.close();app.native_drop.close();root.destroy()
    report={'version':VERSION,'passed':len(checks),'failed':0,'checks':checks}
    Path('paste_flow_results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True))


if __name__=='__main__':main()
