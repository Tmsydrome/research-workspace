"""Windows file drop and clipboard transfer, version 1.0.10."""
import ctypes
import uuid
import os,json
import struct,time
from pathlib import Path
from ctypes import wintypes

HRESULT=ctypes.c_long
DWORD=wintypes.DWORD
PVOID=ctypes.c_void_p
CALL=ctypes.WINFUNCTYPE

def dib_to_bmp(data):
    """Wrap a Windows clipboard DIB in a bitmap file header."""
    if len(data)<40:raise ValueError("剪贴板图片头不完整")
    size,width,height,planes,bits,compression=struct.unpack_from("<IiiHHI",data)
    if size<40 or size>len(data) or width<=0 or not height or planes!=1:
        raise ValueError("剪贴板图片格式无效")
    colors=struct.unpack_from("<I",data,32)[0]
    palette=colors or (1<<bits if bits<=8 else 0)
    offset=size+palette*4+(12 if size==40 and compression==3 else 16 if size==40 and compression==6 else 0)
    if offset>=len(data):raise ValueError("剪贴板图片数据不完整")
    return struct.pack("<2sIHHI",b"BM",len(data)+14,0,0,offset+14)+data


def read_clipboard(owner):
    """Read files, image bytes, or Unicode text while preserving the clipboard."""
    user=ctypes.WinDLL("user32",use_last_error=True)
    kernel=ctypes.WinDLL("kernel32",use_last_error=True)
    shell=ctypes.WinDLL("shell32",use_last_error=True)
    user.OpenClipboard.argtypes=[wintypes.HWND]
    user.GetClipboardData.argtypes=[wintypes.UINT];user.GetClipboardData.restype=PVOID
    user.IsClipboardFormatAvailable.argtypes=[wintypes.UINT]
    user.RegisterClipboardFormatW.argtypes=[wintypes.LPCWSTR];user.RegisterClipboardFormatW.restype=wintypes.UINT
    kernel.GlobalLock.argtypes=[PVOID];kernel.GlobalLock.restype=PVOID
    kernel.GlobalUnlock.argtypes=[PVOID]
    kernel.GlobalSize.argtypes=[PVOID];kernel.GlobalSize.restype=ctypes.c_size_t
    shell.DragQueryFileW.argtypes=[PVOID,wintypes.UINT,wintypes.LPWSTR,wintypes.UINT]
    for attempt in range(5):
        if user.OpenClipboard(owner):break
        if attempt==4:raise OSError("剪贴板正忙，请稍后重试")
        time.sleep(.03)
    try:
        if user.IsClipboardFormatAvailable(15):
            handle=user.GetClipboardData(15)
            if not handle:raise OSError("无法读取剪贴板文件")
            paths=[]
            for index in range(shell.DragQueryFileW(handle,0xffffffff,None,0)):
                length=shell.DragQueryFileW(handle,index,None,0)
                name=ctypes.create_unicode_buffer(length+1)
                shell.DragQueryFileW(handle,index,name,length+1)
                paths.append(name.value)
            return {"files":list(dict.fromkeys(paths))}
        png=user.RegisterClipboardFormatW("PNG")
        # Office selections may publish both Unicode text and a rendered bitmap.
        for kind,suffix in ((13,None),(png,".png"),(17,".bmp"),(8,".bmp")):
            if not kind or not user.IsClipboardFormatAvailable(kind):continue
            handle=user.GetClipboardData(kind)
            if not handle:continue
            pointer=kernel.GlobalLock(handle)
            if not pointer:raise OSError("无法读取剪贴板内容")
            try:
                if suffix is None:
                    text=ctypes.wstring_at(pointer)
                    if text:return {"text":text}
                else:data=ctypes.string_at(pointer,kernel.GlobalSize(handle))
            finally:kernel.GlobalUnlock(handle)
            if suffix is None:continue
            if suffix==".bmp":data=dib_to_bmp(data)
            elif not data.startswith(b"\x89PNG\r\n\x1a\n"):raise ValueError("剪贴板 PNG 图片格式无效")
            return {"image":(suffix,data)}
        return {}
    finally:user.CloseClipboard()


