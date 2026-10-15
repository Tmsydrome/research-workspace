"""Local HTML attachment editor bridge, version 1.0.4."""
from __future__ import annotations
import hashlib
import json
import mimetypes
import os
import queue
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
from workspace import contained,clean_name

EDITOR=Path(__file__).parent/"resources"/"v0.4.7_HTML修订批注工具.html"
ADAPTER=EDITOR.parent/"workspace_editor.js"

def editor_page():
    text=EDITOR.read_text(encoding="utf-8")
    text=re.sub(r'<a class="creator-profile"[^>]*>(.*?)</a>',
                r'<div class="creator-profile" aria-label="Tmsydrome">\1</div>',text,flags=re.S)
    text=re.sub(r'\.creator-profile:hover\{[^}]*\}',"",text)
    before,after=text.rsplit("</body>",1)
    return before+"<script>\n"+ADAPTER.read_text(encoding="utf-8")+"</script>\n</body>"+after

def digest(content):
    return hashlib.sha256(content).hexdigest()

def decode_html(content):
    header=content[:4096]
    if content.startswith((b"\xff\xfe",b"\xfe\xff")):
        return content.decode("utf-16")
    found=re.search(br'charset\s*=\s*["\']?\s*([\w-]+)',header,re.I)
    encodings=["utf-8-sig"]+([found[1].decode("ascii")] if found else [])+["gb18030"]
    for encoding in dict.fromkeys(encodings):
        try:
            return content.decode(encoding)
        except (UnicodeError,LookupError):
            pass
    raise ValueError("HTML 文字编码无法识别，请先另存为 UTF-8")