def copy_files_to_clipboard(paths,owner):
    if os.name!="nt":raise OSError("文件复制需要 Windows")
    files=list(dict.fromkeys(str(Path(p).resolve(strict=True)) for p in paths))
    if not files:raise ValueError("请选择要复制的附件")
    if not owner:raise ValueError("复制需要有效的窗口")
    user=ctypes.WinDLL("user32",use_last_error=True)
    kernel=ctypes.WinDLL("kernel32",use_last_error=True)
    user.OpenClipboard.argtypes=[wintypes.HWND]
    user.EmptyClipboard.argtypes=[]
    user.CloseClipboard.argtypes=[]
    user.SetClipboardData.argtypes=[wintypes.UINT,PVOID]
    user.SetClipboardData.restype=PVOID
    user.RegisterClipboardFormatW.argtypes=[wintypes.LPCWSTR]
    user.RegisterClipboardFormatW.restype=wintypes.UINT
    kernel.GlobalAlloc.argtypes=[wintypes.UINT,ctypes.c_size_t]
    kernel.GlobalAlloc.restype=PVOID
    kernel.GlobalLock.argtypes=[PVOID];kernel.GlobalLock.restype=PVOID
    kernel.GlobalUnlock.argtypes=[PVOID]
    kernel.GlobalFree.argtypes=[PVOID];kernel.GlobalFree.restype=PVOID
    effect=user.RegisterClipboardFormatW("Preferred DropEffect")
    if not effect:raise OSError("无法注册文件复制格式")
    payload=struct.pack("<IiiII",20,0,0,0,1)+("\0".join(files)+"\0\0").encode("utf-16-le")
    owned=[];buffers=[];opened=False
    try:
        for kind,data in ((15,payload),(effect,struct.pack("<I",1))):
            handle=kernel.GlobalAlloc(0x42,len(data))
            if not handle:raise OSError("无法分配文件剪贴板内存")
            owned.append(handle)
            pointer=kernel.GlobalLock(handle)
            if not pointer:raise OSError("无法写入文件剪贴板内存")
            try:ctypes.memmove(pointer,data,len(data))
            finally:kernel.GlobalUnlock(handle)
            buffers.append((kind,handle))
        for attempt in range(5):
            opened=bool(user.OpenClipboard(owner))
            if opened:break
            if attempt<4:time.sleep(.03)
        if not opened:raise OSError("剪贴板正忙，请稍后重试")
        if not user.EmptyClipboard():raise OSError("无法准备文件剪贴板")
        for kind,handle in buffers:
            if not user.SetClipboardData(kind,handle):raise OSError("附件写入剪贴板失败")
            owned.remove(handle)  # Windows owns each published memory block.
        return len(files)
    finally:
        if opened:user.CloseClipboard()
        for handle in owned:kernel.GlobalFree(handle)

class POINTL(ctypes.Structure):
    _fields_=[("x",wintypes.LONG),("y",wintypes.LONG)]

class FORMATETC(ctypes.Structure):
    _fields_=[("cfFormat",wintypes.WORD),("ptd",PVOID),("dwAspect",DWORD),
              ("lindex",wintypes.LONG),("tymed",DWORD)]

class STGMEDIUM(ctypes.Structure):
    _fields_=[("tymed",DWORD),("hGlobal",PVOID),("pUnkForRelease",PVOID)]

class COMObject(ctypes.Structure):
    _fields_=[("vtable",ctypes.POINTER(PVOID))]

def method(obj,index,result,*arguments):
    table=ctypes.cast(obj,ctypes.POINTER(COMObject)).contents.vtable
    return CALL(result,PVOID,*arguments)(table[index])

def files_from_object(obj):
    medium=STGMEDIUM()
    form=FORMATETC(15,None,1,-1,1)  # CF_HDROP, DVASPECT_CONTENT, TYMED_HGLOBAL.
    get=method(obj,3,HRESULT,ctypes.POINTER(FORMATETC),ctypes.POINTER(STGMEDIUM))
    if get(obj,ctypes.byref(form),ctypes.byref(medium))<0:
        return []
    try:
        shell=ctypes.windll.shell32
        shell.DragQueryFileW.argtypes=[PVOID,wintypes.UINT,wintypes.LPWSTR,wintypes.UINT]
        paths=[]
        for i in range(shell.DragQueryFileW(medium.hGlobal,0xffffffff,None,0)):
            n=shell.DragQueryFileW(medium.hGlobal,i,None,0)
            name=ctypes.create_unicode_buffer(n+1)
            shell.DragQueryFileW(medium.hGlobal,i,name,n+1)
            paths.append(name.value)
        return paths
    finally:
        ole=ctypes.windll.ole32
        ole.ReleaseStgMedium.argtypes=[ctypes.POINTER(STGMEDIUM)]
        ole.ReleaseStgMedium(ctypes.byref(medium))

class FileDropTarget:
    def __init__(self,hover,drop,leave,error):
        self.hover,self.drop,self.leave,self.error=hover,drop,leave,error
        self.paths=[]
        self.refs=1
        supported={uuid.UUID(x).bytes_le for x in (
            "00000000-0000-0000-C000-000000000046",
            "00000122-0000-0000-C000-000000000046")}
        def query(this,iid,out):
            if ctypes.string_at(iid,16) in supported:
                out[0]=ctypes.cast(ctypes.pointer(self.obj),PVOID)
                self.refs+=1
                return 0
            out[0]=None
            return -2147467262
        def add(this):
            self.refs+=1
            return self.refs
        def release(this):
            self.refs=max(0,self.refs-1)
            return self.refs
        def trace(event,**values):
            path=os.environ.get("RESEARCH_WORKSPACE_DROP_TRACE")
            if path:
                try:
                    with open(path,"a",encoding="utf-8") as f:
                        f.write(json.dumps({"event":event,**values},ensure_ascii=False)+"\n")
                except OSError:
                    pass
        def update(point,effect):
            effect[0]=1 if self.paths and self.hover(point.x,point.y) else 0
        def enter(this,data,keys,point,effect):
            try:
                self.paths=files_from_object(data)
                update(point,effect)
                trace("enter",paths=self.paths,x=point.x,y=point.y,effect=int(effect[0]))
            except Exception as e:
                effect[0]=0;self.error(e)
            return 0
        def over(this,keys,point,effect):
            try:
                update(point,effect)
                trace("over",x=point.x,y=point.y,effect=int(effect[0]))
            except Exception as e:
                effect[0]=0;self.error(e)
            return 0
        def leave(this):
            trace("leave")
            self.paths=[];self.leave()
            return 0
        def drop(this,data,keys,point,effect):
            try:
                paths=files_from_object(data)
                accepted=bool(paths) and self.hover(point.x,point.y)
                effect[0]=1 if accepted else 0
                trace("drop",paths=paths,x=point.x,y=point.y,effect=int(effect[0]))
                if accepted:self.drop(paths,point.x,point.y)
            except Exception as e:
                effect[0]=0;self.error(e)
            finally:
                self.paths=[];self.leave()
            return 0
        signatures=[
            (HRESULT,[PVOID,PVOID,ctypes.POINTER(PVOID)],query),
            (wintypes.ULONG,[PVOID],add),(wintypes.ULONG,[PVOID],release),
            (HRESULT,[PVOID,PVOID,DWORD,POINTL,ctypes.POINTER(DWORD)],enter),
            (HRESULT,[PVOID,DWORD,POINTL,ctypes.POINTER(DWORD)],over),
            (HRESULT,[PVOID],leave),
            (HRESULT,[PVOID,PVOID,DWORD,POINTL,ctypes.POINTER(DWORD)],drop)]
        self.callbacks=[CALL(restype,*args)(func) for restype,args,func in signatures]
        self.table=(PVOID*7)(*(ctypes.cast(f,PVOID).value for f in self.callbacks))
        self.obj=COMObject(ctypes.cast(self.table,ctypes.POINTER(PVOID)))

class NativeFileDrop:
    def __init__(self,handles,hover,drop,leave,error):
        self.ole=ctypes.windll.ole32
        self.ole.OleInitialize.argtypes=[PVOID]
        self.ole.OleInitialize.restype=HRESULT
        self.ole.RegisterDragDrop.argtypes=[wintypes.HWND,PVOID]
        self.ole.RegisterDragDrop.restype=HRESULT
        self.ole.RevokeDragDrop.argtypes=[wintypes.HWND]
        result=self.ole.OleInitialize(None)
        if result<0:raise OSError("OLE 初始化失败：0x%08X"%(result&0xffffffff))
        self.target=FileDropTarget(hover,drop,leave,error)
        self.handles=[]
        try:
            for handle in dict.fromkeys(handles):
                result=self.ole.RegisterDragDrop(handle,ctypes.byref(self.target.obj))
                if result<0:raise OSError("OLE 文件拖放注册失败：0x%08X"%(result&0xffffffff))
                self.handles.append(handle)
        except Exception:
            self.close();raise
    def close(self):
        for handle in self.handles:self.ole.RevokeDragDrop(handle)
        self.handles=[]
        self.ole.OleUninitialize()