def desktop_directory():
    if os.name!="nt":return Path.home()/"Desktop"
    import ctypes
    import uuid
    folder=(ctypes.c_byte*16).from_buffer_copy(uuid.UUID("B4BFCC3A-DB2C-424C-B029-7FE99A87C641").bytes_le)
    path=ctypes.c_wchar_p()
    shell=ctypes.windll.shell32
    shell.SHGetKnownFolderPath.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_void_p,ctypes.POINTER(ctypes.c_wchar_p)]
    result=shell.SHGetKnownFolderPath(ctypes.byref(folder),0,None,ctypes.byref(path))
    if result:raise OSError("无法读取系统桌面目录")
    try:return Path(path.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree.argtypes=[ctypes.c_void_p]
        ctypes.windll.ole32.CoTaskMemFree(path)

def export_to_desktop(text,name):
    if not isinstance(name,str) or not name.lower().endswith((".html",".htm")):
        raise ValueError("导出文件应为 HTML 格式")
    directory=desktop_directory().resolve()
    directory.mkdir(parents=True,exist_ok=True)
    stem=clean_name(name.rsplit(".",1)[0])
    number=1
    while True:
        target=directory/(stem+("" if number==1 else "_"+str(number))+".html")
        try:stream=target.open("xb")
        except FileExistsError:
            number+=1
            continue
        try:
            with stream:
                stream.write(text.encode("utf-8"));stream.flush();os.fsync(stream.fileno())
            return target
        except BaseException:
            target.unlink(missing_ok=True)
            raise

class HtmlEditor:
    def __init__(self):
        self.sessions={}
        self.events=queue.Queue()
        self.lock=threading.RLock()
        bridge=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):
                pass

            def reply(self,status,data,kind="application/json; charset=utf-8"):
                if isinstance(data,dict):
                    data=json.dumps(data,ensure_ascii=False).encode("utf-8")
                elif isinstance(data,str):
                    data=data.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type",kind)
                self.send_header("Content-Length",str(len(data)))
                self.send_header("Cache-Control","no-store")
                self.send_header("X-Content-Type-Options","nosniff")
                self.send_header("Referrer-Policy","no-referrer")
                self.end_headers()
                self.wfile.write(data)

            def route(self):
                if self.headers.get("Host")!=bridge.origin.split("//")[1]:
                    raise PermissionError("请求主机无效")
                parts=urlsplit(self.path).path.split("/",2)
                if len(parts)!=3 or parts[1] not in bridge.sessions:
                    raise PermissionError("编辑会话已关闭，请从工作区重新打开附件")
                session=bridge.sessions[parts[1]]
                # Recheck containment so a renamed archive or a new junction cannot widen access.
                contained(session["root"],session["file"].relative_to(session["root"]),exists=True)
                return parts[1],unquote(parts[2]),session

            def do_GET(self):
                try:
                    with bridge.lock:
                        token,route,s=self.route()
                        if route=="editor":
                            self.reply(200,editor_page(),"text/html; charset=utf-8")
                        elif route=="document":
                            data=s["file"].read_bytes()
                            relative=s["file"].parent.relative_to(s["root"]).as_posix()
                            base=bridge.origin+"/"+token+"/files/"+("" if relative=="." else quote(relative,safe="/")+"/")
                            self.reply(200,{"name":s["file"].name,"text":decode_html(data),"etag":digest(data),"base":base,"dirty":s["dirty"]})
                        elif route.startswith("files/"):
                            p=contained(s["root"],route[6:],exists=True)
                            if not p.is_file():
                                raise FileNotFoundError()
                            kind=mimetypes.guess_type(p.name)[0] or "application/octet-stream"
                            self.reply(200,p.read_bytes(),kind)
                        else:
                            raise FileNotFoundError()
                except PermissionError as e:
                    self.reply(403,{"error":str(e)})
                except (FileNotFoundError,ValueError,OSError) as e:
                    self.reply(404,{"error":str(e)})

            def do_POST(self):
                try:
                    with bridge.lock:
                        token,route,s=self.route()
                        if route not in {"save","state","export"} or self.headers.get("Origin")!=bridge.origin:
                            raise PermissionError("保存请求来源无效")
                        size=int(self.headers.get("Content-Length","0"))
                        if not 0<size<=50*1024*1024:
                            raise ValueError("HTML 保存大小应在 50 MB 以内")
                        body=json.loads(self.rfile.read(size))
                        if route=="state":
                            s["dirty"]=body.get("dirty") is True
                            self.reply(200,{"ok":True})
                            return
                        text=body["text"]
                        if not isinstance(text,str) or not text.strip():
                            raise ValueError("HTML 保存内容为空")
                        if route=="export":
                            target=export_to_desktop(text,body["name"])
                            self.reply(200,{"ok":True,"name":target.name,"path":str(target)})
                            return
                        current=s["file"].read_bytes()
                        if body.get("etag")!=digest(current):
                            self.reply(409,{"error":"归档副本已被另一窗口修改，请导出当前内容或重新加载归档。"})
                            return
                        target=s["file"]
                        result=text.encode("utf-8")
                        s["history"].mkdir(parents=True,exist_ok=True)
                        backup=s["history"]/(str(time.time_ns())+"_"+target.name)
                        with backup.open("xb") as stream:
                            stream.write(current)
                        temp=None
                        try:
                            with tempfile.NamedTemporaryFile(dir=target.parent,prefix=".html-save-",suffix=".tmp",delete=False) as stream:
                                temp=Path(stream.name)
                                stream.write(result)
                                stream.flush()
                                os.fsync(stream.fileno())
                            assert temp.read_bytes()==result
                            os.replace(temp,target)
                        finally:
                            if temp:
                                temp.unlink(missing_ok=True)
                        s["dirty"]=False
                        bridge.events.put(s["attachment"])
                        self.reply(200,{"etag":digest(result),"savedAt":time.strftime("%H:%M:%S")})
                except PermissionError as e:
                    self.reply(403,{"error":str(e)})
                except (KeyError,ValueError,OSError,TypeError) as e:
                    self.reply(400,{"error":str(e)})
        self.server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
        self.server.daemon_threads=True
        self.origin="http://127.0.0.1:"+str(self.server.server_port)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def url(self,attachment,file,resources,history):
        file,resources=Path(file).resolve(),Path(resources).resolve()
        contained(resources,file.relative_to(resources),exists=True)
        if file.suffix.lower() not in {".html",".htm"}:
            raise ValueError("编辑器仅打开 HTML 文件")
        token=secrets.token_urlsafe(32)
        with self.lock:
            self.sessions[token]={"attachment":attachment,"file":file,"root":resources,"history":Path(history),"dirty":False}
        return self.origin+"/"+token+"/editor"

    def open(self,attachment,file,resources,history):
        url=self.url(attachment,file,resources,history)
        edge=Path(os.environ.get("PROGRAMFILES(X86)",r"C:\Program Files (x86)"))/"Microsoft/Edge/Application/msedge.exe"
        if edge.exists():
            subprocess.Popen([str(edge),"--app="+url])
        else:
            webbrowser.open(url)
        return url

    def has_unsaved(self):
        with self.lock:
            return any(s["dirty"] for s in self.sessions.values())

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)
        with self.lock:
            self.sessions.clear()
